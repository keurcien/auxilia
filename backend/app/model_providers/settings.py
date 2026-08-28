from pydantic_settings import BaseSettings

from app.settings import settings_config


class ModelProviderSettings(BaseSettings):
    openai_api_key: str | None = None
    deepseek_api_key: str | None = None
    anthropic_api_key: str | None = None
    google_api_key: str | None = None
    xiaomi_api_key: str | None = None
    openrouter_api_key: str | None = None
    metaai_api_key: str | None = None
    # The project's canonical model catalog (see whitelist.py). Defaults to
    # auxilia's hosted file so every installation picks up new models without
    # upgrading — the LiteLLM cost-map pattern. Opt out by setting
    # MODEL_WHITELIST_URL= (empty) to use only the bundled snapshot, or point
    # it at your own file. Fetch failures always fall back to the bundled
    # snapshot, so this is never on the availability path.
    model_whitelist_url: str | None = (
        "https://pub-7a6e8912b3c448b8a8bfa47a0363f7bc.r2.dev/models/whitelist.yaml"
    )

    model_config = settings_config()


model_provider_settings = ModelProviderSettings()
