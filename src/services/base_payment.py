from abc import ABC, abstractmethod
from decimal import Decimal
from pydantic import BaseModel
from typing import Optional
from enum import Enum

class ProviderPaymentStatus(str, Enum):
    SUCCESS = "success"
    PENDING = "pending"
    FAILED = "failed"

class PaymentResult(BaseModel):
    provider_payment_id: str
    status: ProviderPaymentStatus
    raw_response: dict
    error_message: Optional[str] = None

class PaymentProvider(ABC):
    """
    Абстрактный базовый класс (Интерфейс), задающий контракт
    для всех будущих платежных шлюзов (YooKassa, Stripe, Crypto).
    """

    @abstractmethod
    async def charge(
        self,
        amount: Decimal,
        idempotency_key: str,
        payment_method_id: str,
    ) -> PaymentResult:
        """
        Инициировать списание средств с сохраненного метода оплаты.
        Каждый подкласс ОБЯЗАН реализовать этот метод.
        """
        pass

    @abstractmethod
    async def get_payment_status(self, provider_payment_id: str) -> PaymentResult:
        """
        Проверить актуальный статус платежа на стороне банка/шлюза.
        Используется в recovery path, если воркер упал во время charge.
        """
        pass

    @abstractmethod
    async def refund(self, provider_payment_id: str, amount: Decimal) -> bool:
        """
        Оформить возврат средств (чисто на будущее).
        """
        pass