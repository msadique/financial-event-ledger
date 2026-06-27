from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    service_name: str = "account-service"
    database_url: str = "sqlite:///./account.db"
    otel_enabled: bool = False
    otel_exporter_otlp_endpoint: str = "http://localhost:4318"
    otel_export_timeout_seconds: float = 5.0
    otel_service_version: str = "0.4.0"
    otel_environment: str = "local"
    otel_excluded_urls: str = "health,metrics"

    log_level: str = "INFO"
    recent_transactions_limit: int = 20
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

@lru_cache
def get_settings() -> Settings:
    return Settings()
