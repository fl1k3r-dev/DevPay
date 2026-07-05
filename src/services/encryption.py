from cryptography.fernet import Fernet, MultiFernet
from src.config import settings

class EncryptionService:
    def __init__(self):
        # MultiFernet принимает список ключей.
        # Первый ключ используется для ШИФРОВАНИЯ.
        # Все ключи в списке могут использоваться для РАСШИФРОВКИ (ротация!).
        self.merchant_fernet = MultiFernet([
            Fernet(settings.MERCHANT_SECRET_KEY.encode())
        ])

        self.card_fernet = MultiFernet([
            Fernet(settings.CARD_TOKEN_SECRET_KEY.encode())
        ])

    def encrypt_merchant_key(self, raw_key: str) -> str:
        """Шифрует API-ключ мерчанта (ЮKassa) в строку для БД"""
        if not raw_key:
            raise ValueError("API-key cannot be empty")
        return self.merchant_fernet.encrypt(raw_key.encode()).decode()

    def decrypt_merchant_key(self, encrypted_key: str) -> str:
        """Расшифровывает строку из БД обратно в чистый API-ключ"""
        return self.merchant_fernet.decrypt(encrypted_key.encode()).decode()

    def encrypt_card_token(self, raw_token: str) -> str:
        """Шифрует внутренний токен карты/способа оплаты"""
        return self.card_fernet.encrypt(raw_token.encode()).decode()

    def decrypt_card_token(self, encrypted_token: str) -> str:
        """Расшифровывает токен карты"""
        return self.card_fernet.decrypt(encrypted_token.encode()).decode()

# Создаем синглтон сервиса
crypto_service = EncryptionService()