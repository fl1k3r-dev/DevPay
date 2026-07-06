import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from src.api.v1 import v1_router
from src.api.dependencies import get_broker_service, get_db_service
from src.config import settings
from src.services.subscription import SubscriptionService

logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    broker = await get_broker_service()
    await broker.connect()

    db_service = await get_db_service()
    # При старте приложения открываем сессию и сидим базу
    async with db_service.session_maker() as session:
        sub_service = SubscriptionService(session)
        await sub_service.seed_default_plans()
        logger.info("✅ Проверка и сидинг тарифных планов успешно завершены!")

    yield

    await broker.close()

app = FastAPI(title="DevPay API", version=settings.API_VERSION, lifespan=lifespan)
app.include_router(v1_router)