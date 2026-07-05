import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from src.exceptions import SubscriptionNotFoundError, InvalidStatusTransitionError
from src.api.dependencies import get_subscription_service
from src.services.subscription import SubscriptionService

router = APIRouter(prefix="/subscriptions", tags=["Subscriptions"])

@router.post("/{subscription_id}/cancel")
async def cancel_subscription(
        subscription_id: uuid.UUID,
        sub_service: SubscriptionService = Depends(get_subscription_service)
) -> dict:
    try:
        await sub_service.cancel_subscription(subscription_id)

        await sub_service.session.commit()

    except SubscriptionNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Активная подписка не найдена"
        )

    except InvalidStatusTransitionError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Нельзя отменить неактивную подписку"
        )

    return {"status": "ok", "message": "Подписка отменена, доступ активен до конца оплаченного периода"}