from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    service_name: str = "account-service"
    database_url: str = "sqlite:///./account.db"
    log_level: str = "INFO"
    recent_transactions_limit: int = 20
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

@lru_cache
def get_settings() -> Settings:
    return Settings()
