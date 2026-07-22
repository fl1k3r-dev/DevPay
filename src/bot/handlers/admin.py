import logging
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from uuid import UUID

from aiogram import Router, F, Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandObject
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot.callbacks.admin import PlanAdminCallback
from src.bot.filters.admin import IsAdminFilter
from src.bot.keyboards.admin import get_plan_management_keyboard
from src.models import SubscriptionPlan, PlanStatus, Subscription, SubscriptionStatus
from src.services.admin_plan import change_plan_status
from src.services.subscription import SubscriptionService

admin_router = Router()
logger = logging.getLogger("DevPayBot")

# Защита на уровне роутера: обрабатывать сообщения ТОЛЬКО от админа
admin_router.message.filter(IsAdminFilter())


@admin_router.message(Command("add_plan"))
async def admin_add_plan(message: Message, session: AsyncSession):
    """
    Команда для добавления тарифа админом.
    Формат: /add_plan Название | Описание | Цена | Длительность
    """
    try:
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
    status_mapping = {
        "archive": PlanStatus.ARCHIVED,
        "deprecate": PlanStatus.DEPRECATED,
        "activate": PlanStatus.ACTIVE
    }

    target_status = status_mapping[callback_data.action]

    await change_plan_status(session, callback_data.plan_id, target_status)

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


@admin_router.message(Command("admin"))
async def show_admin_panel(message: Message):
    text = (
        "👑 **Панель администратора DevPay**\n\n"
        "🛠 **Доступные команды:**\n"
        "• `/grant <user_id>` — выдать подписку выбором тарифа\n"
        "• `/revoke <user_id>` — отзыв активности подписки пользователя\n"
        "• `/cancel_sub <sub_id>` — отмена подписки по ее UUID\n"
        "• `/add_plan` — добавить новый тариф\n"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats"),
            InlineKeyboardButton(text="🔌 Healthcheck", callback_data="admin_health")
        ],
        [
            InlineKeyboardButton(text="❌ Закрыть", callback_data="close_admin")
        ]
    ])

    await message.answer(text, reply_markup=kb, parse_mode="Markdown")


# ==========================================
# 1. РУЧНАЯ ВЫДАЧА ПОДПИСКИ: /grant <user_id>
# ==========================================
@admin_router.message(Command("grant"))
async def admin_grant_start(message: Message, command: CommandObject, session: AsyncSession):
    """
    Вызов: /grant 1776096235
    """
    if not command.args:
        await message.answer("⚠️ Использование: `/grant <user_id>`", parse_mode="Markdown")
        return

    try:
        target_user_id = int(command.args.strip())
    except ValueError:
        await message.answer("⚠️ `user_id` должен быть числом.")
        return

    # Получаем активные тарифы
    stmt = select(SubscriptionPlan).where(SubscriptionPlan.status == PlanStatus.ACTIVE)
    result = await session.execute(stmt)
    plans = result.scalars().all()

    if not plans:
        await message.answer("⚠️ В базе нет активных тарифных планов.")
        return

    keyboard_builder = []
    for plan in plans:
        keyboard_builder.append([
            InlineKeyboardButton(
                text=f"{plan.name} ({plan.period_days} дн. / {plan.price} RUB)",
                callback_data=f"admin_grant_plan:{target_user_id}:{plan.id}"
            )
        ])

    await message.answer(
        f"Выберите тарифный план для пользователя `{target_user_id}`:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard_builder),
        parse_mode="Markdown"
    )


@admin_router.callback_query(F.data.startswith("admin_grant_plan:"))
async def admin_grant_confirm(callback: CallbackQuery, session: AsyncSession, bot: Bot):
    _, target_user_id_str, plan_id_str = callback.data.split(":")
    target_user_id = int(target_user_id_str)
    plan_id = UUID(plan_id_str)

    plan = await session.get(SubscriptionPlan, plan_id)
    if not plan:
        await callback.answer("Тарифный план не найден.", show_alert=True)
        return

    now = datetime.now(timezone.utc)
    end_date = now + timedelta(days=plan.period_days)

    subscription = Subscription(
        user_id=target_user_id,
        plan_id=plan.id,
        merchant_id=None,
        status=SubscriptionStatus.ACTIVE,
        encrypted_payment_method_id="MANUAL_ADMIN_GRANT",
        price_at_creation=plan.price,
        period_days_at_creation=plan.period_days,
        current_period_start=now,
        current_period_end=end_date,
        next_payment_at=None,
        auto_renew=False,
    )
    session.add(subscription)
    await session.commit()

    # Ответ админу в боте
    await callback.message.edit_text(
        f"✅ **Подписка успешно выдана!**\n\n"
        f"👤 **Пользователь:** `{target_user_id}`\n"
        f"📦 **Тариф:** {plan.name}\n"
        f"🆔 **ID подписки (`sub_id`):** `{subscription.id}`\n"
        f"📅 **Действует до:** {end_date.strftime('%d.%m.%Y %H:%M')}",
        parse_mode="Markdown"
    )
    await callback.answer()

    # Уведомляем пользователя
    try:
        await bot.send_message(
            chat_id=target_user_id,
            text=f"🎁 **Вам начислена подписка «{plan.name}»!**\n\n"
                 f"📅 Срок действия: до **{end_date.strftime('%d.%m.%Y %H:%M')}**.",
            parse_mode="Markdown"
        )
    except TelegramAPIError:
        await callback.message.answer("⚠️ Пользователь заблокировал бота, но подписка в БД выдана.")


# ==========================================
# 2. ПРИНУДИТЕЛЬНЫЙ ОТЗЫВ ПОДПИСКИ ПО USER_ID: /revoke <user_id>
# ==========================================
@admin_router.message(Command("revoke"))
async def admin_revoke_subscription(
    message: Message,
    command: CommandObject,
    session: AsyncSession,
    bot: Bot
):
    """
    Принудительное аннулирование подписки пользователя администратором.
    Использование: /revoke <user_id>
    """
    if not command.args:
        await message.answer(
            "❌ **Ошибка:** Укажите `user_id`: `/revoke <user_id>`",
            parse_mode="Markdown"
        )
        return

    try:
        target_user_id = int(command.args.strip())
    except ValueError:
        await message.answer("❌ **Ошибка:** `user_id` должен быть числом!")
        return

    now = datetime.now(timezone.utc)

    # Аннулируем все подписки пользователя, срок действия которых ещё не истёк
    stmt = (
        update(Subscription)
        .where(
            Subscription.user_id == target_user_id,
            Subscription.current_period_end > now
        )
        .values(
            status=SubscriptionStatus.EXPIRED,
            auto_renew=False,
            current_period_end=now,
            next_payment_at=None,
            updated_at=now
        )
        .execution_options(synchronize_session=False)
    )

    result = await session.execute(stmt)
    await session.commit()

    if result.rowcount == 0:
        await message.answer(
            f"ℹ️ У пользователя `{target_user_id}` нет активных подписок для аннулирования.",
            parse_mode="Markdown"
        )
        return

    await message.answer(
        f"✅ Успешно аннулировано подписок для `{target_user_id}`: {result.rowcount}",
        parse_mode="Markdown"
    )

    # Уведомляем пользователя об отзыве доступа
    try:
        await bot.send_message(
            chat_id=target_user_id,
            text="⚠️ Ваша подписка была аннулирована администратором."
        )
    except TelegramAPIError:
        pass


# ==========================================
# 3. ОТМЕНА ПО UUID ПОДПИСКИ: /cancel_sub <subscription_id>
# ==========================================
@admin_router.message(Command("cancel_sub"))
async def admin_cancel_by_sub_id(
        message: Message,
        command: CommandObject,
        session: AsyncSession
):
    """
    Пример использования: /cancel_sub 2fc4268a-6c92-4ff6-8b30-4547f7c603e0
    """
    if not command.args:
        await message.answer("❌ **Ошибка:** Укажите UUID подписки: `/cancel_sub <uuid>`", parse_mode="Markdown")
        return

    try:
        sub_id = UUID(command.args.strip())
    except ValueError:
        await message.answer("❌ **Ошибка:** Некорректный формат UUID.")
        return

    query = select(Subscription).where(Subscription.id == sub_id)
    result = await session.execute(query)
    subscription = result.scalar_one_or_none()

    if not subscription:
        await message.answer("❌ Подписка с таким UUID не найдена.")
        return

    subscription.status = SubscriptionStatus.CANCELED
    subscription.auto_renew = False
    subscription.updated_at = datetime.now(timezone.utc)

    await session.commit()
    await message.answer(
        f"✅ Статус подписки `{sub_id}` изменен на `canceled` (`auto_renew=False`).",
        parse_mode="Markdown"
    )