import logging
from decimal import Decimal
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot.callbacks.admin import PlanAdminCallback
from src.bot.keyboards.admin import get_plan_management_keyboard
from src.models import SubscriptionPlan, PlanStatus
from src.services.admin_plan import change_plan_status
from src.services.subscription import SubscriptionService
from src.config import settings

admin_router = Router()
logger = logging.getLogger("DevPayBot")

# Защита на уровне роутера: обрабатывать сообщения ТОЛЬКО от админа
admin_router.message.filter(F.from_user.id == settings.ADMIN_ID)

@admin_router.message(Command("add_plan"))
async def admin_add_plan(message: Message, session: AsyncSession):
    """
    Команда для добавления тарифа админом.
    Формат: /add_plan Название | Описание | Цена | Длительность
    """
    try:
        # Убираем саму команду и режем строку по разделителю " | "
        command_args = message.text.split("/add_plan")[1]
        args = [arg.strip() for arg in command_args.split("|")]

        if len(args) != 4:
            raise ValueError("Неверное количество аргументов")

        name, description, price_str, period_str = args
        price = Decimal(price_str)
        period_days = int(period_str)

        service = SubscriptionService(session)
        new_plan = await service.create_plan(
            name=name,
            description=description,
            price=price,
            period_days=period_days
        )

        # Коммитим транзакцию, так как это операция записи
        await session.commit()

        logger.info(f"Админ {message.from_user.id} создал тариф {new_plan.id}")
        await message.answer(
            f"🚀 **Тариф успешно добавлен в базу!**\n\n"
            f"🆔 **ID:** `{new_plan.id}`\n"
            f"📦 **Название:** {name}\n"
            f"📝 **Описание:** {description}\n"
            f"💰 **Цена:** {price} руб.\n"
            f"📅 **Период:** {period_days} дней.\n\n"
            f"Теперь он автоматически появится в списке `/plans`!",
            parse_mode="Markdown"
        )

    except (IndexError, ValueError):
        await message.answer(
            "❌ **Ошибка в формате команды!**\n\n"
            "Используй строгий формат (с пробелами вокруг вертикальной черты):\n"
            "`/add_plan Название | Описание | Цена | Дни`\n\n"
            "*Пример:* `/add_plan VIP-Доступ | Максимальная подписка | 2999 | 30`",
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Ошибка при создании тарифа админом: {e}")
        await message.answer("💥 Произошла внутренняя ошибка при сохранении тарифа.")


@admin_router.callback_query(PlanAdminCallback.filter(F.action == "view"))
async def admin_view_plan(callback: CallbackQuery, callback_data: PlanAdminCallback, session: AsyncSession):
    """Просмотр карточки тарифа админом."""
    query = select(SubscriptionPlan).where(SubscriptionPlan.id == callback_data.plan_id)
    result = await session.execute(query)
    plan = result.scalar_one_or_none()

    if not plan:
        await callback.answer("Тариф не найден!", show_alert=True)
        return

    text = (
        f"📋 *Управление тарифом*\n\n"
        f"🆔 ID: `{plan.id}`\n"
        f"🏷 Название: *{plan.name}*\n"
        f"💰 Цена: {plan.price} руб. / {plan.period_days} дней\n"
        f"🟢 Текущий статус: `{plan.status.value.upper()}`\n\n"
        f"ℹ️ _Описание:_ {plan.description}"
    )

    await callback.message.edit_text(
        text=text,
        parse_mode="Markdown",
        reply_markup=get_plan_management_keyboard(plan)
    )
    await callback.answer()


@admin_router.callback_query(PlanAdminCallback.filter(F.action.in_({"archive", "deprecate", "activate"})))
async def admin_process_plan_status(callback: CallbackQuery, callback_data: PlanAdminCallback, session: AsyncSession):
    """Обработка кнопок изменения статуса тарифа."""
    # Маппинг экшена на наш Enum статус
    status_mapping = {
        "archive": PlanStatus.ARCHIVED,
        "deprecate": PlanStatus.DEPRECATED,
        "activate": PlanStatus.ACTIVE
    }

    target_status = status_mapping[callback_data.action]

    # 1. Меняем статус в БД
    await change_plan_status(session, callback_data.plan_id, target_status)

    # 2. Перезапрашиваем обновленный тариф, чтобы перерисовать клавиатуру и текст
    query = select(SubscriptionPlan).where(SubscriptionPlan.id == callback_data.plan_id)
    result = await session.execute(query)
    updated_plan = result.scalar_one()

    text = (
        f"📋 *Управление тарифом (СТАТУС ОБНОВЛЕН)*\n\n"
        f"🆔 ID: `{updated_plan.id}`\n"
        f"🏷 Название: *{updated_plan.name}*\n"
        f"💰 Цена: {updated_plan.price} руб. / {updated_plan.period_days} дней\n"
        f"🟢 Текущий статус: `{updated_plan.status.value.upper()}` 🔥\n\n"
        f"ℹ️ _Описание:_ {updated_plan.description}"
    )

    await callback.message.edit_text(
        text=text,
        parse_mode="Markdown",
        reply_markup=get_plan_management_keyboard(updated_plan)
    )
    await callback.answer(f"Статус изменен на {target_status.value}")