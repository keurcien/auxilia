from pydantic import BaseModel, Field, HttpUrl


class WorkspaceObservabilityResponse(BaseModel):
    enabled: bool
    is_configured: bool
    base_url: str
    timeout_seconds: int
    public_key_last4: str | None = None
    public_key_length: int | None = None
    has_secret_key: bool = False


class WorkspaceObservabilityUpdate(BaseModel):
    enabled: bool = True
    base_url: HttpUrl
    timeout_seconds: int = Field(default=15, ge=1, le=120)
    public_key: str | None = Field(default=None, max_length=4096)
    secret_key: str | None = Field(default=None, max_length=4096)
