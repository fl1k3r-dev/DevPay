import logging
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from src.models import Subscription, SubscriptionStatus, SubscriptionPlan, PlanStatus
from src.services.encryption import crypto_service
from src.exceptions import PlanNotFoundError, SubscriptionNotFoundError, InvalidStatusTransitionError
from src.services.yookassa import YookassaClient


logger = logging.getLogger(__name__)

# Константы для дефолтных тарифов (теперь жестко привязываем правильные ID к ценам из интерфейса бота)
DEFAULT_PLANS = [
    {
        "id": uuid.UUID("11111111-1111-1111-1111-111111111111"),
        "name": "Тестовый Лайт",
        "description": "Доступ к базовым фичам бэкенда",
        "price": Decimal("299.00"),
        "period_days": 30
    },
    {
        "id": uuid.UUID("22222222-2222-2222-2222-222222222222"),
        "name": "Тестовый Про",
        "description": "Полный доступ ко всем фичам бэкенда",
        "price": Decimal("1999.00"),
        "period_days": 30
    }
]


class SubscriptionService:
    def __init__(self, db_session: AsyncSession, broker_service):
        self.session = db_session
        self.broker = broker_service
        self.yookassa_client = YookassaClient()

    async def seed_default_plans(self) -> None:
        """Автоматическая инициализация дефолтных тарифов при старте приложения."""
        for plan_data in DEFAULT_PLANS:
            query = select(SubscriptionPlan).where(SubscriptionPlan.id == plan_data["id"])
            result = await self.session.execute(query)
            existing_plan = result.scalar_one_or_none()

            if not existing_plan:
                new_plan = SubscriptionPlan(**plan_data)
                self.session.add(new_plan)

            else:
                if existing_plan.price != plan_data["price"]:
                    existing_plan.price = plan_data["price"]
                    existing_plan.name = plan_data["name"]

        # Фиксируем изменения в базе
        await self.session.commit()

    async def create_plan(
            self,
            name: str,
            description: str,
            price: Decimal,
            period_days: int = 30
    ) -> SubscriptionPlan:
        """Метод для админки: создание кастомного тарифного плана."""
        new_plan = SubscriptionPlan(
            id=uuid.uuid4(),
            name=name,
            description=description,
            price=price,
            period_days=period_days
        )
        self.session.add(new_plan)
        await self.session.flush()   # Чтобы вернуть объект с уже сгенерированным UUID
        return new_plan

    async def create_subscription(
        self, user_id: int, plan_id: uuid.UUID, merchant_id: uuid.UUID, payment_method_id: str
    ) -> Subscription:
        """Инициализация новой подписки в статусе PAYMENT_PENDING"""
        # 1. Ищем тарифный план в базе (SQLAlchemy 2.0 стиль)
        query = select(SubscriptionPlan).where(SubscriptionPlan.id == plan_id)
        result = await self.session.execute(query)
        plan = result.scalar_one_or_none()

        if not plan:
            raise PlanNotFoundError(plan_id)

        # 2. Шифруем токен карты перед записью в БД
        encrypted_card = crypto_service.encrypt_card_token(payment_method_id)

        # 3. Создаем объект подписки со снапшотом цены
        subscription = Subscription(
            user_id=user_id,
            merchant_id=merchant_id,
            plan_id=plan_id,
            status=SubscriptionStatus.PAYMENT_PENDING,
            encrypted_payment_method_id=encrypted_card,
            price_at_creation=plan.price,
            period_days_at_creation=plan.period_days
        )

        self.session.add(subscription)
        await self.session.flush()      # Генерируем ID подписки без коммита транзакции
        return subscription

    async def activate_subscription(self, subscription_id: uuid.UUID) -> Subscription:
        """Перевод подписки в ACTIVE после успешной оплаты воркером"""
        query = select(Subscription).where(Subscription.id == subscription_id)
        result = await self.session.execute(query)
        subscription = result.scalar_one_or_none()

        if not subscription:
            raise SubscriptionNotFoundError(subscription_id)

        # Защита стейт-машины: активировать можно только то, что ждет оплаты или уже триал
        if subscription.status not in (SubscriptionStatus.PAYMENT_PENDING, SubscriptionStatus.TRIAL):
            raise InvalidStatusTransitionError(subscription.status, SubscriptionStatus.ACTIVE)

        now = datetime.now(timezone.utc).replace(tzinfo=None)

        subscription.status = SubscriptionStatus.ACTIVE
        subscription.current_period_start = now
        subscription.current_period_end = now + timedelta(days=subscription.period_days_at_creation)
        subscription.next_payment_at = subscription.current_period_end

        await self.session.flush()
        return subscription

    async def cancel_subscription(self, subscription_id: uuid.UUID) -> Subscription:
        """Мягкая отмена подписки — доступ остается до конца оплаченного периода"""
        query = select(Subscription).where(Subscription.id == subscription_id)
        result = await self.session.execute(query)
        subscription = result.scalar_one_or_none()

        if not subscription:
            raise SubscriptionNotFoundError(subscription_id)

        if subscription.status != SubscriptionStatus.ACTIVE:
            raise InvalidStatusTransitionError(subscription.status, SubscriptionStatus.CANCELED)

        subscription.status = SubscriptionStatus.CANCELED
        # Важно: current_period_end и next_payment_at НЕ обнуляем
        # Воркер чека заберет её на отключение только когда наступит next_payment_at.

        await self.session.flush()
        return subscription

    async def process_subscription_renewal(self, subscription) -> None:
        """
        Обрабатывает автопродление конкретной подписки
        с учетом актуального статуса тарифного плана.
        """
        plan = subscription.plan

        # Сценарий 1: Тариф полностью выведен из эксплуатации
        if plan.status == PlanStatus.DEPRECATED:
            logger.info(f"Подписка {subscription.id} отменена. Тариф '{plan.name}' DEPRECATED.")

            subscription.status = SubscriptionStatus.CANCELED
            subscription.auto_renew = False

            notification_payload = {
                "user_id": str(subscription.user_id),
                "event": "subscription_deprecated",
                "plan_name": plan.name
            }
            await self.broker.publish_event("notifications", notification_payload)
            await self.session.commit()
            return

        # Сценарий 2: Тариф активен или находится в архиве — пытаемся списать средства
        if plan.status in (PlanStatus.ARCHIVED, PlanStatus.ACTIVE):
            logger.info(f"Попытка продления подписки {subscription.id} по тарифу '{plan.name}' ({plan.status.value})")

            try:
                # 1. Расшифровываем токен карты юзера
                payment_method_id = crypto_service.decrypt_card_token(subscription.encrypted_payment_method_id)

                # 2. Генерируем уникальный ключ идемпотентности для этой попытки продления
                now_timestamp = int(datetime.now(timezone.utc).replace(tzinfo=None).timestamp())
                idempotency_key = f"sub_renew_{subscription.id}_{now_timestamp}"

                # 3. Делаем запрос через ЭКЗЕМПЛЯРА класса yookassa_client
                payment_success = await self.yookassa_client.create_recurrent_payment(
                    amount=subscription.price_at_creation,
                    description=f"Продление подписки: {plan.name}",
                    payment_method_id=payment_method_id,
                    idempotency_key=idempotency_key
                )

                if payment_success:
                    subscription.status = SubscriptionStatus.ACTIVE
                    # 4. Сдвигаем даты вперед!
                    subscription.extend_period(days=subscription.period_days_at_creation)
                    logger.info(f"Подписка {subscription.id} успешно продлена.")
                else:
                    subscription.status = SubscriptionStatus.PAST_DUE

            except Exception as e:
                logger.error(f"Критическая ошибка при ребилле через YooKassa: {e}")
                subscription.status = SubscriptionStatus.PAST_DUE

            # Используем сессию инстанса класса
            await self.session.commit()