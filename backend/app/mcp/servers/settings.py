from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings

from app.settings import settings_config


class MCPServerSettings(BaseSettings):
    # New unified salt — preferred over mcp_api_key_encryption_salt
    salt: SecretStr | None = None
    # Deprecated: use SALT instead
    mcp_api_key_encryption_salt: SecretStr | None = None
    # The official MCP server catalog (see catalog.py). Defaults to auxilia's
    # hosted file so every installation picks up new servers without upgrading.
    # Opt out by setting MCP_CATALOG_URL= (empty) to use only the bundled
    # snapshot, or point it at your own file to publish an internal list of
    # approved servers. Fetch failures always fall back to the bundled
    # snapshot, so this is never on the availability path.
    mcp_catalog_url: str | None = (
        "https://pub-7a6e8912b3c448b8a8bfa47a0363f7bc.r2.dev/mcp/catalog.yaml"
    )

    @model_validator(mode="after")
    def require_salt(self) -> "MCPServerSettings":
        if self.salt is None and self.mcp_api_key_encryption_salt is None:
            raise ValueError(
                "Encryption salt not configured. Set SALT (or the deprecated "
                "MCP_API_KEY_ENCRYPTION_SALT) in your environment."
            )
        return self

    def get_salt(self) -> str:
        """Return the active salt value, preferring SALT over the deprecated key."""
        if self.salt is not None:
            return self.salt.get_secret_value()
        return self.mcp_api_key_encryption_salt.get_secret_value()  # type: ignore[union-attr]

    model_config = settings_config()


mcp_server_settings: MCPServerSettings = MCPServerSettings()
