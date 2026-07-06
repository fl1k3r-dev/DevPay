from typing import Callable, Dict, Any, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from sqlalchemy.ext.asyncio import async_sessionmaker

class DBSessionMiddleware(BaseMiddleware):
    def __init__(self, session_maker: async_sessionmaker):
        super().__init__()
        self.session_maker = session_maker

    async def __call__(
            self,
            handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
            event: TelegramObject,
            data: Dict[str, Any]
    ) -> Any:
        # Открываем асинхронную сессию из фабрики
        async with self.session_maker() as session:
            # Имя ключа ДОЛЖНО строго совпадать с аргументом в хэндлере (session)
            data["session"] = session
            return await handler(event, data)