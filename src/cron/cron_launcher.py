import asyncio
from datetime import datetime
from sqlalchemy import update

from src.services.database import DatabaseService
from src.services.cache import CacheService
from src.models import Subscription, SubscriptionStatus

async def check_and_expire_subscriptions(db_service: DatabaseService, cache_service: CacheService):
    print(f"🕒 [{datetime.now()}] Запуск проверки истекших подписок...")

    async with db_service.session_maker() as session:
        async with session.begin():
            stmt = (
                update(Subscription)
                .where(
                    Subscription.status.in_([SubscriptionStatus.ACTIVE, SubscriptionStatus.CANCELED]),
                    Subscription.current_period_end <= datetime.now()
                )
                .values(status=SubscriptionStatus.EXPIRED)
                .returning(Subscription.user_id)
            )

            result = await session.execute(stmt)
            expired_users = result.scalars().all()

            if expired_users:
                print(f"💀 Отключено подписок: {len(expired_users)} для пользователей: {expired_users}")
                for user_id in expired_users:
                    await cache_service.client.delete(f"user:{user_id}:sub")   # Стираем активный статус
            else:
                print("👍 Просроченных подписок не обнаружено.")