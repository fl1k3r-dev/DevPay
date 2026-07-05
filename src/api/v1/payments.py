import logging
import hmac
import hashlib
from urllib.parse import quote
from fastapi import APIRouter, Depends, HTTPException, Request

from src.config import settings
from src.api.dependencies import get_broker_service
from src.services.broker import BrokerService

router = APIRouter(prefix="/payments", tags=["Payments"])
logger = logging.getLogger("DevPayAPI")

def verify_yoomoney_signature(form_data: dict, secret_key: str) -> bool:
    """Проверка подлинности уведомления ЮMoney по стандарту HMAC-SHA256."""
    # 1. Переводим FormData в обычный словарь, чтобы им можно было манипулировать
    payload_params = dict(form_data)

    # 2. ИЗВЛЕКАЕМ ПОДПИСЬ, КОТОРУЮ ПРИСЛАЛ КЛИЕНТ
    client_sign = payload_params.pop("sign", None)
    if not client_sign:
        logger.warning("❌ В запросе отсутствует поле 'sign'")
        return False

    # 3. Сортируем ключи параметров по алфавиту
    sorted_keys = sorted(payload_params.keys())

    # 4. Собираем строку формата key1=value1&key2=value2 с URL-кодированием (RFC 3986)
    parts = []
    for key in sorted_keys:
        # ЮMoney требует кодирования значений строк
        encoded_val = quote(str(payload_params[key]), safe="~")
        parts.append(f"{key}={encoded_val}")

    data_string = "&".join(parts)

    logger.info(f"Строка на сервере: {data_string}")
    # 5. Считаем HMAC-SHA256 с использованием секретного ключа
    expected_sign = hmac.new(
        secret_key.encode("utf-8"),
        data_string.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()

    # Безопасное сравнение строк для защиты от атак по времени (Timing Attacks)
    return hmac.compare_digest(expected_sign, client_sign)


@router.post("/yoomoney/webhook")
async def yoomoney_webhook(
        request: Request,
        broker: BrokerService = Depends(get_broker_service) # Зависимость вместо глобального объекта
):
    """Гибкий эндпоинт, принимающий все параметры формы ЮMoney."""
    # Получаем данные в виде словаря из x-www-form-urlencoded
    form_data = await request.form()
    form_dict = dict(form_data)

    logger.info(f"Получен вебхук ЮMoney. Операция: {form_dict.get('operation_id')}")

    if not verify_yoomoney_signature(form_dict, settings.YOOMONEY_SECRET):
        logger.warning("❌ Невалидная подпись HMAC-SHA256! Запрос отклонен.")
        raise HTTPException(status_code=400, detail="Invalid signature")

    try:
        payload = {
            "user_id": int(form_dict.get("label")),
            "amount": float(form_dict.get("amount")),
            "transaction_id": form_dict.get("operation_id")
        }
    except (ValueError, TypeError):
        logger.error("Ошибка парсинга label или amount из формы")
        raise HTTPException(status_code=400, detail="Invalid data format")

    await broker.publish_event("payment_events", payload)
    logger.info(f"🚀 Событие {form_dict.get('operation_id')} успешно отправлено в RabbitMQ.")

    return {"status": "ok"}