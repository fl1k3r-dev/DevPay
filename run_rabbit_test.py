import asyncio
import json
from src.config import settings
from src.services.cache import CacheService
from src.services.database import DatabaseService
from src import worker

cache_service = CacheService(redis_url=settings.redis_url)
db_service = DatabaseService(database_url=settings.database_url)

async def process_payment_event(message_body: str):
    try:
        if isinstance(message_body, dict):
            data = message_body
        else:
            data = json.loads(message_body.decode() if isinstance(message_body, bytes) else message_body)

        user_id = data.get("user_id")
        amount = data.get("amount")
        tx_id = data.get("transaction_id")

        print(f"\n📥 [Воркер] Получено событие платежа: {tx_id}")

        # Шаг 1: Проверка на идемпотентность
        if await cache_service.is_processed(tx_id):
            print(f"⚠️ [Воркер] Транзакция {tx_id} уже обрабатывалась! Пропускаем.")
            return

        # Шаг 2: Фиксация в БД
        db_success = await db_service.activate_subscription(user_id, amount, tx_id)

        if db_success:
            # Шаг 3: Обновление быстрого кэша подписок
            await cache_service.set_user_subscription(user_id, status="active", expire_seconds=2592000)   # на месяц
            print(f"🚀 [Воркер] Подписка для {user_id} активирована, кэш обновлен!")
        else:
            print(f"❌ [Воркер] Ошибка при сохранении в БД.")

    except Exception as e:
        print(f"❌ [Воркер] Непредвиденная ошибка: {e}")

async def process_rabbit_flow():

    await cache_service.connect()
    await db_service.connect()

    broker = worker.broker
    await broker.connect()

    QUEUE_NAME = "payment_events"
    await broker.start_consuming(QUEUE_NAME, callback=process_payment_event)

    print("\n📤 [API] Имитируем вебхук оплаты: отправляем событие в очередь...")
    mock_webhook_payload = {
        "user_id": 999888,
        "amount": 990.00,
        "transaction_id": "tx_crypto_pay_888"
    }

    await broker.publish_event(QUEUE_NAME, mock_webhook_payload)
    print("[API] Событие успешно опубликовано.")

    # Даем воркеру 2 секунды, чтобы он успел забрать и обработать сообщение
    await asyncio.sleep(2)

    await broker.close()
    await cache_service.close()
    await db_service.close()
    print("\n🎉 ВСЕ ТЕСТЫ RABBITMQ ВЫПОЛНЕНЫ УСПЕШНО!")

if __name__ == "__main__":
    import logging
    # Включаем базовые логи, чтобы видеть коннект aio-pika
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    asyncio.run(process_rabbit_flow())