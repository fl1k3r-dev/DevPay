import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from enum import Enum as PyEnum
from sqlalchemy import String, Integer, Numeric, ForeignKey, Text, Enum as SQLEnum, Boolean, TIMESTAMP
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# Базовый класс для всех моделей
class Base(DeclarativeBase):
    pass

# Статусы подписки (Enum)
class SubscriptionStatus(str, PyEnum):
    TRIAL = "trial"
    ACTIVE = "active"
    PAYMENT_PENDING = "payment_pending"   # Ждем фиксации оплаты от воркера
    CANCELED = "canceled"                 # Отменена, но доживает оплаченный срок
    EXPIRED = "expired"                   # Полностью отключена, срок истек
    PAST_DUE = "past_due"                 # Если на карте не хватило денег или она заблокирована

# Статусы тарифного плана (Enum)
class PlanStatus(str, PyEnum):
    ACTIVE = "active"  # Тариф доступен всем, автопродление работает
    ARCHIVED = "archived"  # Вариант А: Скрыт для новых, старые продлеваются
    DEPRECATED = "deprecated"  # Вариант Б: Скрыт для всех, догорает и закрывается


# Модель тарифного плана
class SubscriptionPlan(Base):
    __tablename__ = "subscription_plans"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)

    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    period_days: Mapped[int] = mapped_column(Integer, default=30)

    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))

    # Статус из нашего Enum с автоматической конвертацией типов
    status: Mapped[PlanStatus] = mapped_column(
        SQLEnum(
            PlanStatus,
            native_enum=False,
            values_callable=lambda x: [e.value for e in x],
        ),
        default=PlanStatus.ACTIVE,
        index=True
    )

    # Связь с подписками
    subscriptions = relationship("Subscription", back_populates="plan")


# Модель самой подписки пользователя
class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    merchant_id: Mapped[uuid.UUID] = mapped_column(nullable=True)

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
    encrypted_payment_method_id: Mapped[str | None] = mapped_column(String(500), nullable=True, default=None)

    # Снапшоты на случай, если админ изменит цену самого плана, а у юзера старый тариф
    price_at_creation: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    period_days_at_creation: Mapped[int] = mapped_column(Integer, nullable=False)

    # Таймстампы жизненного цикла
    current_period_start: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    current_period_end: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    next_payment_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), default=lambda: datetime.now(timezone.utc).replace(tzinfo=None), onupdate=datetime.now)
    auto_renew: Mapped[bool] = mapped_column(Boolean, nullable=True)

    # Обратная связь с планом
    plan = relationship("SubscriptionPlan", back_populates="subscriptions")

    def extend_period(self, days):
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        self.current_period_start = now
        self.current_period_end = now + timedelta(days=days)
        self.next_payment_at = self.current_period_end

# Модель платежа
class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)

    # Уникальный ID операции от YooMoney для контроля идемпотентности
    operation_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)

    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))