from authlib.integrations.starlette_client import OAuth
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import func, select

from app.auth.dependencies import get_current_user
from app.auth.schemas import (
    AuthMessageResponse,
    AuthProvidersResponse,
    InviteAcceptRequest,
    InviteInfoResponse,
    SetupStatusResponse,
    SigninRequest,
    SignupRequest,
)
from app.auth.settings import auth_settings
from app.auth.utils import create_access_token, get_password_hash, verify_password
from app.database import get_db
from app.invites.models import InviteStatus
from app.invites.service import (
    get_pending_invite_by_email,
    validate_invite,
)
from app.users.models import OAuthAccountDB, UserDB, UserRead, WorkspaceRole

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
async def get_auth_providers(
    db: AsyncSession = Depends(get_db),
) -> AuthProvidersResponse:
    """Return available authentication methods."""
    result = await db.execute(select(func.count()).select_from(UserDB))
    user_count = result.scalar_one()

    return AuthProvidersResponse(
        password=auth_settings.password_enabled,
        google=auth_settings.google_oauth_enabled,
        setup_required=user_count == 0,
    )


@router.get("/setup/status", response_model=SetupStatusResponse)
async def get_setup_status(
    db: AsyncSession = Depends(get_db),
) -> SetupStatusResponse:
    """Check whether initial setup is required (no users exist)."""
    result = await db.execute(select(func.count()).select_from(UserDB))
    user_count = result.scalar_one()
    return SetupStatusResponse(setup_required=user_count == 0)


@router.post("/setup", response_model=UserRead, status_code=201)
async def setup(
    signup_data: SignupRequest,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Create the first user as admin. Fails if any users already exist."""
    result = await db.execute(select(func.count()).select_from(UserDB))
    user_count = result.scalar_one()
    if user_count > 0:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Setup already completed",
        )

    hashed_password = get_password_hash(signup_data.password)
    user = UserDB(
        email=signup_data.email,
        name=signup_data.name,
        hashed_password=hashed_password,
        role=WorkspaceRole.admin,
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
    """Authenticate user with email and password."""
    if not auth_settings.password_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Password authentication is disabled",
        )

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
    """Sign out the current user by clearing the auth cookie."""
    response = JSONResponse(
        status_code=200,
        content={"message": "Successfully signed out"},
    )
    return _clear_auth_cookie(response)


@router.get("/invite/{token}", response_model=InviteInfoResponse)
async def get_invite_info(
    token: str,
    db: AsyncSession = Depends(get_db),
) -> InviteInfoResponse:
    """Return invite info for a given token."""
    invite = await validate_invite(token, db)
    if not invite:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invalid or expired invite",
        )
    return InviteInfoResponse(
        email=invite.email,
        role=invite.role,
        password_enabled=auth_settings.password_enabled,
        google_enabled=auth_settings.google_oauth_enabled,
    )


@router.post("/invite/accept", response_model=UserRead, status_code=201)
async def accept_invite(
    data: InviteAcceptRequest,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Accept an invite and create a user account with password."""
    if not auth_settings.password_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Password authentication is disabled",
        )

    invite = await validate_invite(data.token, db)
    if not invite:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired invite",
        )

    # Check if email is already registered
    result = await db.execute(select(UserDB).where(UserDB.email == invite.email))
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )

    hashed_password = get_password_hash(data.password)
    user = UserDB(
        email=invite.email,
        name=data.name,
        hashed_password=hashed_password,
        role=WorkspaceRole(invite.role),
    )
    db.add(user)

    invite.status = InviteStatus.accepted
    db.add(invite)

    await db.commit()
    await db.refresh(user)

    token = create_access_token(user.id)
    user_read = UserRead.model_validate(user)
    response = JSONResponse(
        status_code=201,
        content=user_read.model_dump(mode="json"),
    )
    return _set_auth_cookie(response, token)


@router.get("/google")
async def google_login(request: Request, invite_token: str | None = None):
    """Initiate Google OAuth flow."""
    if not auth_settings.google_oauth_enabled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Google OAuth is not configured",
        )

    # Store invite token in session so we can use it in the callback
    if invite_token:
        request.session["invite_token"] = invite_token

    redirect_uri = f"{auth_settings.FRONTEND_URL}/api/backend/auth/google/callback"
    return await oauth.google.authorize_redirect(request, redirect_uri)


@router.get("/google/callback", name="google_callback")
async def google_callback(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Handle Google OAuth callback."""
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

    # Check for existing OAuth link
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
        # New OAuth link - check if email exists (link to existing user)
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
            # New user - require a matching invite
            invite_token = request.session.pop("invite_token", None)
            invite = None

            if invite_token:
                invite = await validate_invite(invite_token, db)

            # Fall back to matching by email
            if not invite:
                invite = await get_pending_invite_by_email(email, db)

            if not invite:
                # No invite found - reject
                return RedirectResponse(
                    url=f"{auth_settings.FRONTEND_URL}/auth?error=no_invite",
                    status_code=302,
                )

            user = UserDB(
                email=email,
                name=name,
                role=WorkspaceRole(invite.role),
            )
            db.add(user)
            await db.flush()

            oauth_account = OAuthAccountDB(
                provider="google",
                sub_id=google_sub,
                user_id=user.id,
            )
            db.add(oauth_account)

            invite.status = InviteStatus.accepted
            db.add(invite)

        await db.commit()
        await db.refresh(user)

    # Create JWT and redirect
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
    """Get the currently authenticated user."""
    return UserRead.model_validate(current_user)
