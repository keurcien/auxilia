from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings

from app.settings import settings_config


class ArtifactSettings(BaseSettings):
    s3_bucket: str = ""
    s3_endpoint_url: str | None = None
    s3_region: str = "us-east-1"
    s3_access_key_id: str | None = None
    s3_secret_access_key: SecretStr | None = None
    s3_session_token: SecretStr | None = None
    s3_addressing_style: Literal["auto", "path", "virtual"] = "auto"
    s3_prefix: str = "auxilia/artifacts"
    max_bytes: int = Field(default=20 * 1024 * 1024, ge=1024, le=100 * 1024 * 1024)
    allowed_roots: list[str] = ["/workspace", "/mnt/data", "/tmp"]

    model_config = settings_config(env_prefix="ARTIFACT_", env_ignore_empty=True)

    @model_validator(mode="after")
    def credentials(self):
        if bool(self.s3_access_key_id) != bool(self.s3_secret_access_key):
            raise ValueError(
                "Set both artifact S3 access key and secret, or neither for SDK credentials"
            )
        return self


artifact_settings = ArtifactSettings()
