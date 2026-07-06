import uuid
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from src.models import PlanStatus, SubscriptionPlan

async def change_plan_status(session: AsyncSession, plan_id: uuid.UUID, new_status: PlanStatus):
    """Обновляет статус тарифного плана в базе данных."""
    query = (
        update(SubscriptionPlan)
        .where(SubscriptionPlan.id == plan_id)
        .values(status=new_status)
    )
    await session.execute(query)
    await session.commit()