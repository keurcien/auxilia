from pydantic_settings import BaseSettings
from pathlib import Path
from pydantic import SecretStr

BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent
ROOT_ENV = BASE_DIR.parent / ".env"


class MCPServerSettings(BaseSettings):
    # Salt used to derive the Fernet encryption key for MCP API keys
    mcp_api_key_encryption_salt: SecretStr

    class Config:
        env_file = ROOT_ENV
        extra = "ignore"


mcp_server_settings = MCPServerSettings()
