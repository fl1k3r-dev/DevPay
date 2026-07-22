import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from src.config import settings
from src.bot.handlers.start import start_router
from src.bot.handlers.order import order_router
from src.bot.handlers.admin import admin_router
from src.bot.handlers.profile import profile_router
from src.bot.mq_consumer import start_rabbitmq_consumer

from src.api.dependencies import get_db_service
from src.bot.middlewares.db import DBSessionMiddleware

logger = logging.getLogger("DevPayBot")

# Создаем сет для хранения фоновых задач прямо на уровне модуля
background_tasks = set()

# Функция, которая выполнится при старте бота
async def on_startup(bot: Bot):
    # Создаем задачу
    task = asyncio.create_task(start_rabbitmq_consumer(bot, settings.rabbitmq_url))

    # Добавляем жесткую ссылку в сет
    background_tasks.add(task)

    # Чтобы таска сама удалилась из сета, когда завершится (при выключении)
    task.add_done_callback(background_tasks.discard)

def register_routers(dispatcher: Dispatcher):
    """Регистрация всех роутеров и функций бота"""
    # Порядок важен! Диспетчер опрашивает их сверху вниз
    dispatcher.include_router(start_router)
    dispatcher.include_router(order_router)
    dispatcher.include_router(admin_router)
    dispatcher.include_router(profile_router)
    # Регистрируем функцию старта
    dispatcher.startup.register(on_startup)


async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    logger.info("Инициализация бота...")

    # Инициализируем бот и диспетчер
    bot = Bot(
        token=settings.TELEGRAM_BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN)
    )
    dispatcher = Dispatcher()

    # 🔗 НАСТРОЙКА БАЗЫ ДАННЫХ ДЛЯ БОТА
    # Получаем сервис базы данных точно так же, как в FastAPI бэкенде
    db_service = await get_db_service()

    # Регистрируем мидлварь на обработку сообщений (текстовые команды вроде /plans)
    dispatcher.message.middleware(DBSessionMiddleware(db_service.session_maker))

    # Регистрируем мидлварь на обработку колбэков (клики по кнопкам тарифов)
    dispatcher.callback_query.middleware(DBSessionMiddleware(db_service.session_maker))

    # Подключаем модульные роутеры к главному диспетчеру
    register_routers(dispatcher)

    # Чистим очередь старых сообщений (чтобы бот не отвечал на то, что ему слали, пока он был выключен)
    await bot.delete_webhook(drop_pending_updates=True)

    logger.info("Бот успешно запущен в режиме Long Polling!")

    try:
        await dispatcher.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())