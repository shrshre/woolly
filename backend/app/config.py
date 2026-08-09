"""Environment-based application settings.

All hosts, ports, and secrets come from environment variables (12-factor,
AWS-ready). Locally, values are loaded from the repo-root .env file via
docker-compose or pydantic-settings.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Ravelry API (basic read-only auth)
    ravelry_username: str = ""
    ravelry_password: str = ""
    ravelry_api_base_url: str = "https://api.ravelry.com"

    # Redis
    redis_url: str = "redis://localhost:6379/0"
    search_cache_ttl_seconds: int = 3600
    semantic_cache_ttl_seconds: int = 1800
    recommendations_cache_ttl_seconds: int = 3600

    # PostgreSQL
    database_url: str = "postgresql://woolly:woolly@localhost:5432/woolly"

    # Auth (JWT in httpOnly cookie)
    jwt_secret_key: str = "dev-insecure-secret-change-me"
    jwt_expires_days: int = 7
    auth_cookie_name: str = "woolly_token"
    cookie_secure: bool = False  # set True behind HTTPS in production

    # API
    cors_origins: str = "http://localhost:5173"

    # Admin analytics. Placeholder gate until real auth roles exist: the
    # /admin/analytics endpoint requires an X-Admin-Token header matching this
    # value. Empty (the default) means the endpoint is closed to everyone.
    admin_api_token: str = ""

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
