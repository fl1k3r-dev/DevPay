import asyncio
import logging
import signal
import json
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from src.config import settings
from src.cron.cron_launcher import check_and_expire_subscriptions
from src.services.cache import CacheService
from src.services.broker import BrokerService
from src.services.database import DatabaseService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("DevPayWorker")

cache_service = CacheService(redis_url=settings.redis_url)
broker = BrokerService(amqp_url=settings.rabbitmq_url)
db_service = DatabaseService(database_url=settings.database_url)

# Флаг/событие для управления жизненным циклом воркера
shutdown_event = asyncio.Event()


async def process_payment_event(message_body: str | bytes | dict):
    """Callback-функция для обработки каждого сообщения из очереди."""
    try:
        if isinstance(message_body, dict):
            data = message_body
        else:
            data = json.loads(message_body.decode() if isinstance(message_body, bytes) else message_body)


        operation_id = data.get("operation_id") or data.get("transaction_id")
        user_id = data.get("user_id") or data.get("label") # В ЮMoney id пользователя лежит в label
        amount = data.get("amount")

        logger.info(f"📥 Получено событие платежа: {operation_id} для пользователя {user_id}")

        # Уровень 1: Быстрая проверка идемпотентности в Redis (in-memory)
        if await cache_service.is_processed(operation_id):
            logger.warning(f"Транзакция {operation_id} уже обрабатывалась! Пропускаем.")
            return

        # Уровень 2: Железная проверка идемпотентности в PostgreSQL (источник истины)
        if await db_service.payment_exists(operation_id):
            logger.info(f"🔄 [PostgreSQL] Обнаружен дубликат вебхука: {operation_id}. Пропускаем.")
            return

        # Если проверки пройдены — запускаем атомарную транзакцию активации
        subscription = await db_service.activate_subscription(user_id, amount, operation_id)

        if subscription is not None:
            # Определяем TTL для кэша на основе периода подписки (в секундах)
            period_days = subscription.period_days_at_creation or 30
            expire_seconds = period_days * 86400
            await cache_service.set_user_subscription(user_id, status="active", expire_seconds=expire_seconds)
            logger.info(f"🚀 Подписка для {user_id} успешно активирована, кэш обновлен на {period_days} дней!")
        else:
            logger.error(f"Ошибка при сохранении транзакции {operation_id} в базу данных.")

    except Exception as e:
        logger.exception(f"Критическая ошибка при обработке сообщения: {e}")

def ask_exit(sig_name):
    """Слушатель сигналов ОС. Переводит воркер в режим завершения работы."""
    logger.info(f"Получен сигнал {sig_name}. Инициируем плавное завершение (Graceful Shutdown)...")
    shutdown_event.set()

async def main():
    logger.info("Запуск бэкграунд-воркера DevPay...")

    # 1. Подключаем все внешние ресурсы
    await cache_service.connect()
    await db_service.connect()

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        check_and_expire_subscriptions,
        "interval",
        minutes=10,
        args=[db_service, cache_service]
    )
    scheduler.start()

    await broker.connect()

    # 2. Настраиваем перехват сигналов ОС (SIGINT - Ctrl+C, SIGTERM - docker stop)
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda s=sig: ask_exit(s.name))

    # 3. Подписываемся на очередь событий
    QUEUE_NAME = "payment_events"
    await broker.start_consuming(QUEUE_NAME, callback=process_payment_event)
    logger.info(f"Воркер успешно подписался на очередь [{QUEUE_NAME}] и готов к работе.")

    # 4. Замираем и работаем, пока не взведется флаг shutdown_event
    await shutdown_event.wait()

    # 5. Сюда мы попадаем, только если пришел сигнал на остановку
    logger.info("Останавливаем прием новых сообщений из RabbitMQ...")
    # Здесь закрываем брокер, чтобы RabbitMQ перестал слать нам новые задачи
    await broker.close()

    logger.info("Закрываем соединения с базами данных...")
    await db_service.close()
    await cache_service.close()

    logger.info("🏁 Воркер успешно и безопасно завершил работу.")

if __name__ == "__main__":
    asyncio.run(main())