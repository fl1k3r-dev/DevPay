import logging
from typing import Optional, Dict, Any
import httpx

from src.config import settings

logger = logging.getLogger(__name__)

class YookassaClient:
    def __init__(self):
        self.base_url = "https://api.yookassa.ru/v3/payments"
        # ЮKassa использует стандартную Basic-авторизацию: (ShopID, SecretKey)
        self.auth = (settings.YOOKASSA_SHOP_ID, settings.YOOKASSA_SECRET_KEY)

    async def create_payment(
            self,
            amount: float,
            description: str,
            idempotency_key: str,
            metadata: dict
    ) -> Optional[Dict[Any, Any]]:
        """
        Асинхронный метод для создания платежной сессии в YooKassa.

        :param amount: Сумма платежа (например, 1.00)
        :param description: Описание платежа для пользователя
        :param idempotency_key: Уникальный ID транзакции из нашей БД (защита от дублей)
        :param metadata: Метаданные платежа
        :return: Словарь с данными платежа (включая confirmation_url) или None в случае ошибки
        """
        headers = {
            "Idempotence-Key": idempotency_key,
            "Content-Type": "application/json",
        }

        # Формируем тело запроса строго по документации ЮKassa REST API
        payload = {
            "amount": {
                "value": f"{amount:.2f}",    # Форматируем до 2 знаков после запятой
                "currency": "RUB"
            },
            "capture": True,
            "confirmation": {
                "type": "redirect",
                "return_url": settings.yookassa_return_url
            },
            "description": description,
            "metadata": metadata
        }

        try:
            # Открываем асинхронную сессию httpx
            async with httpx.AsyncClient() as client:
                logger.info(f"Отправка запроса в ЮKassa на создание платежа. Ключ идемпотентности: {idempotency_key}")

                response = await client.post(
                    self.base_url,
                    json=payload,
                    auth=self.auth,
                    headers=headers,
                    timeout=10.0      # Таймаут 10 секунд, чтобы не вешать Event Loop
                )

                # Если статус-код 4xx или 5xx, это выбросит исключение HTTPStatusError
                response.raise_for_status()

                data = response.json()
                logger.info(f"Платеж успешно создан в ЮKassa. ID шлюза: {data.get('id')}")
                return data
        except httpx.HTTPStatusError as e:
            logger.error(
                f"Ошибка API ЮKassa при создании платежа: {e.response.status_code} "
                f"- Текст ошибки: {e.response.text}"
            )
            return None
        except httpx.RequestError as e:
            logger.error(f"Сетевая ошибка при запросе к ЮKassa: {e}")
            return None
        except Exception as e:
            logger.error(f"Непредвиденная ошибка в YokassaClient: {e}")
            return None

    async def get_payment_status(self, payment_gateway_id: str) -> Optional[str]:
        """
        Метод для ручной проверки статуса платежа (на случай, если вебхук не дошел).

        :param payment_gateway_id: ID платежа на стороне ЮKassa (например, '21b23b59-000f-5000-9000-01b5042c1325')
        :return: Текущий статус в ЮKassa (succeeded, pending, canceled) или None
        """
        url = f"{self.base_url}/{payment_gateway_id}"

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url, auth=self.auth, timeout=5.0)
                response.raise_for_status()
                data = response.json()
                return data.get("status")

        except Exception as e:
            logger.error(f"Ошибка при проверке статуса платежа {payment_gateway_id}: {e}")
            return None
