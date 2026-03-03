from pathlib import Path

from pydantic import ConfigDict, SecretStr, model_validator
from pydantic_settings import BaseSettings


BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent
ROOT_ENV = BASE_DIR.parent / ".env"


class MCPServerSettings(BaseSettings):
    # New unified salt — preferred over mcp_api_key_encryption_salt
    salt: SecretStr | None = None
    # Deprecated: use SALT instead
    mcp_api_key_encryption_salt: SecretStr | None = None

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

    model_config: ConfigDict = ConfigDict(
        env_file=ROOT_ENV,
        extra="ignore"
    )


mcp_server_settings: MCPServerSettings = MCPServerSettings()
