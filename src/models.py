import uuid
from datetime import datetime
from enum import Enum as PyEnum
from sqlalchemy import String, Integer, Numeric, DateTime, ForeignKey, Text, Enum as SQLEnum
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# Базовый класс для всех моделей
class Base(DeclarativeBase):
    pass

# 1. Статусы подписки (Enum)
class SubscriptionStatus(str, PyEnum):
    TRIAL = "trial"
    ACTIVE = "active"
    PAYMENT_PENDING = "payment_pending"   # Ждем фиксации оплаты от воркера
    CANCELED = "canceled"                 # Отменена, но доживает оплаченный срок
    EXPIRED = "expired"                   # Полностью отключена, срок истек


# 2. Модель тарифного плана
class SubscriptionPlan(Base):
    __tablename__ = "subscription_plans"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4())
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)

    # Цена. Используем Numeric вместо Float, чтобы не поплыла точность при расчетах
    price: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    period_days: Mapped[int] = mapped_column(Integer, default=30)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    # Связь с подписками
    subscriptions = relationship("Subscription", back_populates="plan")


# 3. Модель самой подписки пользователя
class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    merchant_id: Mapped[uuid.UUID] = mapped_column(nullable=False)

    # Внешний ключ на план подписки
    plan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("subscription_plans.id"), nullable=False)

    # Статус из нашего Enum с автоматической конвертацией типов
    status: Mapped[SubscriptionStatus] = mapped_column(
        SQLEnum(
            SubscriptionStatus,
            native_enum=False,
            values_callable=lambda x: [e.value for e in x],
        ),
        default=SubscriptionStatus.PAYMENT_PENDING,
        index=True
    )

    # Токен карты/метода оплаты (зашифрованный Fernet-строкой)
    encrypted_payment_method_id: Mapped[str] = mapped_column(String(500), nullable=False)

    # Снапшоты на случай, если админ изменит цену самого плана, а у юзера старый тариф
    price_at_creation: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    period_days_at_creation: Mapped[int] = mapped_column(Integer, nullable=False)

    # Таймстампы жизненного цикла
    current_period_start: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    current_period_end: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    next_payment_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)

    # Обратная связь с планом
    plan = relationship("SubscriptionPlan", back_populates="subscriptions")

class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)

    # Уникальный ID операции от ЮMoney для контроля идемпотентности
    operation_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    amount: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)