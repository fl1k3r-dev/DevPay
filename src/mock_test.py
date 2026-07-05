import pytest
from unittest.mock import AsyncMock, MagicMock
from decimal import Decimal
from src.services.base_payment import PaymentResult, PaymentProvider, ProviderPaymentStatus

# Наша бизнес-логика, которую мы хотим протестировать
async def process_billing(provider:PaymentProvider, amount: Decimal) -> str:
    result = await provider.charge(
        amount=amount,
        idempotency_key="test-uuid",
        payment_method_id="card_tok_123"
    )

    if result.status == ProviderPaymentStatus.SUCCESS:
        return f"Платеж {result.provider_payment_id} успешно обработан"
    else:
        return "Оплата не прошла"


#------ Тест ------

@pytest.mark.asyncio
async def test_process_billing_success_path():
    # 1. Создаем мок-объект вместо реальной ЮKassa.
    # Спецификация spec=PaymentProvider гарантирует, что если мы опечатаемся
    # в названии метода (например, напишем chagre вместо charge), тест сразу упадет.
    mock_provider = AsyncMock(spec=PaymentProvider)

    # 2. Настраиваем Stub-поведение: что должен вернуть метод charge при вызове
    mock_provider.charge.return_value = PaymentResult(
        provider_payment_id="pay_real_internal_999",
        status=ProviderPaymentStatus.SUCCESS,
        raw_response={"status": "succeeded"}
    )

    # 3. Вызываем нашу реальную бизнес-логику, подсовывая ей мок
    test_amount = Decimal("499.00")
    execution_result = await process_billing(mock_provider, test_amount)

    # 4. Проверяем РЕЗУЛЬТАТ работы нашей функции
    assert execution_result == "Платёж pay_real_internal_999 успешно обработан"

    # 5. Самая магия МOКА: Проверяем ПОВЕДЕНИЕ.
    # Действительно ли наша функция вызывала метод charge с правильными аргументами?
    mock_provider.charge.assert_called_once_with(
        amount=test_amount,
        idempotency_key="test-uuid",
        payment_method="card_tok_123"
    )

