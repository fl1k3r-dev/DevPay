from fastapi import APIRouter
from src.api.v1.payments import router as payments_router
from src.api.v1.subscriptions import router as subscriptions_router

v1_router = APIRouter(prefix="/api/v1")
v1_router.include_router(payments_router)
v1_router.include_router(subscriptions_router)