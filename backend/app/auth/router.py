from authlib.integrations.starlette_client import OAuth
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.auth.dependencies import get_current_user
from app.auth.schemas import (
    AuthMessageResponse,
    AuthProvidersResponse,
    SigninRequest,
    SignupRequest,
)
from app.auth.settings import auth_settings
from app.auth.utils import create_access_token, get_password_hash, verify_password
from app.database import get_db
from app.users.models import OAuthAccountDB, UserDB, UserRead

router = APIRouter(prefix="/auth", tags=["auth"])

# Initialize OAuth client
oauth = OAuth()
if auth_settings.google_oauth_enabled:
    oauth.register(
        name="google",
        client_id=auth_settings.GOOGLE_CLIENT_ID,
        client_secret=auth_settings.GOOGLE_CLIENT_SECRET,
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )


def _set_auth_cookie(response: JSONResponse, token: str) -> JSONResponse:
    """Helper to set the auth cookie on a response."""
    response.set_cookie(
        key=auth_settings.COOKIE_NAME,
        value=token,
        httponly=auth_settings.COOKIE_HTTPONLY,
        secure=auth_settings.COOKIE_SECURE,
        samesite=auth_settings.COOKIE_SAMESITE,
        domain=auth_settings.COOKIE_DOMAIN,
        max_age=auth_settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )
    return response


def _clear_auth_cookie(response: JSONResponse) -> JSONResponse:
    """Helper to clear the auth cookie."""
    response.delete_cookie(
        key=auth_settings.COOKIE_NAME,
        httponly=auth_settings.COOKIE_HTTPONLY,
        secure=auth_settings.COOKIE_SECURE,
        samesite=auth_settings.COOKIE_SAMESITE,
        domain=auth_settings.COOKIE_DOMAIN,
    )
    return response


@router.get("/providers", response_model=AuthProvidersResponse)
async def get_auth_providers() -> AuthProvidersResponse:
    """
    Return available authentication methods.
    Frontend uses this to show/hide OAuth buttons.
    """
    return AuthProvidersResponse(
        password=True,
        google=auth_settings.google_oauth_enabled,
    )


@router.post("/signup", response_model=UserRead, status_code=201)
async def signup(
    signup_data: SignupRequest,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """
    Register a new user with email and password.
    Sets JWT cookie on success.
    """
    result = await db.execute(select(UserDB).where(UserDB.email == signup_data.email))
    existing_user = result.scalar_one_or_none()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )

    hashed_password = get_password_hash(signup_data.password)

    user = UserDB(
        email=signup_data.email,
        name=signup_data.name,
        hashed_password=hashed_password,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    token = create_access_token(user.id)
    user_read = UserRead.model_validate(user)
    response = JSONResponse(
        status_code=201,
        content=user_read.model_dump(mode="json"),
    )
    return _set_auth_cookie(response, token)


@router.post("/signin", response_model=UserRead)
async def signin(
    signin_data: SigninRequest,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """
    Authenticate user with email and password.
    Sets JWT cookie on success.
    """
    result = await db.execute(select(UserDB).where(UserDB.email == signin_data.email))
    user = result.scalar_one_or_none()

    if user is None or user.hashed_password is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if not verify_password(signin_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    token = create_access_token(user.id)
    user_read = UserRead.model_validate(user)
    response = JSONResponse(
        status_code=200,
        content=user_read.model_dump(mode="json"),
    )
    return _set_auth_cookie(response, token)


@router.post("/signout", response_model=AuthMessageResponse)
async def signout() -> JSONResponse:
    """
    Sign out the current user by clearing the auth cookie.
    """
    response = JSONResponse(
        status_code=200,
        content={"message": "Successfully signed out"},
    )
    return _clear_auth_cookie(response)


@router.get("/google")
async def google_login(request: Request):
    """
    Initiate Google OAuth flow.
    Redirects to Google's authorization page.
    """
    if not auth_settings.google_oauth_enabled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Google OAuth is not configured",
        )

    redirect_uri = f"{auth_settings.FRONTEND_URL}/api/backend/auth/google/callback"
    return await oauth.google.authorize_redirect(request, redirect_uri)


@router.get("/google/callback", name="google_callback")
async def google_callback(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Handle Google OAuth callback.
    Creates or finds user, links OAuth account, sets JWT cookie.
    Redirects to frontend after successful auth.
    """
    if not auth_settings.google_oauth_enabled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Google OAuth is not configured",
        )

    try:
        token = await oauth.google.authorize_access_token(request)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"OAuth error: {e!s}",
        )

    userinfo = token.get("userinfo")
    if not userinfo:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to get user info from Google",
        )

    google_sub = userinfo.get("sub")
    email = userinfo.get("email")
    name = userinfo.get("name")

    if not google_sub or not email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing required user info from Google",
        )

    result = await db.execute(
        select(OAuthAccountDB).where(
            OAuthAccountDB.provider == "google",
            OAuthAccountDB.sub_id == google_sub,
        )
    )
    oauth_account = result.scalar_one_or_none()

    if oauth_account:
        # Existing OAuth account - fetch linked user
        result = await db.execute(
            select(UserDB).where(UserDB.id == oauth_account.user_id)
        )
        user = result.scalar_one_or_none()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Linked user not found",
            )
    else:
        # New OAuth account - check if email exists
        result = await db.execute(select(UserDB).where(UserDB.email == email))
        user = result.scalar_one_or_none()

        if user:
            # Link OAuth to existing user
            oauth_account = OAuthAccountDB(
                provider="google",
                sub_id=google_sub,
                user_id=user.id,
            )
            db.add(oauth_account)
        else:
            # Create new user
            user = UserDB(
                email=email,
                name=name,
            )
            db.add(user)
            await db.flush()  # Get user ID

            # Link OAuth account
            oauth_account = OAuthAccountDB(
                provider="google",
                sub_id=google_sub,
                user_id=user.id,
            )
            db.add(oauth_account)

        await db.commit()
        await db.refresh(user)

    # Create JWT and redirect to frontend with cookie
    access_token = create_access_token(user.id)
    redirect_url = f"{auth_settings.FRONTEND_URL}/agents"
    response = RedirectResponse(url=redirect_url, status_code=302)
    response.set_cookie(
        key=auth_settings.COOKIE_NAME,
        value=access_token,
        httponly=auth_settings.COOKIE_HTTPONLY,
        secure=auth_settings.COOKIE_SECURE,
        samesite=auth_settings.COOKIE_SAMESITE,
        domain=auth_settings.COOKIE_DOMAIN,
        max_age=auth_settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )
    return response


@router.get("/me", response_model=UserRead)
async def get_me(
    current_user: UserDB = Depends(get_current_user),
) -> UserRead:
    """
    Get the currently authenticated user.
    """
    return UserRead.model_validate(current_user)
