import uuid
import hmac
import hashlib
import requests
from urllib.parse import quote
from src.config import settings

# Секрет автоматически подтягивается из настроек .env
SECRET = settings.YOOKASSA_SECRET_KEY

# Данные платежа (имитируем то, что пришлет ЮMoney)
payload = {
    "notification_type": "p2p-incoming",
    "operation_id": f"yoo_{uuid.uuid4().hex[:12]}",
    "amount": "999.00",
    "currency": "643",
    "datetime": "2026-06-30T14:30:00Z",
    "sender": "41001xxxxxxxxxxxx",
    "codepro": "false",
    "label": "999999"  # Наш user_id
}

# 1. Сортируем ключи параметров по алфавиту
sorted_keys = sorted(payload.keys())

# 2. Собираем строку формата key1=value1&key2=value2 с URL-кодированием (строго safe="~")
parts = []
for key in sorted_keys:
    encoded_val = quote(str(payload[key]), safe="~")
    parts.append(f"{key}={encoded_val}")

data_string = "&".join(parts)
print(f"Строка в скрипте: {data_string}")

# 3. Вычисляем актуальную подпись sign через HMAC-SHA256
payload["sign"] = hmac.new(
    SECRET.encode("utf-8"),
    data_string.encode("utf-8"),
    hashlib.sha256
).hexdigest()

# Отправляем данные формы на твой локальный FastAPI
response = requests.post("http://127.0.0.1:8000/api/v1/payments/yoomoney/webhook", data=payload)

print(f"Статус ответа API: {response.status_code}")
print(f"Тело ответа: {response.json()}")