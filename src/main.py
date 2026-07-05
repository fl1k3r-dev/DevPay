from contextlib import asynccontextmanager
from fastapi import FastAPI
from src.api.v1 import v1_router
from src.api.dependencies import get_broker_service
from src.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    broker = await get_broker_service()
    await broker.connect()
    yield
    await broker.close()

app = FastAPI(title="DevPay API", version=settings.API_VERSION, lifespan=lifespan)
app.include_router(v1_router)