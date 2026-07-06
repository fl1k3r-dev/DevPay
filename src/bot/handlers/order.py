import logging
import uuid
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from src.bot.keyboards.inline import get_plans_keyboard, BuyPlanCallback
from src.models import SubscriptionPlan
from src.services.payment import PaymentService
from src.api.dependencies import get_db_service
from src.config import settings

order_router = Router()
logger = logging.getLogger("DevPayBot")

async def _show_plans_interface(target: Message | CallbackQuery, session: AsyncSession):
    """ Вспомогательный метод для отображения тарифов (универсален для сообщений и колбэков) """
    # 1. Получаем актуальные тарифы из базы
    query = select(SubscriptionPlan).order_by(SubscriptionPlan.price)
    result = await session.execute(query)
    plans = result.scalars().all()

    text = "Выберите подходящий тарифный план:"

    if not plans:
        text = "⚠️ Доступных тарифов сейчас нет. Попробуйте позже."
        if isinstance(target, CallbackQuery):
            await target.message.edit_text(text)
        else:
            await target.answer(text)
        return

    # 2. Генерируем клавиатуру
    keyboard = get_plans_keyboard(plans)

    # 3. Отправляем или обновляем сообщение
    if isinstance(target, CallbackQuery):
        await target.message.edit_text(text, reply_markup=keyboard)
    else:
        await target.answer(text, reply_markup=keyboard)


@order_router.message(Command("plans"))
async def cmd_plans(message: Message, session: AsyncSession):
    """Показывает список доступных тарифов по команде /plans"""
    await _show_plans_interface(message, session)

@order_router.callback_query(F.data == "plans")
async def cb_plans(callback: CallbackQuery, session: AsyncSession):
    """Возвращает к списку тарифов при нажатии кнопки 'Попробовать снова' или 'Назад'"""
    await callback.answer()
    await _show_plans_interface(callback, session)


@order_router.callback_query(BuyPlanCallback.filter())
async def handle_buy_click(callback: CallbackQuery, callback_data: BuyPlanCallback, session: AsyncSession):
    """
    Обрабатывает клик по кнопке покупки.
    Генерирует реальную платежную сессию в YooKassa через PaymentService.
    """
    user_id = callback.from_user.id
    plan_id = callback_data.plan_id

    try:
        merchant_id = uuid.UUID(settings.YOOKASSA_SHOP_ID)
    except (ValueError, AttributeError):
        merchant_id = uuid.uuid4()

    # Telegram требует отвечать на каждый callback, иначе кнопка будет "висеть" нажатой
    await callback.answer("Генерируем ссылку...")

    logger.info(f"Пользователь {user_id} выбрал тариф {plan_id}")

    # Уведомляем пользователя, что мы пошли в платежную систему
    await callback.message.edit_text(
        f"⏳ **Формируем счет для тарифа...**\n"
        f"Пожалуйста, подождите, связываемся с YooKassa..."
    )

    payment_service = PaymentService(session)

    try:
        logger.info(f"Бот запрашивает платеж: user_id={user_id}, plan_id={plan_id}")

        payment_url = await payment_service.initiate_subscription_payment(
            user_id=user_id,
            plan_id=plan_id,
            merchant_id=merchant_id
        )

        if not payment_url:
            raise ValueError("Платежный сервис вернул пустой URL")

        # Формируем инлайн-кнопку со ссылкой на оплату
        pay_keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💳 Перейти к оплате (YooKassa)", url=payment_url)]
        ])

        # Обновляем сообщение для пользователя
        await callback.message.edit_text(
            f"✅ **Счет успешно сформирован!**\n\n"
            f"Для активации подписки нажмите на кнопку ниже и оплатите заказ на стороне ЮKassa.\n\n"
            f"⚠️ *После успешной оплаты бот пришлет вам уведомление об активации в течение пары минут.*",
            reply_markup=pay_keyboard,
            parse_mode="Markdown"
        )

    except Exception as e:
        logger.error(f"💥 Ошибка при создании инвойса для пользователя {user_id}: {e}")

        # В случае сбоя возвращаем пользователю понятную ошибку и кнопку "Попробовать еще раз"
        retry_keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Попробовать снова", callback_data="plans")]
        ])

        await callback.message.edit_text(
            "❌ **Не удалось сгенерировать платежную ссылку.**\n"
            "Сервер платежной системы временно недоступен или произошел внутренний сбой. "
            "Пожалуйста, попробуйте позже.",
            reply_markup=retry_keyboard,
            parse_mode="Markdown"
        )