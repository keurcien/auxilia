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
    # CDN-hosted whitelist YAML (see whitelist.py). Unset → the bundled
    # snapshot only, so self-hosters never fetch from someone else's bucket;
    # deployments that want live catalog updates set MODEL_WHITELIST_URL.
    model_whitelist_url: str | None = None

    model_config: ConfigDict = ConfigDict(env_file=ROOT_ENV, extra="ignore")


model_provider_settings = ModelProviderSettings()
