import logging
import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from src.api.dependencies import get_broker_service, get_db_session
from src.services.broker import BrokerService
from src.services.payment import PaymentService


router = APIRouter(prefix="/payments", tags=["Payments"])
logger = logging.getLogger("DevPayAPI")

class SubscriptionOrderRequest(BaseModel):
    user_id: int
    plan_id: uuid.UUID
    merchant_id: uuid.UUID

@router.post("/create", status_code=status.HTTP_201_CREATED)
async def create_payment_link(
        payload: SubscriptionOrderRequest,
        db_session: AsyncSession = Depends(get_db_session),
):
    """
    Вызывается Telegram-ботом, когда пользователь выбирает тариф
    и нажимает кнопку 'Оплатить'. Возвращает URL для редиректа.
    """
    payment_service = PaymentService(db_session=db_session)

    url = await payment_service.initiate_subscription_payment(
        user_id=payload.user_id,
        plan_id=payload.plan_id,
        merchant_id=payload.merchant_id,
    )

    if not url:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Не удалось сгенерировать платежную ссылку. Попробуйте позже."
        )

    return {"payment_url": url}


@router.post("/yookassa/webhook")
async def yookassa_webhook(
        request: Request,
        db_session: AsyncSession = Depends(get_db_session),
        broker: BrokerService = Depends(get_broker_service)
):
    """Принимает JSON-уведомления от YooKassa и активирует подписки."""
    try:
        notification_data = await request.json()
    except Exception as e:
        logger.error("Не удалось распарсить JSON вебхука")
        raise HTTPException(status_code=400, detail="Invalid JSON")

    event_type = notification_data.get("event")
    payment_object = notification_data.get("object", {})
    gateway_payment_id = payment_object.get("id")
    amount_data = payment_object.get("amount") or {}
    amount = Decimal(amount_data.get("value", "0.0"))
    metadata = payment_object.get("metadata", {})
    subscription_id = metadata.get("subscription_id")
    user_id = metadata.get("user_id")

    logger.info(f"Получен вебхук YooKassa. Событие: {event_type}, ID платежа: {gateway_payment_id}")

    # Мы обрабатываем только статус успешной оплаты
    if event_type != "payment.succeeded":
        logger.info(f"Игнорируем событие {event_type} для платежа {gateway_payment_id}")
        return {"status": "ignored"}

    if not subscription_id or not gateway_payment_id:
        logger.error("В данных вебхука отсутствует subscription_id или payment_id")
        raise HTTPException(status_code=400, detail="Missing required metadata fields")

    # Отправляем событие в RabbitMQ, чтобы бот мгновенно прислал юзеру: "Ура, оплата прошла!"
    payload = {
        "user_id": user_id,
        "subscription_id": subscription_id,
        "amount": amount,
        "operation_id": gateway_payment_id,
        "status": "success"
    }

    await broker.publish_to_exchange(
        exchange_name="payment_events_exchange",
        payload=payload
    )
    logger.info(f"🚀 Событие активации подписки {subscription_id} отправлено в обменник.")

    return {"status": "ok"}