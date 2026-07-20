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
    xiaomi_api_key: str | None = None
    openrouter_api_key: str | None = None
    metaai_api_key: str | None = None
    # CDN-hosted whitelist YAML (see whitelist.py). Unset/empty → the bundled
    # snapshot only (self-hosters can also point it at their own file).
    model_whitelist_url: str | None = (
        "https://pub-7a6e8912b3c448b8a8bfa47a0363f7bc.r2.dev/models/whitelist.yaml"
    )

    model_config: ConfigDict = ConfigDict(env_file=ROOT_ENV, extra="ignore")


model_provider_settings = ModelProviderSettings()
