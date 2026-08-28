# Contributing to auxilia

auxilia is an open-source web MCP client: users and companies host and configure
their own MCP-powered AI assistants. Everything an agent knows comes through MCP
(skills, semantic search, web search), which is what keeps the codebase small
enough to contribute to.

This guide covers the backend. For architecture and conventions in full, read
[`CLAUDE.md`](./CLAUDE.md) — it is the normative document; this file is the
on-ramp.

---

## Getting set up

Requirements: Python 3.11+ with [uv](https://docs.astral.sh/uv/), Node 20+,
Docker (for Postgres and Redis).

```sh
cp .env.example .env
make dev              # postgres + redis + backend + frontend, in parallel
```

Or piecemeal: `make dev-stack` (Docker services), `make dev-backend`
(migrations + uvicorn with reload), `make dev-frontend`.

The backend test suite needs **no** infrastructure — no Postgres, no Redis, no
network. From a cold clone:

```sh
cd backend
uv sync --all-groups
uv run pytest            # ~700 tests in about 5 seconds
```

That property is deliberate and worth protecting: tests use `fakeredis` and
SQLite. If a change of yours would need a real service to test, put that test
behind a marker rather than making the default lane slow or flaky.

## Before you open a PR

```sh
cd backend
uv run ruff format .     # format
uv run ruff check .      # lint
uv run mypy app          # type check
uv run pytest -q         # tests
```

CI (`.github/workflows/backend-ci.yml`) runs exactly these four on any PR
touching `backend/`.

**Commit and PR titles must follow [Conventional Commits](https://www.conventionalcommits.org/).**
PRs are squash-merged, so the **PR title becomes the commit on `main`** and
release-please parses it to build the changelog and bump versions. A
non-conventional title means your change never appears in a release.

```
feat(triggers): scheduled agent runs
fix(agents): don't drop subagent HITL gates
docs: correct the exception table
```

`feat` / `fix` / `perf` / `refactor` / `deps` / `revert` appear in the changelog;
`docs` / `chore` / `test` / `style` / `build` / `ci` are hidden.

## The architecture in one page

A layered modular monolith. One directory per domain concept, and inside it
always the same four layers:

```
router.py      → HTTP surface. Endpoints, auth dependencies, response shape.
                 No DB access, no branching on domain rules.
service.py     → business logic. Owns the request-scoped `db`, raises domain
                 exceptions, delegates all IO to its repository.
repository.py  → SQL. One method per query shape, named for what it returns.
                 Never raises domain exceptions — returns None / [].
models.py      → SQLModel tables.
schemas.py     → request/response DTOs.
```

Read [`app/users/`](./backend/app/users/) first. It is the cleanest module in the
codebase and the one to copy: clean layer separation, escaped `LIKE` search,
deterministic ordering, comments explaining route ordering. When you are unsure
what a new module should look like, make it look like `users/`.

Rules that are easy to get wrong:

- **Never `db.execute(select(...))` in a router or a service.** Lift it into a
  repository method named after what it returns. Some older modules break this
  (`auth/`, `invites/`) — they are on the cleanup list, not the template.
- **Services `flush()`, never `commit()`.** `get_db` runs one transaction per
  request. The two documented exceptions are in CLAUDE.md § Transactions.
- **Never return a `*DB` model from an endpoint.** Project to a `*Response`
  schema so relations and storage-only columns can't leak.
- **Use `BaseService.get_or_404(id)`** instead of hand-rolling the check.
- Domain exceptions (`app/exceptions.py`) are translated centrally in `main.py`.
  Raise them; don't catch them just to re-wrap them.

## Write down why, not what

This is the codebase's most valuable asset, and the standard we hold PRs to.
Nearly every non-obvious decision here states **its reason and its failure
mode**, next to the code:

```python
# DB reads done — release the pooled connection before the probes' network IO
# (token refresh, OAuth metadata discovery can take seconds). expire_on_commit=False
# keeps the loaded rows usable.
await db.commit()
```

Not `# commit the transaction`. If you worked out something subtle — an ordering
constraint, a race, an upstream bug you're routing around — the next contributor
needs the reasoning, not a restatement of the line below. When you deliberately
swallow an exception, say why in the `# noqa: BLE001 — …` comment; the linter
requires the annotation, review requires the reason.

The same goes for tests: several test docstrings name the production incident the
test exists to prevent. That makes the suite a regression ledger rather than a
coverage number.

## Where things live

| I want to… | Look at |
| --- | --- |
| add a CRUD feature | `app/users/` as the template |
| change how agents execute | `app/agents/runtime.py`, `app/agents/toolset.py` |
| touch the durable run runtime | `app/agents/runs/` — **read its `SPEC.md` first** |
| add an MCP transport or auth scheme | `app/mcp/client/` |
| add a scheduled-run feature | `app/triggers/` |
| change a DB table | `alembic revision --autogenerate`, then read the migration |

## Known cleanup in flight

Two documents at the repo root track deliberate technical debt:

- [`backend-design-review.md`](./backend-design-review.md) — a full design review
  with `file:line` evidence, and the phased plan in §9.
- [`backend-cleanup-todo.md`](./backend-cleanup-todo.md) — the live checklist.

If you're looking for a first contribution, the Phase 0 and Phase 3 items there
are scoped to be independent. If you're about to refactor something and find a
`FIXME(P3-…)` marker, that's the task it belongs to.

Two things are decided and not up for relitigation (see §8 "What NOT to do"):
no DDD migration, and no replacing the durable run runtime with a generic queue.
