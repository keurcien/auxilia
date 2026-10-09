from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID

from app.exceptions import DomainValidationError


if TYPE_CHECKING:
    from app.users.models import UserDB


class ResourceVisibility(StrEnum):
    personal = "personal"
    workspace = "workspace"
    teams = "teams"


def validate_visibility(
    visibility: ResourceVisibility, team_ids: list[UUID] | set[UUID]
) -> None:
    if visibility == ResourceVisibility.teams and not team_ids:
        raise DomainValidationError("At least one team is required")
    if visibility != ResourceVisibility.teams and team_ids:
        raise DomainValidationError("Teams can only be set with teams visibility")


def is_resource_visible(
    *,
    visibility: ResourceVisibility,
    owner_id: UUID,
    team_ids: set[UUID],
    user: "UserDB",
) -> bool:
    if user.role == "admin" or user.id == owner_id:
        return True
    if visibility == ResourceVisibility.workspace:
        return True
    return (
        visibility == ResourceVisibility.teams
        and user.team_id is not None
        and user.team_id in team_ids
    )


def is_resource_visible_to_identity(
    *,
    visibility: ResourceVisibility,
    owner_id: UUID,
    team_ids: set[UUID],
    user_id: UUID,
    is_admin: bool,
    team_id: UUID | None,
) -> bool:
    return (
        is_admin
        or user_id == owner_id
        or visibility == ResourceVisibility.workspace
        or (
            visibility == ResourceVisibility.teams
            and team_id is not None
            and team_id in team_ids
        )
    )


def audience_contains(
    *,
    parent_visibility: ResourceVisibility,
    parent_owner_id: UUID,
    parent_team_ids: set[UUID],
    child_visibility: ResourceVisibility,
    child_owner_id: UUID,
    child_team_ids: set[UUID],
) -> bool:
    """Whether every non-admin in the parent's baseline audience can use child."""
    if parent_visibility == ResourceVisibility.workspace:
        return child_visibility == ResourceVisibility.workspace
    if parent_visibility == ResourceVisibility.teams:
        if child_visibility == ResourceVisibility.workspace:
            return True
        return (
            child_visibility == ResourceVisibility.teams
            and parent_team_ids <= child_team_ids
        )
    if child_visibility == ResourceVisibility.workspace:
        return True
    if child_visibility == ResourceVisibility.teams:
        return False
    return parent_owner_id == child_owner_id
