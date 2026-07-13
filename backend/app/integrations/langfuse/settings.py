from pathlib import Path

from pydantic import ConfigDict, PositiveInt
from pydantic_settings import BaseSettings


BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent
ROOT_ENV = BASE_DIR.parent / ".env"


class LangfuseSettings(BaseSettings):
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    langfuse_base_url: str | None = None
    langfuse_timeout: PositiveInt = 15

    model_config: ConfigDict = ConfigDict(
        env_file=ROOT_ENV,
        extra="ignore",
    )


langfuse_settings: LangfuseSettings = LangfuseSettings()
