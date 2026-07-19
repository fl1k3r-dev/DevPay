import json
import logging
import aio_pika
from typing import Optional, Callable, Awaitable, Any

logger = logging.getLogger(__name__)

class BrokerService:
    def __init__(self, amqp_url: str):
        """Инициализация с доступами, которые мы прописали в docker-compose."""
        self.amqp_url = amqp_url
        self._connection: Optional[aio_pika.RobustConnection] = None
        self._channel: Optional[aio_pika.RobustChannel] = None

    async def connect(self) -> None:
        """Устанавливаем отказоустойчивое соединение с брокером."""
        if not self._connection:
            # Robust-соединение автоматически переподключится, если RabbitMQ перезагрузится
            self._connection = await aio_pika.connect_robust(self.amqp_url)
            self._channel = await self._connection.channel()
            logger.info("Успешное подключение к RabbitMQ.")

    async def publish_event(self, queue_name: str, payload: dict) -> None:
        """Отправить сообщение (событие) в указанную очередь."""
        await self.connect()

        # Декларируем очередь (гарантируем, что она существует)
        queue = await self._channel.declare_queue(queue_name, durable=True)

        # Конвертируем наш dict в JSON-строку и пакуем в байты
        message_body = json.dumps(payload, default=str).encode()

        # Отправляем сообщение напрямую в очередь
        await self._channel.default_exchange.publish(
            aio_pika.Message(
                body=message_body,
                delivery_mode=aio_pika.DeliveryMode.PERSISTENT  # Сообщение сохранится на диске RabbitMQ
            ),
            routing_key=queue_name
        )

    async def start_consuming(self, queue_name: str, callback: Callable[[dict], Awaitable[None]]) -> None:
        """Запустить фоновое чтение очереди."""
        await self.connect()

        queue = await self._channel.declare_queue(queue_name, durable=True)
        # Ограничиваем воркер: брать строго по 1 задаче за раз, пока не подтвердит выполнение (ACK)
        await self._channel.set_qos(prefetch_count=1)

        async def on_message(message: aio_pika.IncomingMessage) -> None:
            async with message.process():     # Автоматически сделает ACK при выходе из контекста
                try:
                    payload = json.loads(message.body.decode())
                    await callback(payload)
                except Exception as e:
                    logger.error(f"Ошибка при обработке сообщения из очереди: {e}")

        await queue.consume(on_message)
        logger.info(f"Воркер подписался на очередь: [{queue_name}]")

    async def close(self) -> None:
        """Закрываем соединение."""
        if self._connection:
            await self._connection.close()
            logger.info("Соединение с RabbitMQ закрыто.")

    async def publish_to_exchange(self, exchange_name: str, payload: dict) -> None:
        """Публикует сообщение в Fanout Exchange (вебхук шлет сюда)."""
        if not self._channel:
            raise RuntimeError("RabbitMQ channel is not initialized. Call connect() first.")

        # Объявляем обменник типа FANOUT
        exchange = await self._channel.declare_exchange(
            exchange_name,
            aio_pika.ExchangeType.FANOUT,
            durable=True
        )

        message_body = json.dumps(payload, default=str).encode()
        message = aio_pika.Message(
            body=message_body,
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT
        )

        # В fanout routing_key не важен, сообщение дублируется во все привязанные очереди
        await exchange.publish(message, routing_key="")
        logger.info(f"📤 Сообщение опубликовано в exchange '{exchange_name}'")


    async def start_consuming_from_exchange(self, exchange_name: str, queue_name: str, callback: Callable[[Any], Any]):
        """Создает персональную очередь, привязывает её к Exchange и начинает слушать."""
        if not self._channel:
            raise RuntimeError("RabbitMQ channel is not initialized. Call connect() first.")

            # 1. Объявляем тот же самый обменник
        exchange = await self._channel.declare_exchange(
            exchange_name,
            aio_pika.ExchangeType.FANOUT,
            durable=True
        )

        # 2. Объявляем уникальную для каждого сервиса очередь
        queue = await self._channel.declare_queue(queue_name, durable=True)

        # 3. Связываем персональную очередь с общим обменником
        await queue.bind(exchange, routing_key="")

        # 4. Запускаем консьюмер
        async def message_wrapper(message: aio_pika.abc.AbstractIncomingMessage):
            async with message.process():
                await callback(message.body)

        await queue.consume(message_wrapper)
        logger.info(f"📢 Успешно подписались на exchange '{exchange_name}' через очередь '{queue_name}'")