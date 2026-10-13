import re
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings

from app.settings import settings_config


# A CSP host-source: `https:` (any host) or one https origin, optionally a path.
# Anything else (quotes, `;`, spaces) could rewrite the viewer's whole policy.
CSP_SOURCE = re.compile(
    r"https:(//(\*\.)?[a-z0-9-]+(\.[a-z0-9-]+)*(:(?P<port>\d{1,5}))?(/[a-z0-9._~%/-]*)?)?",
    re.IGNORECASE,
)


class ArtifactSettings(BaseSettings):
    # gs://name → native GCS with ADC (keyless); a bare name or s3://name → S3 API.
    bucket: str = ""
    s3_endpoint_url: str | None = None
    s3_region: str = "us-east-1"
    s3_access_key_id: str | None = None
    s3_secret_access_key: SecretStr | None = None
    s3_session_token: SecretStr | None = None
    s3_addressing_style: Literal["auto", "path", "virtual"] = "auto"
    prefix: str = "auxilia/artifacts"
    max_bytes: int = Field(default=20 * 1024 * 1024, ge=1024, le=100 * 1024 * 1024)
    # Paths inside the execution sandbox, never the Auxilia host.
    allowed_roots: list[str] = ["/tmp"]  # nosec B108
    # Where an HTML artifact's scripts, styles, fonts and images may load from,
    # e.g. ["https://cdn.jsdelivr.net", "https://cdnjs.cloudflare.com"].
    # ["https:"] allows any https host; [] allows inline content only.
    html_sources: list[str] = ["https:"]

    model_config = settings_config(env_prefix="ARTIFACT_", env_ignore_empty=True)

    @property
    def provider(self) -> Literal["gcs", "s3"] | None:
        if not self.bucket:
            return None
        return "gcs" if self.bucket.startswith("gs://") else "s3"

    @property
    def bucket_name(self) -> str:
        return self.bucket.removeprefix("gs://").removeprefix("s3://")

    @property
    def endpoint(self) -> str | None:
        return (self.s3_endpoint_url or None) if self.provider == "s3" else None

    @field_validator("html_sources")
    @classmethod
    def csp_sources(cls, sources: list[str]) -> list[str]:
        for source in sources:
            match = CSP_SOURCE.fullmatch(source)
            port = match and match["port"]
            if not match or (port and not 0 < int(port) < 65536):
                raise ValueError(
                    f"{source!r} is not an https source like https://cdn.jsdelivr.net"
                )
        return sources

    @model_validator(mode="after")
    def credentials(self):
        if self.provider == "gcs" and (
            self.s3_endpoint_url or self.s3_access_key_id or self.s3_session_token
        ):
            raise ValueError(
                "A gs:// artifact bucket uses Google ADC; unset the S3 endpoint and keys"
            )
        if bool(self.s3_access_key_id) != bool(self.s3_secret_access_key):
            raise ValueError(
                "Set both artifact S3 access key and secret, or neither for SDK credentials"
            )
        if self.s3_session_token and not self.s3_access_key_id:
            raise ValueError(
                "An artifact S3 session token requires the access key and secret"
            )
        return self


artifact_settings = ArtifactSettings()
