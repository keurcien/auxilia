from uuid import UUID

from fastapi import APIRouter, Depends

from app.auth.dependencies import require_admin
from app.auth.tokens.models import (
    PersonalAccessTokenCreate,
    PersonalAccessTokenCreated,
    PersonalAccessTokenRead,
)
from app.auth.tokens.service import PersonalAccessTokenService, get_pat_service
from app.users.models import UserDB


router = APIRouter(prefix="/auth/tokens", tags=["tokens"])


@router.post("", response_model=PersonalAccessTokenCreated, status_code=201)
async def create_token(
    data: PersonalAccessTokenCreate,
    current_user: UserDB = Depends(require_admin),
    service: PersonalAccessTokenService = Depends(get_pat_service),
) -> PersonalAccessTokenCreated:
    pat, plaintext = await service.create_token(current_user.id, data.name)
    return PersonalAccessTokenCreated(
        id=pat.id,
        name=pat.name,
        prefix=pat.prefix,
        created_at=pat.created_at,
        token=plaintext,
    )


@router.get("", response_model=list[PersonalAccessTokenRead])
async def list_tokens(
    current_user: UserDB = Depends(require_admin),
    service: PersonalAccessTokenService = Depends(get_pat_service),
) -> list[PersonalAccessTokenRead]:
    pats = await service.list_tokens(current_user.id)
    return [PersonalAccessTokenRead.model_validate(pat) for pat in pats]


@router.delete("/{token_id}", status_code=204)
async def delete_token(
    token_id: UUID,
    current_user: UserDB = Depends(require_admin),
    service: PersonalAccessTokenService = Depends(get_pat_service),
) -> None:
    await service.delete_token(token_id, current_user.id)
