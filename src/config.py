from pydantic import computed_field, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # API
    API_VERSION: str = "1.1.0"

    # Telegram bot
    TELEGRAM_BOT_TOKEN: str = Field(..., description="Токен бота для отправки уведомлений")
    TELEGRAM_BOT_URL: str = Field(..., description="Ссылка на Telegram-бота")
    ADMIN_ID: int

    # YooKassa
    YOOKASSA_SHOP_ID: str = Field(..., description="Shop ID из личного кабинета YooKassa")
    YOOKASSA_SECRET_KEY: str = Field(..., description="Секретный API-ключ ЮKassa")

    @computed_field
    @property
    def yookassa_return_url(self) -> str:
        """Возвращает URL для редиректа, подставляя ссылку на бота"""
        return self.TELEGRAM_BOT_URL

    # Криптография
    MERCHANT_SECRET_KEY: str
    CARD_TOKEN_SECRET_KEY: str

    # RabbitMQ
    RABBITMQ_USER: str
    RABBITMQ_PASS: str
    RABBITMQ_HOST: str
    RABBITMQ_PORT: int = 5672

    @computed_field
    @property
    def rabbitmq_url(self) -> str:
        return f"amqp://{self.RABBITMQ_USER}:{self.RABBITMQ_PASS}@{self.RABBITMQ_HOST}:{self.RABBITMQ_PORT}/"

    # Redis
    REDIS_HOST: str
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0

    @computed_field
    @property
    def redis_url(self) -> str:
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

    # Postgres
    POSTGRES_USER: str
    POSTGRES_PASSWORD: str
    POSTGRES_HOST: str
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str

    @computed_field
    @property
    def database_url(self) -> str:
        return f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"

settings = Settings()