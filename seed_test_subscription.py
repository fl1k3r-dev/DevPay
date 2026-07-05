import asyncio
from datetime import datetime
import uuid

# Импортируем сервис, модели и конфиг
from src.services.database import DatabaseService
from src.models import Subscription, SubscriptionPlan, SubscriptionStatus
from src.config import settings


async def seed():
    print("🌱 Инициализируем DatabaseService...")
    db_service = DatabaseService(settings.database_url)
    session_maker = db_service.session_maker

    print("🌱 Создаем тестовый тариф и подписку для пользователя 999999...")
    try:
        async with session_maker() as session:
            async with session.begin():
                # 1. Генерируем ID для плана заранее, чтобы связать таблицы
                plan_uuid = uuid.uuid4()

                # 2. Создаем тарифный план, чтобы не нарушать Foreign Key
                test_plan = SubscriptionPlan(
                    id=plan_uuid,
                    name="Тестовый план 999",
                    description="План для симуляции платежей ЮMoney",
                    price=999.00,
                    period_days=30,
                    created_at=datetime.now()
                )
                session.add(test_plan)

                # 3. Создаем подписку, привязанную к реальному плану
                new_sub = Subscription(
                    id=uuid.uuid4(),
                    user_id=999999,
                    merchant_id=uuid.uuid4(),
                    plan_id=plan_uuid,  # <-- Передаем реальный ID созданного плана
                    status=SubscriptionStatus.PAYMENT_PENDING,
                    encrypted_payment_method_id="mock_yoomoney_token_12345",
                    price_at_creation=999.00,
                    period_days_at_creation=30,
                    created_at=datetime.now(),
                    updated_at=datetime.now()
                )
                session.add(new_sub)

        print("✅ Тестовый план и подписка успешно добавлены в PostgreSQL!")

    except Exception as e:
        print(f"❌ Ошибка при сидировании базы: {e}")

    finally:
        # Закрываем пул соединений
        await db_service.close()


if __name__ == "__main__":
    asyncio.run(seed())