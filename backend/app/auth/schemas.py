from pydantic import BaseModel, EmailStr, Field


class SignupRequest(BaseModel):
    """Request body for user signup (used for setup)."""

    email: EmailStr
    password: str = Field(min_length=8)
    name: str | None = None


class SigninRequest(BaseModel):
    """Request body for user signin."""

    email: EmailStr
    password: str


class TwoFactorSigninResponse(BaseModel):
    two_factor_required: bool = True


class TwoFactorSigninVerifyRequest(BaseModel):
    code: str


class AuthProvidersResponse(BaseModel):
    """Response for available auth providers."""

    password: bool = True
    google: bool = False
    setup_required: bool = False


class AuthMessageResponse(BaseModel):
    """Generic auth message response."""

    message: str


class SetupStatusResponse(BaseModel):
    """Response for setup status check."""

    setup_required: bool


class InviteInfoResponse(BaseModel):
    """Response for invite token info."""

    email: str
    role: str
    workspace_name: str
    password_enabled: bool
    google_enabled: bool


class InviteAcceptRequest(BaseModel):
    """Request body for accepting an invite with password."""

    token: str
    password: str = Field(min_length=8)
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)


class WorkspaceAuthenticationResponse(BaseModel):
    enabled: bool
    is_configured: bool
    google_exclusive: bool
    client_id_last4: str | None = None
    client_id_length: int | None = None
    callback_url: str


class WorkspaceAuthenticationUpdate(BaseModel):
    enabled: bool = True
    google_exclusive: bool = False
    client_id: str | None = Field(default=None, max_length=2048)
    client_secret: str | None = Field(default=None, max_length=4096)
