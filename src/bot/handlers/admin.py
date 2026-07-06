import logging
from decimal import Decimal
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

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