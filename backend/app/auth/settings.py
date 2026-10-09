from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings

from app.settings import settings_config


class AuthSettings(BaseSettings):
    # JWT Configuration
    JWT_SECRET_KEY: str = Field(
        default="change-me-in-production",
        validation_alias=AliasChoices(
            "BACKEND_JWT_SECRET_KEY",
            "JWT_SECRET_KEY",
        ),
    )
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24 hours

    # Cookie Configuration
    COOKIE_NAME: str = "access_token"
    COOKIE_SECURE: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "BACKEND_COOKIE_SECURE",
            "COOKIE_SECURE",
        ),
    )
    COOKIE_HTTPONLY: bool = True
    COOKIE_SAMESITE: str = "lax"
    COOKIE_DOMAIN: str | None = None

    # Frontend URL for OAuth redirects
    FRONTEND_URL: str = "http://localhost:3000"

    model_config = settings_config()


auth_settings = AuthSettings()
