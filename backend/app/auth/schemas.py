from pydantic import BaseModel, EmailStr, Field


class SignupRequest(BaseModel):
    """Request body for user signup."""

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


class AuthMessageResponse(BaseModel):
    """Generic auth message response."""

    message: str
