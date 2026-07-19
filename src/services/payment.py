import logging
import uuid
from typing import Optional

import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timedelta, timezone

from src.services.yookassa import YookassaClient
from src.services.encryption import crypto_service
from src.models import Subscription, SubscriptionPlan, SubscriptionStatus, Payment

logger = logging.getLogger(__name__)

class PaymentService:
    def __init__(self, db_session: AsyncSession):
        self.db_session = db_session
        self.yookassa_client = YookassaClient()

    async def initiate_subscription_payment(
            self,
            user_id: int,
            plan_id: uuid.UUID,
            merchant_id: uuid.UUID
    ) -> Optional[str]:
        """
        Инициализирует покупку подписки: создает запись в БД со статусом PAYMENT_PENDING,
        генерирует платеж в YooKassa и возвращает ссылку на оплату.
        """
        # 1. Получаем данные тарифного плана из БД
        result = await self.db_session.execute(select(SubscriptionPlan).where(SubscriptionPlan.id == plan_id))
        plan: Optional[SubscriptionPlan] = result.scalar_one_or_none()

        if not plan:
            logger.error(f"Тарифный план {plan_id} не найден в базе данных")
            return None

        # 2. Создаем подписку со статусом PAYMENT_PENDING
        # Так как encrypted_payment_method_id не nullable, временно пишем "PENDING"
        subscription_id = uuid.uuid4()
        new_subscription = Subscription(
            id=subscription_id,
            user_id=user_id,
            merchant_id=merchant_id,
            plan_id=plan_id,
            status=SubscriptionStatus.PAYMENT_PENDING,
            encrypted_payment_method_id="PENDING",
            price_at_creation=plan.price,
            period_days_at_creation=plan.period_days
        )

        try:
            self.db_session.add(new_subscription)
            await self.db_session.commit()

        except Exception as e:
            logger.error(f"Ошибка сохранения ожидающей подписки в БД: {e}")
            await self.db_session.rollback()
            return None

        # 3. Формируем запрос к ЮKassa
        # В качестве ключа идемпотентности используем строковый ID нашей подписки
        idempotency_key = str(subscription_id)
        description = f"Оплата подписки '{plan.name}' для пользователя {user_id}"

        # В metadata кладем ID подписки, чтобы вебхук знал, кого активировать
        metadata = {
            "subscription_id": idempotency_key,
            "user_id": str(user_id)  # Передаем строкой, YooKassa любит строки
        }

        yookassa_response = await self.yookassa_client.create_payment(
            amount=float(plan.price),
            description=description,
            idempotency_key=idempotency_key,
            metadata=metadata
        )

        if not yookassa_response:
            logger.error(f"ЮKassa не смогла создать платеж для подписки {subscription_id}. Удаляем сессию.")
            # Если платежка ответила отказом, удаляем временную подписку, чтобы не забивать БД
            await self.db_session.delete(new_subscription)
            await self.db_session.commit()
            return None

        # 4. Забираем ссылку для редиректа пользователя
        confirmation_url = yookassa_response.get("confirmation", {}).get("confirmation_url")

        logger.info(f"Подписка {subscription_id} создана. Ссылка на оплату получена.")
        return confirmation_url


    async def process_succeeded_payment(
            self,
            subscription_id: str,
            gateway_payment_id: str
    ) -> Optional[Subscription]:
        """
        Обрабатывает успешный платеж: проверяет статус в YooKassa,
        переводит подписку в ACTIVE и логирует платеж в таблицу payments.
        """
        # 1. СЕТЕВОЙ БЛОК: Делаем один чистый вызов через наш клиент до транзакции
        payment_info = await self.yookassa_client.get_payment_details(gateway_payment_id)

        if not payment_info:
            logger.error(f"❌ Не удалось обработать платеж {gateway_payment_id}, так как данные от ЮKassa не получены.")
            return None

        # Проверяем статус
        actual_status = payment_info.get("status")
        if actual_status != "succeeded":
            logger.warning(f"⚠️ Платеж {gateway_payment_id} имеет статус {actual_status}, а не succeeded. Отмена.")
            return None

        # Вытаскиваем токен карты
        payment_method = payment_info.get("payment_method", {})
        payment_method_id = payment_method.get("id")

        if not payment_method_id or payment_method_id == "NO_TOKEN":
            logger.error(f"❌ Не удалось получить payment_method.id от YooKassa для платежа {gateway_payment_id}")
            return None

        # 2. БЛОК БАЗЫ ДАННЫХ: Открываем транзакцию только тогда, когда все данные на руках
        try:
            subscription_uuid = uuid.UUID(subscription_id)
            query = (
                select(Subscription)
                .where(Subscription.id == subscription_uuid)
                .with_for_update()
            )
            result = await self.db_session.execute(query)
            subscription: Optional[Subscription] = result.scalar_one_or_none()

            if not subscription:
                logger.error(f"❌ Подписка {subscription_id} не найдена в БД при обработке вебхука")
                return None

            # Идемпотентность: если подписка уже активна, просто возвращаем её (дублирующий вебхук)
            if subscription.status == SubscriptionStatus.ACTIVE:
                logger.info(f"ℹ️ Подписка {subscription_id} уже имеет статус ACTIVE. Пропускаем.")
                return subscription

            # 3. Шифруем токен карты
            logger.info(f"Шифруем токен карты для подписки {subscription_id}")
            encrypted_token = crypto_service.encrypt_card_token(payment_method_id)
            subscription.encrypted_payment_method_id = encrypted_token

            # 4. Обновляем жизненный цикл подписки
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            subscription.status = SubscriptionStatus.ACTIVE
            subscription.current_period_start = now
            subscription.current_period_end = now + timedelta(days=subscription.period_days_at_creation)
            subscription.next_payment_at = subscription.current_period_end

            # 5. Создаем запись в таблице payments
            new_payment = Payment(
                id=uuid.uuid4(),
                operation_id=gateway_payment_id,
                user_id=subscription.user_id,
                amount=subscription.price_at_creation
            )
            self.db_session.add(new_payment)

            await self.db_session.commit()
            logger.info(f"✅ Подписка {subscription_id} успешно активирована и зашифрована.")
            return subscription

        except Exception as e:
            logger.exception(f"💥 Ошибка при обработке успешного платежа для подписки {subscription_id}: {e}")
            await self.db_session.rollback()
            return None