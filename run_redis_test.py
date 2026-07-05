import asyncio

from src.services.cache import CacheService
from src.config import settings

async def test_redis_connection():
    print("Подключение к Redis в Docker...")
    cache = CacheService(settings.redis_url)
    await cache.connect()

    # Тест 1: Базовая запись и чтение
    print("\nТест 1: Запись временного статуса подписки...")
    test_key = "user:999888:pending_payment"
    test_value = "sub_ac363295"

    success = await cache.set(test_key, test_value, expire_seconds=5)
    if success:
        print(f"Успешно записано! Ключ: {test_key} -> Значение: {test_value}")

    cached_val = await cache.get(test_key)
    print(f"Проверка чтения: из Redis получено -> '{cached_val}'")
    assert cached_val == test_value, "Данные не совпадают"

    # Тест 2: Проверка автоматического удаления по TTL
    print("\nТест 2: Проверяем работу TTL (ожидаем 6 секунд)...")
    await asyncio.sleep(6)

    expired_val = await cache.get(test_key)
    print(f"Проверка после паузы: получено -> {expired_val}")
    assert expired_val is None, "Ключ должен был удалиться по TTL, но он всё еще на месте"
    print("Запись успешно удалена сервером по истечении времени.")

    # Закрываем пул
    await cache.close()
    print("\nВСЕ ТЕСТЫ REDIS ВЫПОЛНЕНЫ УСПЕШНО!")

if __name__ == "__main__":
    asyncio.run(test_redis_connection())