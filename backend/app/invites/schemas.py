from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr

from app.users.models import WorkspaceRole


class InviteCreate(BaseModel):
    email: EmailStr
    role: WorkspaceRole = WorkspaceRole.member


class InviteRead(BaseModel):
    id: UUID
    email: str
    role: str
    status: str
    invite_url: str | None = None
    invited_by: UUID
    expires_at: datetime
    created_at: datetime
