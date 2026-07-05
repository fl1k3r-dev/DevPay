import asyncio
import uuid
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, result
from sqlalchemy import select

from src.services.subscription import SubscriptionService
from src.models import Subscription, SubscriptionPlan, SubscriptionStatus
from src.config import settings

# URL нашей базы данных в Docker
DATABASE_URL = settings.database_url

async def test_online_sprint():
    print("Подключение к БД PostgreSQL в Docker...")
    engine = create_async_engine(DATABASE_URL, echo=False)
    async_session = async_sessionmaker(engine, expire_on_commit=False)

    async with async_session() as session:
        print("Подготовка тестовых данных...")

        # 1. Создаем и сохраняем реальный тарифный план в БД
        test_plan = SubscriptionPlan(
            id=uuid.uuid4(),
            name="Live Premium Plan",
            description="Тестовый премиум тариф для онлайн-интеграции",
            price=999.00,
            period_days=30
        )

        session.add(test_plan)
        await session.commit()     # Фиксируем план в БД, чтобы сработал Foreign Key
        print(f"[БД] Тарифный план '{test_plan.name}' успешно сохранен.")

        # 2. Инициализируем наш сервис с реальной сессией
        service = SubscriptionService(db_session=session)
        test_user_id = 999888

        print("\nШаг 1: Тестируем создание подписки в БД...")
        # Вызываем метод сервиса (внутри него отработает session.add)
        sub = await service.create_subscription(
            user_id=test_user_id,
            plan_id=test_plan.id,
            merchant_id=uuid.uuid4(),
            payment_method_id="real_card_token_123"
        )
        await session.commit()    # Коммитим создание подписки в базу

        print(f"[БД] Подписка записана! ID: {sub.id}")
        print(f"Статус в базе: {sub.status} (Ожидалось: PAYMENT_PENDING)")
        assert sub.status == SubscriptionStatus.PAYMENT_PENDING

        print("\nШаг 2: Тестируем активацию подписки (стейт-машина)...")
        # Активируем подписку через сервис
        activated_sub = await service.activate_subscription(sub.id)
        await session.commit()    # Коммитим обновление статуса в базу

        print(f"[БД] Статус обновлен на: {activated_sub.status} (Ожидалось: ACTIVE)")
        print(f"Дата окончания периода: {activated_sub.current_period_end}")
        assert activated_sub.status == SubscriptionStatus.ACTIVE

        print("\nШаг 3: Проверяем честность записи (делаем прямой SELECT)...")
        # Делаем независимый запрос в базу, чтобы убедиться, что всё реально сохранилось
        query = select(Subscription).where(Subscription.user_id == test_user_id)
        result = await session.execute(query)
        db_subscription = result.scalar_one_or_none()

        assert db_subscription is not None
        assert db_subscription.status == SubscriptionStatus.ACTIVE
        print("[БД] Прямой SELECT подтвердил: данные в базе изменены корректно!")

        # 4. Очистка данных (Cleanup), чтобы не забивать базу мусором при повторных тестах
        print("\nОчистка тестового окружения...")
        await session.delete(db_subscription)
        await session.delete(test_plan)
        await session.commit()
        print("[БД] Тестовые записи успешно удалены.")

    await engine.dispose()
    print("\nИНТЕГРАЦИОННЫЙ ТЕСТ С РЕАЛЬНОЙ БД ПРОЙДЕН УСПЕШНО!")

if __name__ == "__main__":
    asyncio.run(test_online_sprint())