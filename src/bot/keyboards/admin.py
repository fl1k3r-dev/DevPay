from aiogram.utils.keyboard import InlineKeyboardBuilder
from src.models import SubscriptionPlan, PlanStatus
from src.bot.callbacks.admin import PlanAdminCallback

def get_plan_management_keyboard(plan: SubscriptionPlan):
    builder = InlineKeyboardBuilder()

    # Кнопки управления в зависимости от текущего статуса
    if plan.status == PlanStatus.ACTIVE:
        builder.button(
            text="📦 В архив (ARCHIVED)",
            callback_data=PlanAdminCallback(action="archive", plan_id=plan.id)
        )
        builder.button(
            text="🚨 Вывести из эксплуатации (DEPRECATED)",
            callback_data=PlanAdminCallback(action="deprecate", plan_id=plan.id)
        )

    elif plan.status == PlanStatus.ARCHIVED:
        builder.button(
            text="✅ Вернуть в ACTIVE",
            callback_data=PlanAdminCallback(action="activate", plan_id=plan.id)
        )
        builder.button(
            text="🚨 Вывести из эксплуатации (DEPRECATED)",
            callback_data=PlanAdminCallback(action="deprecate", plan_id=plan.id)
        )

    elif plan.status == PlanStatus.DEPRECATED:
        # Из DEPRECATED обычно не возвращают, но для админки можно сделать кнопку активации на случай ошибки
        builder.button(
            text="♻️ Реанимировать в ACTIVE",
            callback_data=PlanAdminCallback(action="activate", plan_id=plan.id)
        )

    # Кнопка возврата к списку всех тарифов
    builder.button(text="« Назад к тарифам", callback_data="admin_list_plans")

    # Выравниваем кнопки по одной в ряд
    builder.adjust(1)
    return builder.as_markup()