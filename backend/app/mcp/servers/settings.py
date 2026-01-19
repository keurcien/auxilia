from pydantic_settings import BaseSettings
from pathlib import Path
from pydantic import SecretStr

BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent
ROOT_ENV = BASE_DIR.parent / ".env"


class MCPServerSettings(BaseSettings):
    # Encryption Key for MCP API Keys
    mcp_api_key_encryption_key: SecretStr

    class Config:
        env_file = ROOT_ENV
        extra = "ignore"


mcp_server_settings = MCPServerSettings()
