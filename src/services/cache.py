import logging
import redis.asyncio as aioredis
from typing import Optional, Any


logger = logging.getLogger(__name__)

class CacheService:
    def __init__(self, redis_url: str):
        """
        Инициализация сервиса кэширования.
        По умолчанию смотрим на локальный Redis, базу 0.
        """
        self.redis_url = redis_url
        self.client: Optional[aioredis.Redis] = None


    async def connect(self) -> None:
        if not self.client:
            # aioredis.from_url под капотом сам создает и управляет пулом соединений
            self.client = aioredis.from_url(self.redis_url, decode_responses=True)
            logger.info("💾 Подключение к Redis (Connection Pool) успешно установлено.")

    async def is_processed(self, tx_id: str) -> bool:
        """Проверка транзакции на дубликат (идемпотентность) на 24 часа."""
        is_new = await self.client.set(f"tx:{tx_id}", "processed", ex=86400, nx=True)
        return not is_new

    async def set_user_subscription(self, user_id: int, status: str, expire_seconds: int = 3600) -> None:
        """Быстрое сохранение статуса подписки для бота"""
        await self.client.set(f"user:{user_id}:sub", status, ex=expire_seconds)

    async def set(self, key: str, value: Any, expire_seconds: Optional[int] = None) -> bool:
        """Сохранить значение в кэш с опциональным временем жизни (TTL)."""
        try:
            return bool(await self.client.set(key, value, ex=expire_seconds))
        except Exception as e:
            logger.error(f"Ошибка записи в Redis ({key}): {e}")
            return False

    async def get(self, key: str) -> Optional[str]:
        """Получить значение из кэша по ключу."""
        try:
            return await self.client.get(key)
        except Exception as e:
            logger.error(f"Ошибка чтения из Redis ({key}): {e}")
            return None

    async def close(self) -> None:
        """Корректное закрытие пула соединений при остановке приложения."""
        if self.client:
            await self.client.close()
            logger.info("💾 Соединение с Redis успешно закрыто.")