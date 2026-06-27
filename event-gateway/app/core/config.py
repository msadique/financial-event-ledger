from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    service_name: str = "event-gateway"
    database_url: str = "sqlite:///./gateway.db"
    account_service_url: str = "http://localhost:8081"
    account_service_timeout_seconds: float = 2.0
    account_service_max_attempts: int = 3
    circuit_breaker_failure_threshold: int = 5
    circuit_breaker_recovery_seconds: float = 30.0

    rate_limit_enabled: bool = True
    rate_limit_requests: int = 120
    rate_limit_window_seconds: float = 60.0

    async_fallback_enabled: bool = True
    async_fallback_poll_seconds: float = 1.0
    async_fallback_batch_size: int = 25
    async_fallback_base_backoff_seconds: float = 1.0
    async_fallback_max_backoff_seconds: float = 60.0
    async_fallback_jitter_seconds: float = 0.25

    log_level: str = "INFO"
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
