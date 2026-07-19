from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

start_router = Router()

@start_router.message(CommandStart())
async def cmd_start(message: Message):
    """Хэндлер на команду /start"""
    user_name = message.from_user.full_name
    await message.answer(
        f"Привет, {user_name}! 👋\n\n"
        "Это демонстрационный бот платежной системы.\n"
        "Здесь ты можешь оформить и протестировать подписку.\n\n"
        "Используй команду /plans, чтобы посмотреть доступные тарифы."
    )


@start_router.message(Command("help"))
async def cmd_help(message: Message):
    """Хэндлер на команду /help"""
    await message.answer(
        "💡 **Доступные команды:**\n"
        "/start - Перезапустить бота\n"
        "/plans - Посмотреть тарифные планы и купить подписку"
    )