from pydantic import model_validator
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

    # Workload identity federation (see federation.py): keyless Anthropic /
    # OpenAI auth from the GCP service account the backend runs as. Takes
    # precedence over the provider's API key once its required IDs are set.
    anthropic_federation_rule_id: str | None = None
    anthropic_organization_id: str | None = None
    anthropic_service_account_id: str | None = None
    anthropic_workspace_id: str | None = None
    openai_identity_provider_id: str | None = None
    openai_service_account_id: str | None = None

    model_config = settings_config()

    @property
    def anthropic_federation(self) -> bool:
        return all((self.anthropic_federation_rule_id, self.anthropic_organization_id))

    @property
    def openai_federation(self) -> bool:
        return all((self.openai_identity_provider_id, self.openai_service_account_id))

    @model_validator(mode="after")
    def _federation_is_complete(self) -> "ModelProviderSettings":
        # A partial federation config is a typo, not a choice: fail at startup
        # instead of silently serving the provider with its API key (or not at all).
        # Required pair -> (is it complete?, every ID of that provider).
        providers = {
            "ANTHROPIC_FEDERATION_RULE_ID and ANTHROPIC_ORGANIZATION_ID": (
                self.anthropic_federation,
                (
                    self.anthropic_federation_rule_id,
                    self.anthropic_organization_id,
                    self.anthropic_service_account_id,
                    self.anthropic_workspace_id,
                ),
            ),
            "OPENAI_IDENTITY_PROVIDER_ID and OPENAI_SERVICE_ACCOUNT_ID": (
                self.openai_federation,
                (self.openai_identity_provider_id, self.openai_service_account_id),
            ),
        }
        errors = [
            f"Workload identity federation needs both {required}."
            for required, (complete, ids) in providers.items()
            if any(ids) and not complete
        ]
        if errors:
            raise ValueError(" ".join(errors))
        return self


model_provider_settings = ModelProviderSettings()
