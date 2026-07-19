import json
import logging
import asyncio
from aiogram import Bot
import aio_pika

logger = logging.getLogger("DevPayBotConsumer")

async def process_payment_event(message:aio_pika.IncomingMessage, bot: Bot):
    """Обрабатывает входящее сообщение об оплате из RabbitMQ."""
    async with message.process():
        try:
            payload = json.loads(message.body.decode())
            user_id = payload.get("user_id")
            status = payload.get("status")
            amount = payload.get("amount")

            logger.info(f"Получено событие из RMQ для юзера {user_id}: статус {status}")

            if status == "success":
                text = (
                    "🎉 **Оплата прошла успешно!**\n\n"
                    "Ваша подписка успешно активирована. "
                    f"Сумма: {amount} руб.\n"
                    "Спасибо, что вы с нами! 🚀"
                )

                # Отправляем сообщение напрямую через инстанс бота
                await bot.send_message(chat_id=user_id, text=text, parse_mode="Markdown")
                logger.info(f"💌 Уведомление об оплате успешно отправлено юзеру {user_id}")

        except Exception as e:
            logger.error(f"💥 Ошибка при обработке сообщения из RabbitMQ: {e}")


async def start_rabbitmq_consumer(bot: Bot, ampq_url: str):
    """Запускает фоновое прослушивание очереди."""
    while True:
        try:
            connection = await aio_pika.connect_robust(ampq_url)
            channel = await connection.channel()

            # Объявляем Fanout Exchange (тот самый, в который FastAPI шлет эвенты)
            exchange = await channel.declare_exchange(
                name="payment_events_exchange",
                type=aio_pika.ExchangeType.FANOUT,
                durable=True
            )

            # Объявляем уникальную очередь специально для инстанса БОТА
            queue = await channel.declare_queue("bot_payment_events_queue", durable=True)

            # Связываем эту очередь с общим обменником
            await queue.bind(exchange, routing_key="")

            logger.info("📢 Консьюмер RabbitMQ успешно запущен и слушает очередь 'bot_payment_events_queue'...")

            # Начинаем принимать сообщения
            await queue.consume(lambda msg: process_payment_event(msg, bot))

            # Держим таску запущенной
            await asyncio.Future()

        except asyncio.CancelledError:
            logger.info("Консьюмер RabbitMQ останавливается...")
            break
        except Exception as e:
            logger.error(f"Потеряно соединение с RabbitMQ ({e}). Повторная попытка через 5 секунд...")
            await asyncio.sleep(5)