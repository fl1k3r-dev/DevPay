from datetime import datetime, timedelta
import logging
from typing import Optional
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import select
from src.models import Payment, Subscription, SubscriptionStatus

logger = logging.getLogger(__name__)

class DatabaseService:

    def __init__(self, database_url: str):
        # Инициализируем движок и фабрику внутри сервиса
        self.engine = create_async_engine(database_url, echo=True, future=True)
        self.session_maker = async_sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False
        )

    async def payment_exists(self, operation_id: str) -> bool:
        """Проверяет в PostgreSQL, обрабатывался ли этот платёж ранее."""
        async with self.session_maker() as session:
            query = select(Payment).where(Payment.operation_id == operation_id)
            result = await session.execute(query)
            return result.scalar_one_or_none() is not None

    async def connect(self):
        """Проверяет, живое ли соединение с Postgres."""
        try:
            async with self.engine.connect() as conn:
                await conn.exec_driver_sql("SELECT 1")
            logger.info("Подключение к PostgreSQL успешно проверено.")
        except Exception as e:
            logger.error(f"Не удалось подключиться к PostgreSQL: {e}")
            raise e

    async def activate_subscription(self, user_id: int, amount: float, operation_id: str) -> Optional[Subscription]:
        """Бизнес-логика обработки платежа через контекст сессии.
        Возвращает объект подписки при успехе, иначе None.
        """
        logger.info(f"[DB] Начинаем транзакцию для tx: {operation_id}")

        try:
            async with self.session_maker() as session:
                async with session.begin():
                    # 1. Ищем подписку пользователя, которая ожидает оплаты или в триале
                    # Сортируем по дате создания (берём самую свежую), если вдруг их несколько
                    query = (
                        select(Subscription)
                        .where(
                            Subscription.user_id == user_id,
                            Subscription.status.in_([SubscriptionStatus.PAYMENT_PENDING, SubscriptionStatus.TRIAL])
                        )
                        .order_by(Subscription.created_at.desc())
                        .limit(1)
                    )
                    result = await session.execute(query)
                    subscription = result.scalar_one_or_none()

                    if not subscription:
                        logger.error(f"❌ [DB] Подписка для пользователя {user_id} в статусе PAYMENT_PENDING или TRIAL не найдена!")
                        return None

                    # 2. Проверяем, что сумма платежа соответствует цене подписки (с небольшим допуском из-за float)
                    if abs(amount - subscription.price_at_creation) > 0.01:
                        logger.error(f"❌ [DB] Сумма платежа {amount} не совпадает с ценой подписки {subscription.price_at_creation} для пользователя {user_id}")
                        return None

                    # 3. Обновляем жизненный цикл подписки
                    now = datetime.now()
                    # Берем дни из снапшота плана, сохраненного при создании подписки
                    days_to_add = subscription.period_days_at_creation or 30

                    subscription.status = SubscriptionStatus.ACTIVE
                    subscription.current_period_start = now
                    subscription.current_period_end = now + timedelta(days=days_to_add)
                    subscription.next_payment_at = subscription.current_period_end
                    subscription.updated_at = now

                    # 4. Фиксируем успешный платеж для истории и контроля идемпотентности
                    new_payment = Payment(
                        operation_id=operation_id,
                        user_id=user_id,
                        amount=amount,
                        created_at=now,
                    )
                    session.add(new_payment)

            logger.info(f"✅ [DB] Подписка для {user_id} успешно переведена в ACTIVE, платеж {operation_id} сохранен.")
            return subscription

        except Exception as e:
            logger.exception(f"❌ [DB] Критическая ошибка внутри транзакции активации подписки: {e}")
            return None

    async def close(self) -> None:
        if self.engine:
            await self.engine.dispose()
            logger.info("Пул соединений PostgreSQL закрыт.")