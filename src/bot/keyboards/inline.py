import uuid
from aiogram.filters.callback_data import CallbackData
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardMarkup

from src.models import SubscriptionPlan

class BuyPlanCallback(CallbackData, prefix="buy_plan"):
    plan_id: uuid.UUID


def get_plans_keyboard(plans: list[SubscriptionPlan]) -> InlineKeyboardMarkup:
    """Генерирует клавиатуру на основе реальных тарифов из базы данных."""
    builder = InlineKeyboardBuilder()

    for plan in plans:
        # Текст на кнопке теперь полностью зависит от данных из БД
        button_text = f"💳 {plan.name} — {int(plan.price)} руб."

        # Передаем объект фабрики в callback_data и упаковываем его через .pack()
        builder.button(
            text=button_text,
            callback_data=BuyPlanCallback(plan_id=plan.id).pack()
        )

    # Размещаем кнопки друг под другом (в один столбец)
    builder.adjust(1)
    return builder.as_markup()