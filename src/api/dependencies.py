from fastapi import Depends

from src.config import settings
from src.services.broker import BrokerService
from src.services.database import DatabaseService

_db_service = DatabaseService(settings.database_url)
_broker = BrokerService(settings.rabbitmq_url)

async def get_db_service() -> DatabaseService:
    return _db_service

async def get_broker_service() -> BrokerService:
    return _broker


from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession
from src.services.subscription import SubscriptionService

# Зависимость, которая открывает транзакционную сессию на один HTTP-запрос
async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    async with _db_service.session_maker() as session:
        yield session

# Зависимость, которая создает сервис подписок, передавая ему сессию
async def get_subscription_service(session: AsyncSession = Depends(get_db_session)) -> SubscriptionService:
    return SubscriptionService(session)
