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
    password_enabled: bool
    google_enabled: bool


class InviteAcceptRequest(BaseModel):
    """Request body for accepting an invite with password."""

    token: str
    password: str = Field(min_length=8)
    name: str | None = None
