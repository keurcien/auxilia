# Teams feature — implementation plan

## Goal & model

Introduce **teams** as a workspace-admin-defined grouping that grants **member-level usage** of agents.

Confirmed constraints (from product discussion):

- A **user belongs to at most one team** → single nullable FK on the user, **no membership join table**.
- An **agent can be assigned to many teams** → `AgentTeamDB` join table.
- A team has a **name** and a **color** (reuses the agent background palette, `web/src/lib/colors.ts → AGENT_COLORS`).
- **No `is_public` column** for now.
- Team membership grants only **`member`** on agents linked to that team. Higher levels still come from the existing `AgentUserPermissionDB`.
- Invites may carry a team → the invited user lands already in a team with usable agents.
- Per-user permission **always wins** over team permission in resolution (and team only ever grants `member`, so redundancy is harmless).

### Permission resolution (the core change)

`AgentService._resolve_permission` (`app/agents/core/service.py:46`) gains one branch, ordered so a real grant always beats the team floor:

```
1. owner of the agent                      → "owner"
2. workspace admin                         → "admin"
3. explicit AgentUserPermissionDB grant    → member | editor | admin
4. user's team is linked to the agent      → "member"     ← NEW
5. otherwise                               → None
```

Because a user has **exactly one** `team_id`, the "is this agent linked to my team" check matches **at most one** `AgentTeamDB` row per agent — so it can be folded directly into the existing `list_with_permissions` join **without cartesian fan-out** (this is why the one-team constraint matters: it keeps the query flat).

---

## Backend

### 1. New module `app/teams/`

Follows `router → service → repository → model`, mirroring `app/invites/` and `app/agents/core/`.

#### `app/teams/models.py`

```python
from uuid import UUID
from sqlmodel import Field, SQLModel
from app.models import BaseDBModel, TimestampMixin


class TeamBase(SQLModel):
    name: str = Field(max_length=255, nullable=False)
    color: str | None = Field(default=None, max_length=7, nullable=True)  # hex "#RRGGBB"


class TeamDB(TeamBase, BaseDBModel, table=True):
    __tablename__ = "teams"

    name: str = Field(max_length=255, nullable=False)
    color: str | None = Field(default=None, max_length=7, nullable=True)


class AgentTeamDB(TimestampMixin, SQLModel, table=True):
    __tablename__ = "agent_teams"
    __table_args__ = (UniqueConstraint("agent_id", "team_id", name="uq_agent_team"),)

    agent_id: UUID = Field(foreign_key="agents.id", primary_key=True, nullable=False)
    team_id: UUID = Field(foreign_key="teams.id", primary_key=True, nullable=False)
```

- `AgentTeamDB` uses the composite-PK join-table pattern (like the convention doc prescribes), no surrogate UUID.
- `team_id` on the **user** lives on `UserDB`, not here (one team per user) — see step 3.

#### `app/teams/schemas.py`

```python
class TeamCreate(BaseModel):
    name: str
    color: str | None = None

class TeamPatch(SQLModel):           # partial update
    name: str | None = None
    color: str | None = None

class TeamResponse(SQLModel):
    id: UUID
    name: str
    color: str | None
    created_at: datetime
    updated_at: datetime
```

#### `app/teams/repository.py`

`TeamRepository(BaseRepository[TeamDB])` — inherits `get/create/update/delete`. Add:

- `list_all() -> list[TeamDB]`
- `get_by_name(name) -> TeamDB | None` (for uniqueness check / create-on-the-fly)

Plus a small `AgentTeamRepository` (or methods on the agents repository — see step 5) for the agent↔team link:

- `set_agent_teams(agent_id, team_ids)` — replace-set semantics, mirroring `AgentRepository.set_permissions` (`app/agents/core/repository.py:90`).
- `team_agent_ids(team_id) -> set[UUID]` — used by resolution if we go the separate-query route (we won't; see step 5).

#### `app/teams/service.py`

`TeamService(BaseService[TeamDB, TeamRepository])`:

- `create(TeamCreate)` — raise `AlreadyExistsError` if name taken (if we enforce uniqueness — see Open Questions).
- `update(team_id, TeamPatch)` — `get_or_404` then repo update.
- `delete(team_id)` — `get_or_404` then delete. Deletion side-effects handled by FK rules (see Open Questions).
- `list()` → `list[TeamResponse]`.

#### `app/teams/router.py`  (`prefix="/teams"`)

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| `GET` | `/teams` | `get_current_user` | list teams (needed by Users-page select, invite dialog, agent perms modal) |
| `POST` | `/teams` | `require_admin` | create team |
| `PATCH` | `/teams/{id}` | `require_admin` | rename / recolor |
| `DELETE` | `/teams/{id}` | `require_admin` | delete |

Register in `app/main.py` alongside the other routers.

### 2. `app/agents/` — assign teams to an agent

This is the agent side of the link (used later by the "Manage permissions" modal, but the model/endpoint belong in the backend foundation now).

- `AgentTeamDB` lives in `app/teams/models.py` (above) to avoid an import cycle, or in `app/agents/models.py` next to `AgentMCPServerDB` / `AgentUserPermissionDB` — **decision: put it in `app/agents/models.py`** since it's conceptually an agent binding and that's where `AgentUserPermissionDB` already lives. (Adjust the import in step 1 accordingly.)
- Repository: add `get_team_ids(agent_id)` and `set_teams(agent_id, team_ids)` to `AgentRepository`, mirroring `get_permissions`/`set_permissions`.
- Service: `AgentService.get_teams(agent_id)` / `set_teams(agent_id, team_ids)`.
- Router: `GET /agents/{id}/teams` and `PUT /agents/{id}/teams` mirroring the existing `GET|PUT /agents/{id}/permissions` (`app/agents/router.py:117`).

### 3. `app/users/` — user's team

- **Model** (`app/users/models.py`): add to `UserBase` (so it flows into create schemas) **or** directly on `UserDB`. Since invites/signup set it server-side, put it on `UserDB`:

  ```python
  team_id: UUID | None = Field(default=None, foreign_key="teams.id", nullable=True)
  ```

- **Schemas** (`app/users/schemas.py`):
  - `UserResponse` gains `team_id: UUID | None`. (Frontend joins against `GET /teams` for name/color — see Open Questions on whether to embed the full team.)
  - New `UserTeamPatch(SQLModel): team_id: UUID | None` (nullable to support un-assigning).
- **Service** (`app/users/service.py`): `update_team(user_id, UserTeamPatch)` — `get_or_404`, validate `team_id` exists if not null, repo update. Mirrors `update_role`.
- **Router** (`app/users/router.py`): `PATCH /users/{id}/team` mirroring `PATCH /users/{id}/role`.
  - ⚠️ **Auth note:** the existing `PATCH /users/{id}` and `PATCH /users/{id}/role` have **no auth dependency** today (only `create`/`delete` require admin). I recommend gating the new `/team` endpoint with `require_admin` (team assignment is an admin action) and, separately, flagging the ungated role endpoint as a pre-existing gap. See Open Questions.

### 4. `app/invites/` — invite with team

- **Model** (`app/invites/models.py`): `InviteDB` gains `team_id: UUID | None = Field(default=None, foreign_key="teams.id", nullable=True)`.
- **Schemas**: `InviteCreate` gains `team_id: UUID | None = None`; `InviteResponse` gains `team_id`.
- **Service** (`app/invites/service.py`): `create()` persists `team_id`.
- **Accept flow** (`app/auth/service.py`): both `accept_invite` (~line 87) and the Google OAuth branch (~line 147) set `team_id=invite.team_id` on the new `UserDB`.

### 5. Permission resolution wiring

- **`AgentRepository.list_with_permissions`** (`app/agents/core/repository.py:20`): when `include_permissions` is true (user set & not admin), accept a `user_team_id: UUID | None` arg and add a second `outerjoin`:

  ```python
  if include_permissions and user_team_id is not None:
      columns.append(AgentTeamDB.team_id.label("team_match"))
      stmt = stmt.outerjoin(
          AgentTeamDB,
          (AgentDB.id == AgentTeamDB.agent_id)
          & (AgentTeamDB.team_id == user_team_id),
      )
  ```

  Filtering the join on the user's single `team_id` guarantees ≤1 matching row per agent → no fan-out.

- **`AgentService._resolve_permission`** gains a `team_granted: bool` param; insert the branch between the explicit-grant lookup and the `None` fallback.
- **`AgentService.list` / `get` / `update`** thread a new `user_team_id` param.
- **All call sites** must pass `current_user.team_id`:
  - `app/agents/router.py` (list/get/update endpoints) — `current_user.team_id`.
  - `app/integrations/slack/commands/chat.py:32` `list_pickable_agents` — pass the resolved internal user's `team_id` (already loads a `UserDB`). The existing `current_user_permission is not None` filter then automatically includes team-granted agents. ✅

### 6. Migrations (Alembic)

One revision (or split if cleaner), `uv run alembic revision --autogenerate -m "add teams"`:

1. `create table teams` (id, name, color, timestamps).
2. `create table agent_teams` (agent_id, team_id composite PK, FKs, timestamps, `uq_agent_team`).
3. `add column users.team_id` (nullable FK → teams.id, `ondelete=SET NULL`).
4. `add column invites.team_id` (nullable FK → teams.id, `ondelete=SET NULL`).

Verify the autogenerated FK `ondelete` rules — autogenerate often omits them; set them explicitly (see Open Questions for the desired semantics).

### 7. Tests (`backend/tests/`)

Mirror the `app/` layout:

- `tests/teams/test_repository.py` — CRUD, `get_by_name`, agent↔team set/replace.
- `tests/teams/test_service.py` — create/duplicate-name, update, delete.
- `tests/teams/test_router.py` — endpoint auth (admin gates), happy paths.
- `tests/agents/` — **resolution cases** (the important ones):
  - user in team linked to agent → `current_user_permission == "member"`.
  - user has explicit `editor` **and** team link → stays `editor` (per-user wins).
  - user in a team **not** linked to the agent → `None`.
  - owner / workspace-admin unaffected.
  - agent listing for a team member surfaces the agent (the Slack/`list` path).
- `tests/users/` — `PATCH /users/{id}/team` assigns & un-assigns; `UserResponse.team_id` present.
- `tests/invites/` + `tests/auth/` — invite with `team_id`; accepting it sets `user.team_id` (password and Google flows).

---

## Frontend (later steps — included for completeness)

### Step A — Users table team select (the requested first UI slice)

`web/src/app/(protected)/users/page.tsx`:

- Add a **Team column** after Role in the grid templates (`page.tsx:245`); widen the `md` grid cols (e.g. `[1fr_230px_130px_160px_34px]`).
- Render a team picker per row mirroring the Role `SageDropdownMenu` (`page.tsx:338`):
  - Items = teams from `GET /teams`, each with a color dot (`style={{ background: team.color }}`) like `ROLE_DOT`.
  - **Empty state** (user has no team): show a muted pill — e.g. a dashed-border chip reading "No team" with a neutral dot — rather than a blank cell. Keep it visually consistent with the Role pill.
  - Footer item **"+ New team"** inside the dropdown → opens the create dialog (step B).
  - `handleTeamChange(userId, teamId | null)` → `api.patch('/users/${userId}/team', { teamId })`, optimistic local update (same shape as `handleRoleChange`, `page.tsx:161`).

### Step B — "New team" dialog

New component mirroring `RenameThreadDialog` (`web/src/components/layout/app-sidebar/rename-thread-dialog.tsx`):

- `Dialog` + `SageInput` for the name.
- Color picker = the swatch grid from `agent-editor.tsx:206` (`AGENT_COLORS.map(...)`).
- Submit → `api.post('/teams', { name, color })`; on success, append to the team list and select it for the current row.
- Props `{ open, onOpenChange, onTeamCreated }`.

### Step C — Invite dialog team select

`web/src/app/(protected)/users/invite-dialog.tsx`: add a team `<select>` after the role select (`invite-dialog.tsx:85`); include `teamId` in the `POST /invites/` payload (`invite-dialog.tsx:38`).

### Step D — Agent "Manage permissions" modal (team grants)

From the agent editor menu, the Manage permissions modal additionally lists **teams** (multi-select) and writes via `PUT /agents/{id}/teams`. Per-user grants and team grants coexist; the UI should note team grants are member-only.

---

## Suggested PR sequencing

1. **PR 1 — Backend foundation** (this step's deliverable): models, migration, `app/teams/` module, `users.team_id` + `/users/{id}/team`, resolution wiring, invite `team_id`, tests. No UI.
2. **PR 2 — Users page**: team select column + empty state + New-team dialog + invite team select (frontend steps A–C).
3. **PR 3 — Agent team permissions**: `PUT /agents/{id}/teams` UI in the Manage permissions modal (step D).

---

## Implementation status — PR 1 (backend foundation) ✅ done

Implemented on `main` working tree:

- `app/teams/` module: `TeamDB` (unique `name` + `color`), `TeamCreate/Patch/Response`, `TeamRepository`, `TeamService` (dup-name → `AlreadyExistsError`), admin-gated CRUD router + open `GET /teams`. Registered in `main.py`.
- `AgentTeamDB` join in `app/agents/models.py` (composite uniqueness, `ondelete=CASCADE`). Repo `get_team_ids` / `set_teams` / `delete_all_teams`; service `get_team_ids` / `set_teams`; `GET|PUT /agents/{id}/teams`.
- Resolution: `_resolve_permission` team branch (`member`, below explicit grant); `list_with_permissions` adds the team `outerjoin` filtered on the user's single `team_id` (no fan-out); `user_team_id` threaded through `get/list/update/restore/delete_permanently` and both Slack call sites.
- `users.team_id` (FK `SET NULL`) + `UserResponse.team_id` + `UserTeamPatch` + `update_team` (validates team) + admin-gated `PATCH /users/{id}/team`; retrofitted `require_admin` onto `PATCH /users/{id}` and `/role`.
- `invites.team_id` (FK `SET NULL`) through `InviteDB/Create/Response/service/router`; both accept flows (password + Google) set `user.team_id`.
- Migration `f3c2b1a09d8e_add_teams` (single head). Offline SQL verified correct. **Live apply not yet run** — local Docker postgres is crash-looping on a host `No space left on device`; apply once disk is freed.
- Tests: `tests/teams/`, `tests/invites/test_service.py`, resolution + binding cases in `tests/agents/core/test_service.py`, `/team` endpoint + admin-gate cases in `tests/users/`. **Full suite: 316 passed.** `ruff check` clean on new code.

## Implementation status — PR 2 (Users page) ✅ done

- **Migration applied** to the dev DB (`alembic current` → `f3c2b1a09d8e (head)`; `teams`, `agent_teams`, `users.team_id`, `invites.team_id` all verified present).
- **Users table team column** (`web/.../users/page.tsx`): new "Team" column after Role (md+; folds out on mobile like Email). Each row has a `SageDropdownMenu` listing teams (color dot + active check), a "No team" entry to unassign, and a "+ New team" footer item. Empty state = dashed-border "No team" pill. Writes via `PATCH /users/{id}/team` with optimistic update. Fetches `GET /teams`.
- **New-team dialog** (`web/.../users/new-team-dialog.tsx`): mirrors `RenameThreadDialog` (Dialog + `SageInput` + `SageButton`) with the `AGENT_COLORS` swatch picker. `POST /teams`; on success the team is added to the list and auto-assigned to the row that opened it.
- **Invite dialog** (`web/.../users/invite-dialog.tsx`): optional Team select; `teamId` sent in the `POST /invites/` payload.
- `tsc` + `eslint` clean on all three files (the one repo-wide tsc error is pre-existing and unrelated).

## Implementation status — PR 3 (agent team grants) ✅ done

- **Manage permissions modal** (`web/.../agents/components/agent-permissions-dialog.tsx`): added a **People / Teams** segmented toggle. The Teams view loads `GET /agents/{id}/teams`, lists all teams (`GET /teams`) as toggleable chips (color dot + check when selected), with the note "Everyone in a selected team gets Member access." Save now PUTs **both** `/permissions` and `/teams` (`{ teamIds }`) in parallel. Per-user and team grants coexist; team grants are member-only by construction.
- No menu change needed — the same modal opens from the agent editor's "Manage permissions" item (owner/admin gated).
- `tsc` + `eslint` clean.

## Decisions (confirmed)

1. **Team deletion semantics** → **SET NULL + cascade.** `users.team_id` is set NULL for members; `agent_teams` rows for the team are deleted. Deletion always succeeds. Implement via FK `ondelete="SET NULL"` (users, invites) and `ondelete="CASCADE"` (agent_teams).
2. **Team name uniqueness** → **unique.** Unique constraint on `teams.name`; `TeamService.create` raises `AlreadyExistsError` on collision.
3. **User-mutation authz** → **gate all + fix the gap.** Add `require_admin` to the new `PATCH /users/{id}/team`, and retrofit `require_admin` onto the existing ungated `PATCH /users/{id}` and `PATCH /users/{id}/role`.
4. **`UserResponse` shape** → **just `team_id`** (UUID only; frontend resolves name/color from `GET /teams`).
5. **`AgentTeamDB` home** → **`app/agents/models.py`**, next to `AgentUserPermissionDB`.
