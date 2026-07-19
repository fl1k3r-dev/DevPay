import asyncio
import logging
import signal
import json
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from src.cron.cron_launcher import check_and_expire_subscriptions
from src.models import Subscription, SubscriptionStatus
from src.services.cache import CacheService
from src.services.broker import BrokerService
from src.services.database import DatabaseService
from src.api.dependencies import get_cache_service, get_db_service, get_broker_service
from src.services.payment import PaymentService
from src.services.subscription import SubscriptionService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("DevPayWorker")

# Флаг/событие для управления жизненным циклом воркера
shutdown_event = asyncio.Event()

CHECK_INTERVAL = 30

cache_service: CacheService = None
db_service: DatabaseService = None
broker_service: BrokerService = None

async def check_and_renew_subscriptions():
    """Сканирует базу на наличие подписок, требующих списания или отмены."""
    async with db_service.session_maker() as session:
        service = SubscriptionService(session, broker_service)
        now = datetime.now(timezone.utc).replace(tzinfo=None)

        query = (
            select(Subscription)
            .options(joinedload(Subscription.plan))
            .where(
                Subscription.next_payment_at <= now,
                Subscription.status.in_([SubscriptionStatus.ACTIVE, SubscriptionStatus.PAST_DUE]),
                Subscription.auto_renew == True
            )
        )

        result = await session.execute(query)
        subscriptions_to_renew = result.scalars().all()

        if not subscriptions_to_renew:
            logger.info("Нет подписок для продления")
            return

        logger.info(f"Найдено {len(subscriptions_to_renew)} подписок для обработки.")

        for subscription in subscriptions_to_renew:
            try:
                # Передаем управление нашему сервису
                await service.process_subscription_renewal(subscription)
            except Exception as sub_err:
                # Обязательно изолируем ошибку одной подписки,
                # чтобы падение у одного юзера не ломало весь цикл для остальных
                logger.error(f"Ошибка при обработке подписки {subscription.id}: {sub_err}", exc_info=True)



async def process_payment_event(message_body: str | bytes | dict):
    """Callback-функция для обработки каждого сообщения из очереди."""
    try:
        if isinstance(message_body, dict):
            data = message_body
        else:
            data = json.loads(message_body.decode() if isinstance(message_body, bytes) else message_body)


        operation_id = data.get("operation_id") or data.get("transaction_id")
        user_id = data.get("user_id")
        subscription_id = data.get("subscription_id")

        logger.info(f"📥 Получено событие платежа: {operation_id} для пользователя {user_id}")

        # Уровень 1: Быстрая проверка идемпотентности в Redis (in-memory)
        if await cache_service.is_processed(operation_id):
            logger.warning(f"Транзакция {operation_id} уже обрабатывалась! Пропускаем.")
            return

        # Уровень 2: Открываем сессию базы данных локально для обработки этого платежа
        async with db_service.session_maker() as session:
            # Железная проверка идемпотентности в PostgreSQL (источник истины)
            if await db_service.payment_exists(operation_id):
                logger.info(f"🔄 [PostgreSQL] Обнаружен дубликат вебхука: {operation_id}. Пропускаем.")
                return

            # Инициализируем наш сервис платежей с ЖИВОЙ сессией
            payment_service = PaymentService(db_session=session)

            # Вызываем основную бизнес-логику активации подписки
            activated_subscription = await payment_service.process_succeeded_payment(
                subscription_id=str(subscription_id),
                gateway_payment_id=operation_id
            )

            if not activated_subscription:
                logger.error("Не удалось обработать платеж")
                return

            # Успешно применили изменения в БД! Теперь обновляем быстрый кэш в Redis
            period_days = activated_subscription.period_days_at_creation or 30
            expire_seconds = period_days * 86400

            await cache_service.set_user_subscription(user_id, status="active", expire_seconds=expire_seconds)
            logger.info(f"🚀 Подписка для {user_id} успешно активирована, кэш обновлен на {period_days} дней!")

    except Exception as e:
        logger.exception(f"Критическая ошибка при обработке сообщения: {e}")


def ask_exit(sig_name):
    """Слушатель сигналов ОС. Переводит воркер в режим завершения работы."""
    logger.info(f"Получен сигнал {sig_name}. Инициируем плавное завершение (Graceful Shutdown)...")
    shutdown_event.set()

async def main():
    global cache_service, db_service, broker_service

    logger.info("Запуск бэкграунд-воркера DevPay...")

    cache_service = await get_cache_service()
    broker_service = await get_broker_service()
    db_service = await get_db_service()

    # 1. Подключаем все внешние ресурсы
    await cache_service.connect()
    await db_service.connect()
    await broker_service.connect()

    # 2. Настраиваем планировщик задач (Scheduler)
    scheduler = AsyncIOScheduler()

    # Задача А: Проверка истекших тарифов (раз в 10 минут)
    scheduler.add_job(
        check_and_expire_subscriptions,
        "interval",
        minutes=10,
        args=[db_service, cache_service]
    )

    # Задача Б (НАША NEW!): Проверка автопродлений (раз в 30 секунд)
    scheduler.add_job(
        check_and_renew_subscriptions,
        "interval",
        seconds=CHECK_INTERVAL
    )

    scheduler.start()

    # 3. Настраиваем перехват сигналов ОС (SIGINT - Ctrl+C, SIGTERM - docker stop)
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda s=sig: ask_exit(s.name))

    # 4. Подписываемся на очередь событий
    await broker_service.start_consuming_from_exchange(
        exchange_name="payment_events_exchange",
        queue_name="worker_payment_events_queue",  # Уникальное имя очереди для воркера
        callback=process_payment_event
    )
    logger.info(f"Воркер успешно подписался на очередь worker_payment_events_queue и готов к работе.")

    # 5. Замираем и работаем, пока не взведется флаг shutdown_event
    await shutdown_event.wait()

    # ---------------- GRACEFUL SHUTDOWN SEQUENCE ----------------
    logger.info("🛑 Начинаем остановку воркера...")

    logger.info("Останавливаем планировщик задач...")
    scheduler.shutdown()

    logger.info("Останавливаем прием новых сообщений из RabbitMQ...")
    await broker_service.close()

    logger.info("Закрываем соединения с базами данных...")
    await db_service.close()
    await cache_service.close()

    logger.info("🏁 Воркер успешно и безопасно завершил работу.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Воркер остановлен вручную.")