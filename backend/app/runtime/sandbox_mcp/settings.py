from pydantic import Field
from pydantic_settings import BaseSettings

from app.settings import settings_config


class BridgeSettings(BaseSettings):
    # Must be reachable FROM the sandbox (not the frontend's internal URL).
    url: str = ""
    lease_seconds: int = Field(default=30, ge=3)
    operation_seconds: int = Field(default=900, ge=1)
    max_request_bytes: int = Field(default=1_000_000, ge=1)
    max_result_bytes: int = Field(default=16_000_000, ge=1)
    max_calls: int = Field(default=200, ge=1)

    model_config = settings_config(env_prefix="sandbox_mcp_")


bridge_settings = BridgeSettings()
