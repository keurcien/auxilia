from pathlib import Path
from pydantic import ConfigDict
from pydantic_settings import BaseSettings


BASE_DIR = Path(__file__).resolve().parent.parent.parent
ROOT_ENV = BASE_DIR.parent / ".env"


class ModelProviderSettings(BaseSettings):
    openai_api_key: str | None = None
    deepseek_api_key: str | None = None
    anthropic_api_key: str | None = None
    google_api_key: str | None = None
    litellm_api_key: str | None = None
    litellm_api_base: str | None = None

    model_config: ConfigDict = ConfigDict(
        env_file=ROOT_ENV,
        extra="ignore"
    )


model_provider_settings = ModelProviderSettings()
