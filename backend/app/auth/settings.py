from pydantic_settings import BaseSettings

from app.settings import settings_config


class AuthSettings(BaseSettings):
    # JWT Configuration
    JWT_SECRET_KEY: str = "change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24 hours

    # Cookie Configuration
    COOKIE_NAME: str = "access_token"
    COOKIE_SECURE: bool = False  # Set to True in production with HTTPS
    COOKIE_HTTPONLY: bool = True
    COOKIE_SAMESITE: str = "lax"
    COOKIE_DOMAIN: str | None = None

    # Google OAuth (optional - enables if both are set)
    GOOGLE_CLIENT_ID: str | None = None
    GOOGLE_CLIENT_SECRET: str | None = None

    # Frontend URL for OAuth redirects
    FRONTEND_URL: str = "http://localhost:3000"

    # When True and Google OAuth is configured, password auth is disabled
    AUTH_GOOGLE_EXCLUSIVE: bool = False

    model_config = settings_config()

    @property
    def google_oauth_enabled(self) -> bool:
        """Check if Google OAuth is configured."""
        return bool(self.GOOGLE_CLIENT_ID and self.GOOGLE_CLIENT_SECRET)

    @property
    def password_enabled(self) -> bool:
        """Password auth is disabled when Google exclusive mode is active."""
        return not (self.google_oauth_enabled and self.AUTH_GOOGLE_EXCLUSIVE)


auth_settings = AuthSettings()
