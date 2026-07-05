import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock
from src.services.subscription import SubscriptionService
from src.models import SubscriptionPlan, SubscriptionStatus


async def test_sprint():
    print("Запуск офлайн-теста стейт-машины...")

    # 1. Создаем фейковый тарифный план
    fake_plan = SubscriptionPlan(
        id=uuid.uuid4(),
        name="Premium Plan",
        price=499.00,
        period_days=30
    )

    # 2. Мокаем сессию базы данных
    mock_session = AsyncMock()

    # Явно говорим, что add — синхронный метод, чтобы убрать RuntimeWarning
    mock_session.add = MagicMock()

    # Настраиваем, чтобы на первый запрос (поиск плана) база возвращала наш фейковый план
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = fake_plan
    mock_session.execute.return_value = mock_result

    # 3. Инициализируем сервис с моканой сессией
    service = SubscriptionService(db_session=mock_session)

    # 4. Тестируем создание подписки (метод create_subscription)
    sub = await service.create_subscription(
        user_id=123456,
        plan_id=fake_plan.id,
        merchant_id=uuid.uuid4(),
        payment_method_id="3ds_card_token_xyz"
    )

    print(f"Подписка создана успешно!")
    print(f"Статус: {sub.status} (Ожидалось: payment_pending)")
    print(f"Снапшот цены: {sub.price_at_creation} руб.")
    assert sub.status == SubscriptionStatus.PAYMENT_PENDING

    # 5. Перенастраиваем мок сессии для следующего шага
    # Теперь при запросе подписки из БД сервис получит наш объект `sub`
    mock_result.scalar_one_or_none.return_value = sub

    # 6. Тестируем активацию (метод activate_subscription принимает только ID подписки)
    activated_sub = await service.activate_subscription(sub.id)
    print(f"Подписка успешно активирована!")
    print(f"Новый статус: {activated_sub.status} (Ожидалось: active)")
    print(f"Дата окончания: {activated_sub.current_period_end}")
    assert activated_sub.status == SubscriptionStatus.ACTIVE
    assert activated_sub.next_payment_at == activated_sub.current_period_end

    print("\nВСЕ ТЕСТЫ ПРОЙДЕНЫ УСПЕШНО В РЕЖИМЕ ОФЛАЙН!")


if __name__ == "__main__":
    asyncio.run(test_sprint())