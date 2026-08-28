from pydantic import PositiveInt
from pydantic_settings import BaseSettings

from app.settings import settings_config


class LangfuseSettings(BaseSettings):
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    langfuse_base_url: str | None = None
    langfuse_timeout: PositiveInt = 15

    model_config = settings_config()


langfuse_settings: LangfuseSettings = LangfuseSettings()
