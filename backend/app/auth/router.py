from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse, RedirectResponse, Response

from app.auth.configuration import (
    WorkspaceAuthenticationService,
    get_workspace_authentication_service,
)
from app.auth.dependencies import get_current_user, require_admin
from app.auth.schemas import (
    AuthMessageResponse,
    AuthProvidersResponse,
    InviteAcceptRequest,
    InviteInfoResponse,
    SetupStatusResponse,
    SigninRequest,
    SignupRequest,
    TwoFactorSigninResponse,
    TwoFactorSigninVerifyRequest,
    WorkspaceAuthenticationResponse,
    WorkspaceAuthenticationUpdate,
)
from app.auth.service import AuthService, get_auth_service
from app.auth.settings import auth_settings
from app.auth.two_factor import create_scoped_token
from app.exceptions import NoInviteError
from app.invites.service import InviteService, get_invite_service
from app.users.models import UserDB
from app.users.schemas import CurrentUserResponse
from app.workspaces.constants import ACTIVE_WORKSPACE_COOKIE
from app.workspaces.dependencies import get_active_workspace_id
from app.workspaces.router import (
    clear_active_workspace_cookie,
    set_active_workspace_cookie,
)
from app.workspaces.service import WorkspaceService, get_workspace_service


router = APIRouter(prefix="/auth", tags=["auth"])
TWO_FACTOR_CHALLENGE_COOKIE = "two_factor_challenge"


def _attach_auth_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=auth_settings.COOKIE_NAME,
        value=token,
        httponly=auth_settings.COOKIE_HTTPONLY,
        secure=auth_settings.COOKIE_SECURE,
        samesite=auth_settings.COOKIE_SAMESITE,
        domain=auth_settings.COOKIE_DOMAIN,
        max_age=auth_settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


def _attach_two_factor_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=TWO_FACTOR_CHALLENGE_COOKIE,
        value=token,
        httponly=True,
        secure=auth_settings.COOKIE_SECURE,
        samesite=auth_settings.COOKIE_SAMESITE,
        domain=auth_settings.COOKIE_DOMAIN,
        max_age=10 * 60,
    )


def _delete_two_factor_cookie(response: Response) -> None:
    response.delete_cookie(
        key=TWO_FACTOR_CHALLENGE_COOKIE,
        httponly=True,
        secure=auth_settings.COOKIE_SECURE,
        samesite=auth_settings.COOKIE_SAMESITE,
        domain=auth_settings.COOKIE_DOMAIN,
    )


def _auth_response(user: UserDB, token: str, status_code: int = 200) -> JSONResponse:
    user_read = CurrentUserResponse.model_validate(
        user, update={"workspace_id": user.active_workspace_id}
    )
    response = JSONResponse(
        status_code=status_code,
        content=user_read.model_dump(mode="json"),
    )
    _attach_auth_cookie(response, token)
    if user.active_workspace_id is not None:
        set_active_workspace_cookie(response, user.active_workspace_id)
    else:
        clear_active_workspace_cookie(response)
    return response


@router.get("/providers", response_model=AuthProvidersResponse)
async def get_auth_providers(
    request: Request,
    service: AuthService = Depends(get_auth_service),
    authentication: WorkspaceAuthenticationService = Depends(
        get_workspace_authentication_service
    ),
) -> AuthProvidersResponse:
    user_count = await service.count_users()
    workspace_id = await service.resolve_workspace_id(
        request.cookies.get(ACTIVE_WORKSPACE_COOKIE)
    )
    config = (
        await authentication.get_runtime_config(workspace_id)
        if workspace_id is not None
        else None
    )
    return AuthProvidersResponse(
        password=(
            await authentication.password_enabled(workspace_id)
            if workspace_id is not None
            else True
        ),
        google=config is not None,
        setup_required=user_count == 0,
    )


@router.get("/manage", response_model=WorkspaceAuthenticationResponse)
async def get_workspace_authentication(
    _: UserDB = Depends(require_admin),
    workspace_id: UUID = Depends(get_active_workspace_id),
    service: WorkspaceAuthenticationService = Depends(
        get_workspace_authentication_service
    ),
) -> WorkspaceAuthenticationResponse:
    return await service.get_response(workspace_id)


@router.put("/manage", response_model=WorkspaceAuthenticationResponse)
async def update_workspace_authentication(
    data: WorkspaceAuthenticationUpdate,
    _: UserDB = Depends(require_admin),
    workspace_id: UUID = Depends(get_active_workspace_id),
    service: WorkspaceAuthenticationService = Depends(
        get_workspace_authentication_service
    ),
) -> WorkspaceAuthenticationResponse:
    return await service.update(workspace_id, data)


@router.delete("/manage", response_model=WorkspaceAuthenticationResponse)
async def delete_workspace_authentication(
    _: UserDB = Depends(require_admin),
    workspace_id: UUID = Depends(get_active_workspace_id),
    service: WorkspaceAuthenticationService = Depends(
        get_workspace_authentication_service
    ),
) -> WorkspaceAuthenticationResponse:
    return await service.clear(workspace_id)


@router.get("/setup/status", response_model=SetupStatusResponse)
async def get_setup_status(
    service: AuthService = Depends(get_auth_service),
) -> SetupStatusResponse:
    return SetupStatusResponse(setup_required=await service.count_users() == 0)


@router.post("/setup", response_model=CurrentUserResponse, status_code=201)
async def setup(
    signup_data: SignupRequest,
    service: AuthService = Depends(get_auth_service),
) -> JSONResponse:
    user, token = await service.setup(signup_data)
    return _auth_response(user, token, status_code=201)


@router.post("/signin", response_model=CurrentUserResponse | TwoFactorSigninResponse)
async def signin(
    request: Request,
    signin_data: SigninRequest,
    service: AuthService = Depends(get_auth_service),
) -> JSONResponse:
    user, token = await service.signin(
        signin_data, request.cookies.get(ACTIVE_WORKSPACE_COOKIE)
    )
    if user.two_factor_enabled:
        response = JSONResponse(
            content=TwoFactorSigninResponse().model_dump(mode="json")
        )
        _attach_two_factor_cookie(response, token)
        if user.active_workspace_id is not None:
            set_active_workspace_cookie(response, user.active_workspace_id)
        else:
            clear_active_workspace_cookie(response)
        return response
    return _auth_response(user, token)


@router.post("/signin/two-factor", response_model=CurrentUserResponse)
async def verify_two_factor_signin(
    request: Request,
    data: TwoFactorSigninVerifyRequest,
    service: AuthService = Depends(get_auth_service),
) -> JSONResponse:
    challenge = request.cookies.get(TWO_FACTOR_CHALLENGE_COOKIE)
    if not challenge:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Two-factor challenge has expired",
        )
    user, token = await service.verify_two_factor_signin(
        challenge, data, request.cookies.get(ACTIVE_WORKSPACE_COOKIE)
    )
    response = _auth_response(user, token)
    _delete_two_factor_cookie(response)
    return response


@router.post("/signout", response_model=AuthMessageResponse)
async def signout() -> JSONResponse:
    response = JSONResponse(
        status_code=200,
        content={"message": "Successfully signed out"},
    )
    response.delete_cookie(
        key=auth_settings.COOKIE_NAME,
        httponly=auth_settings.COOKIE_HTTPONLY,
        secure=auth_settings.COOKIE_SECURE,
        samesite=auth_settings.COOKIE_SAMESITE,
        domain=auth_settings.COOKIE_DOMAIN,
    )
    response.delete_cookie(
        key=ACTIVE_WORKSPACE_COOKIE,
        httponly=True,
        secure=auth_settings.COOKIE_SECURE,
        samesite=auth_settings.COOKIE_SAMESITE,
        domain=auth_settings.COOKIE_DOMAIN,
    )
    _delete_two_factor_cookie(response)
    return response


@router.get("/invite/{token}", response_model=InviteInfoResponse)
async def get_invite_info(
    token: str,
    service: InviteService = Depends(get_invite_service),
    workspaces: WorkspaceService = Depends(get_workspace_service),
    authentication: WorkspaceAuthenticationService = Depends(
        get_workspace_authentication_service
    ),
) -> InviteInfoResponse:
    invite = await service.get_by_token(token)
    if not invite:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invalid or expired invite",
        )
    return InviteInfoResponse(
        email=invite.email,
        role=invite.role,
        workspace_name=(await workspaces.get_or_404(invite.workspace_id)).name,
        password_enabled=await authentication.password_enabled(invite.workspace_id),
        google_enabled=(
            await authentication.get_runtime_config(invite.workspace_id) is not None
        ),
    )


@router.post(
    "/invite/accept",
    response_model=CurrentUserResponse | TwoFactorSigninResponse,
    status_code=201,
)
async def accept_invite(
    data: InviteAcceptRequest,
    service: AuthService = Depends(get_auth_service),
) -> JSONResponse:
    user, token = await service.accept_invite(data)
    if user.two_factor_enabled:
        response = JSONResponse(
            status_code=201,
            content=TwoFactorSigninResponse().model_dump(mode="json"),
        )
        _attach_two_factor_cookie(response, token)
        if user.active_workspace_id is not None:
            set_active_workspace_cookie(response, user.active_workspace_id)
        return response
    return _auth_response(user, token, status_code=201)


@router.get("/google")
async def google_login(
    request: Request,
    invite_token: str | None = None,
    service: AuthService = Depends(get_auth_service),
    authentication: WorkspaceAuthenticationService = Depends(
        get_workspace_authentication_service
    ),
):
    if invite_token:
        invite = await service.invites.get_by_token(invite_token)
        if invite is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Invalid or expired invite",
            )
        workspace_id = invite.workspace_id
    else:
        workspace_id = await service.resolve_workspace_id(
            request.cookies.get(ACTIVE_WORKSPACE_COOKIE)
        )
    if workspace_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Google OAuth is not configured",
        )
    oauth = await authentication.build_oauth(workspace_id)
    if oauth is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Google OAuth is not configured",
        )
    if invite_token:
        request.session["invite_token"] = invite_token
    else:
        request.session.pop("invite_token", None)
    request.session["oauth_workspace_id"] = str(workspace_id)

    client = oauth.create_client("google")
    return await client.authorize_redirect(request, authentication.callback_url)


@router.get("/google/callback", name="google_callback")
async def google_callback(
    request: Request,
    service: AuthService = Depends(get_auth_service),
    authentication: WorkspaceAuthenticationService = Depends(
        get_workspace_authentication_service
    ),
):
    workspace_value = request.session.get("oauth_workspace_id")
    if not isinstance(workspace_value, str):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid OAuth session",
        )
    workspace_id = await service.resolve_workspace_id(workspace_value)
    if workspace_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid OAuth session",
        )
    oauth = await authentication.build_oauth(workspace_id)
    if oauth is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Google OAuth is not configured",
        )

    try:
        client = oauth.create_client("google")
        token_data = await client.authorize_access_token(request)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OAuth authentication failed",
        ) from e

    userinfo = token_data.get("userinfo")
    if not userinfo:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to get user info from Google",
        )

    google_sub = userinfo.get("sub")
    email = userinfo.get("email")
    if not google_sub or not email or userinfo.get("email_verified") is not True:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Google did not return a verified email address",
        )

    invite_token = request.session.pop("invite_token", None)
    request.session.pop("oauth_workspace_id", None)

    try:
        user, access_token = await service.oauth_signin_or_link(
            provider="google",
            sub_id=google_sub,
            email=email,
            name=userinfo.get("name"),
            picture_url=userinfo.get("picture"),
            invite_token=invite_token,
            workspace_id=workspace_id,
        )
    except NoInviteError:
        return RedirectResponse(
            url=f"{auth_settings.FRONTEND_URL}/auth?error=no_invite",
            status_code=302,
        )

    if user.two_factor_enabled:
        challenge = create_scoped_token(user.id, "two_factor_signin")
        response = RedirectResponse(
            url=f"{auth_settings.FRONTEND_URL}/auth?two_factor=required",
            status_code=302,
        )
        _attach_two_factor_cookie(response, challenge)
        if user.active_workspace_id is not None:
            set_active_workspace_cookie(response, user.active_workspace_id)
        return response

    response = RedirectResponse(
        url=f"{auth_settings.FRONTEND_URL}/agents",
        status_code=302,
    )
    _attach_auth_cookie(response, access_token)
    if user.active_workspace_id is not None:
        set_active_workspace_cookie(response, user.active_workspace_id)
    return response


@router.get("/me", response_model=CurrentUserResponse)
async def get_me(
    current_user: UserDB = Depends(get_current_user),
) -> CurrentUserResponse:
    return CurrentUserResponse.model_validate(
        current_user, update={"workspace_id": current_user.active_workspace_id}
    )
