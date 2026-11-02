from urllib.parse import urlencode, urlsplit
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse, RedirectResponse, Response

from app.auth.configuration import (
    WorkspaceAuthenticationService,
    get_workspace_authentication_service,
)
from app.auth.dependencies import (
    SupervisionContext,
    get_current_user,
    get_supervision_context,
    require_admin,
)
from app.auth.schemas import (
    AuthMessageResponse,
    AuthProvidersResponse,
    ForgotPasswordRequest,
    InviteAcceptRequest,
    InviteInfoResponse,
    ResetPasswordRequest,
    SetupStatusResponse,
    SigninRequest,
    SignupRequest,
    TwoFactorSigninResponse,
    TwoFactorSigninVerifyRequest,
    WorkspaceAuthenticationResponse,
    WorkspaceAuthenticationUpdate,
)
from app.auth.service import AuthService, get_auth_service
from app.auth.settings import TWO_FACTOR_CHALLENGE_COOKIE, auth_settings
from app.auth.two_factor import create_scoped_token
from app.auth.utils import attach_auth_cookie
from app.exceptions import NoInviteError
from app.invites.service import InviteService, get_invite_service
from app.users.models import UserDB
from app.users.schemas import CurrentUserResponse, SupervisionInfo
from app.workspaces.constants import ACTIVE_WORKSPACE_COOKIE
from app.workspaces.cookies import (
    clear_active_workspace_cookie,
    set_active_workspace_cookie,
)
from app.workspaces.dependencies import get_active_workspace_id
from app.workspaces.service import WorkspaceService, get_workspace_service


router = APIRouter(prefix="/auth", tags=["auth"])


def _oauth_return_to(value: str | None) -> str | None:
    if value is None or not value.startswith("/") or value.startswith("//"):
        return None
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc or parsed.path != "/mcp/authorize":
        return None
    return value


def _same_origin_path(value: str | None) -> str | None:
    if (
        value is None
        or not value.startswith("/")
        or value[1:2] in ("/", "\\")
        or any(char in value for char in "\t\n\r")
    ):
        return None
    return value


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
    attach_auth_cookie(response, token)
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
        password_reset=auth_settings.smtp_configured,
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


@router.post("/password/forgot", response_model=AuthMessageResponse)
async def forgot_password(
    data: ForgotPasswordRequest,
    service: AuthService = Depends(get_auth_service),
) -> AuthMessageResponse:
    await service.request_password_reset(data)
    return AuthMessageResponse(
        message="If an account exists for this email, a reset link has been sent"
    )


@router.post("/password/reset", response_model=AuthMessageResponse)
async def reset_password(
    data: ResetPasswordRequest,
    service: AuthService = Depends(get_auth_service),
) -> AuthMessageResponse:
    await service.reset_password(data)
    return AuthMessageResponse(message="Password reset successfully")


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
    return_to: str | None = None,
    next_path: str | None = Query(default=None, alias="next"),
    remember_me: bool = False,
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
    safe_return_to = _oauth_return_to(return_to)
    if safe_return_to is not None:
        request.session["auth_return_to"] = safe_return_to
    else:
        request.session.pop("auth_return_to", None)
    safe_next = _same_origin_path(next_path)
    if safe_next is not None:
        request.session["auth_next"] = safe_next
    else:
        request.session.pop("auth_next", None)
    request.session["remember_me"] = remember_me
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
    return_to = _oauth_return_to(request.session.pop("auth_return_to", None))
    next_path = _same_origin_path(request.session.pop("auth_next", None))
    remember_me = request.session.pop("remember_me", False) is True
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
            remember_me=remember_me,
        )
    except NoInviteError:
        query = {"error": "no_invite"}
        if return_to is not None:
            query["returnTo"] = return_to
        elif next_path is not None:
            query["next"] = next_path
        return RedirectResponse(
            url=f"{auth_settings.FRONTEND_URL}/auth?{urlencode(query)}",
            status_code=302,
        )

    if not user.two_factor_enabled and await authentication.enforces_two_factor(
        workspace_id
    ):
        response = RedirectResponse(
            url=f"{auth_settings.FRONTEND_URL}/two-factor/setup",
            status_code=302,
        )
        attach_auth_cookie(response, access_token)
        if user.active_workspace_id is not None:
            set_active_workspace_cookie(response, user.active_workspace_id)
        return response

    if user.two_factor_enabled:
        challenge = create_scoped_token(
            user.id,
            "two_factor_signin",
            remember_me=remember_me,
        )
        query = {"two_factor": "required"}
        if return_to is not None:
            query["returnTo"] = return_to
        elif next_path is not None:
            query["next"] = next_path
        response = RedirectResponse(
            url=f"{auth_settings.FRONTEND_URL}/auth?{urlencode(query)}",
            status_code=302,
        )
        _attach_two_factor_cookie(response, challenge)
        if user.active_workspace_id is not None:
            set_active_workspace_cookie(response, user.active_workspace_id)
        return response

    response = RedirectResponse(
        url=f"{auth_settings.FRONTEND_URL}{return_to or next_path or '/agents'}",
        status_code=302,
    )
    attach_auth_cookie(response, access_token)
    if user.active_workspace_id is not None:
        set_active_workspace_cookie(response, user.active_workspace_id)
    return response


@router.get("/me", response_model=CurrentUserResponse)
async def get_me(
    current_user: UserDB = Depends(get_current_user),
    context: SupervisionContext | None = Depends(get_supervision_context),
    authentication: WorkspaceAuthenticationService = Depends(
        get_workspace_authentication_service
    ),
) -> CurrentUserResponse:
    two_factor_enforced = bool(
        context is None
        and current_user.active_workspace_id is not None
        and await authentication.enforces_two_factor(current_user.active_workspace_id)
    )
    supervision = (
        SupervisionInfo(
            actor_id=context.actor.id,
            actor_name=context.actor.name,
            actor_email=context.actor.email,
            workspace_id=current_user.active_workspace_id,
        )
        if context is not None and current_user.active_workspace_id is not None
        else None
    )
    return CurrentUserResponse.model_validate(
        current_user,
        update={
            "workspace_id": current_user.active_workspace_id,
            "two_factor_enforced": two_factor_enforced,
            "two_factor_required": (
                two_factor_enforced and not current_user.two_factor_enabled
            ),
            "supervision": supervision,
        },
    )
