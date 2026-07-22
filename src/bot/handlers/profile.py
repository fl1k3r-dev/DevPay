import logging
from datetime import datetime, timezone

from sqlalchemy import select
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import Subscription, SubscriptionStatus
from src.services.subscription import SubscriptionService

profile_router = Router()
logger = logging.getLogger("DevPayBot")

async def _get_user_subscription(session: AsyncSession, user_id: int) -> Subscription | None:
    """Вспомогательный метод для поиска актуальной подписки пользователя."""
    query = (
        select(Subscription)
        .where(Subscription.user_id == user_id)
        .order_by(Subscription.created_at.desc())
        .limit(1)
    )
    result = await session.execute(query)
    return result.scalar_one_or_none()

def get_profile_keyboard(subscription: Subscription | None) -> InlineKeyboardMarkup:
    """Генерирует клавиатуру для профиля в зависимости от статуса подписки."""
    buttons = []

    if subscription and subscription.status == SubscriptionStatus.ACTIVE:
        buttons.append([InlineKeyboardButton(text="❌ Отменить автопродление", callback_data=f"cancel_sub_{subscription.id}")])
    else:
        buttons.append([InlineKeyboardButton(text="💳 Выбрать тариф", callback_data="plans")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


@profile_router.message(Command("profile"))
@profile_router.callback_query(F.data == "profile")
async def show_profile(target: Message | CallbackQuery, session: AsyncSession) -> None:
    """Отображает профиль пользователя и текущий статус подписки."""
    user_id = target.from_user.id

    # 1. Запрашиваем активную подписку пользователя
    subscription = await _get_user_subscription(session, user_id)

    if subscription and subscription.status in (SubscriptionStatus.ACTIVE, SubscriptionStatus.CANCELED):
        end_date = subscription.current_period_end.strftime("%d.%m.%Y в %H:%M") if subscription.current_period_end else "Не ограничено"

        now = datetime.now(timezone.utc)

        # Если период уже прошел, подписка неактивна, даже если воркер еще не сменил статус в БД
        if subscription.current_period_end <= now:
            status_text = "❌ Истекла"
        elif subscription.status == SubscriptionStatus.CANCELED:
            status_text = "🟡 Отменена (доступ до окончания периода)"
        elif subscription.status == SubscriptionStatus.ACTIVE:
            status_text = "🟢 Активна"
        else:
            status_text = "❌ Неактивна"

        text = (
            f"👤 **Ваш профиль**\n\n"
            f"🆔 ID: `{user_id}`\n"
            f"📦 Статус: {status_text}\n"
            f"📅 Действует до: **{end_date}**\n"
        )
    else:
        text = (
            f"👤 **Ваш профиль**\n\n"
            f"🆔 ID: `{user_id}`\n"
            f"🔴 **У вас нет активной подписки.**\n\n"
            f"Оформите подписку через `/plans`, чтобы разблокировать все возможности!"
        )

    keyboard = get_profile_keyboard(subscription)

    if isinstance(target, CallbackQuery):
        await target.message.edit_text(text, reply_markup=keyboard, parse_mode="Markdown")
        await target.answer()
    else:
        await target.answer(text, reply_markup=keyboard, parse_mode="Markdown")


@profile_router.callback_query(F.data.startswith("cancel_sub_"))
async def handle_cancel_subscription(callback: CallbackQuery, session: AsyncSession) -> None:
    """Обрабатывает мягкую отмену конкретной подписки."""
    user_id = callback.from_user.id

    # Извлекаем UUID подписки из callback_data
    sub_id_str = callback.data.replace("cancel_sub_", "")

    try:
        import uuid
        sub_uuid = uuid.UUID(sub_id_str)

        service = SubscriptionService(session, broker_service=None)
        await service.cancel_subscription(sub_uuid)
        await session.commit()

        await callback.answer("Подписка успешно отменена!", show_alert=True)

        await show_profile(callback, session)

    except Exception as e:
        logger.error(f"Ошибка при отмене подписки {sub_id_str} пользователем {user_id}: {e}")
        await callback.answer("Не удалось отменить подписку. Попробуйте позже.", show_alert=True)

