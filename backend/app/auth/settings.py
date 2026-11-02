from typing import Literal

from pydantic import AliasChoices, EmailStr, Field, field_validator, model_validator
from pydantic_settings import BaseSettings

from app.settings import settings_config


TWO_FACTOR_CHALLENGE_COOKIE = "two_factor_challenge"


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
    SESSION_MAX_DAYS: int = Field(default=30, ge=1)
    REMEMBER_ME_DAYS: int = Field(default=3650, ge=1)

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
    COOKIE_SAMESITE: Literal["lax", "strict", "none"] = "lax"
    COOKIE_DOMAIN: str | None = None

    # Frontend URL for OAuth redirects
    FRONTEND_URL: str = "http://localhost:3000"

    # Password reset and SMTP
    PASSWORD_RESET_TOKEN_EXPIRE_MINUTES: int = Field(default=60, ge=5, le=1440)
    PASSWORD_RESET_REQUEST_COOLDOWN_SECONDS: int = Field(default=60, ge=0, le=3600)
    SMTP_HOST: str | None = None
    SMTP_PORT: int = Field(default=587, ge=1, le=65535)
    SMTP_USERNAME: str | None = None
    SMTP_PASSWORD: str | None = None
    SMTP_FROM_EMAIL: EmailStr | None = None
    SMTP_FROM_NAME: str = "auxilia"
    SMTP_REPLY_TO: EmailStr | None = None
    SMTP_USE_TLS: bool = True
    SMTP_USE_SSL: bool = False
    SMTP_TIMEOUT_SECONDS: float = Field(default=10, gt=0, le=120)

    model_config = settings_config()

    @field_validator("COOKIE_SAMESITE", mode="before")
    @classmethod
    def _lowercase_samesite(cls, value: object) -> object:
        return value.lower() if isinstance(value, str) else value

    @field_validator(
        "SMTP_HOST",
        "SMTP_USERNAME",
        "SMTP_PASSWORD",
        "SMTP_FROM_EMAIL",
        "SMTP_REPLY_TO",
        mode="before",
    )
    @classmethod
    def _empty_smtp_value_is_none(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value

    @model_validator(mode="after")
    def _validate_smtp(self) -> "AuthSettings":
        if self.SMTP_USE_TLS and self.SMTP_USE_SSL:
            raise ValueError("SMTP_USE_TLS and SMTP_USE_SSL cannot both be enabled")
        if (self.SMTP_USERNAME is None) != (self.SMTP_PASSWORD is None):
            raise ValueError("SMTP_USERNAME and SMTP_PASSWORD must be set together")
        if (self.SMTP_HOST is None) != (self.SMTP_FROM_EMAIL is None):
            raise ValueError("SMTP_HOST and SMTP_FROM_EMAIL must be set together")
        return self

    @property
    def smtp_configured(self) -> bool:
        return self.SMTP_HOST is not None and self.SMTP_FROM_EMAIL is not None


auth_settings = AuthSettings()
