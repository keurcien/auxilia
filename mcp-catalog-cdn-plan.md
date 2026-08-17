# Moving the official MCP server catalog to a CDN file

> **Status: implemented** (2026-07-29). Built as planned, with three decisions worth recording:
> the shared fetch layer *was* extracted (`app/utils/remote_catalog.py`, with `whitelist.py`
> reimplemented on top of it); the bundled snapshot is ordered alphabetically, since file order is
> now display order; and the catalog validator additionally *requires* `supports_dcr` on every
> OAuth entry (a missing flag would silently read as "DCR works").
>
> One step is left to the operator: upload `backend/app/mcp/servers/catalog.yaml` to R2 at
> `mcp/catalog.yaml`. Until then the URL 404s and every deployment serves the bundled snapshot
> (correct, just a wasted round-trip on each cold cache), and **Sync catalog** returns a 400.

Goal: `official_mcp_servers` (a DB table seeded by Alembic migrations) becomes a remote YAML
file behind the R2 CDN, read the same way as the model whitelist
(`backend/app/model_providers/whitelist.py`) — so adding an official server no longer needs a
migration and a release.

## 1. What the catalog is used for today

Current surface is tiny, which is what makes this cheap:

| Piece | File |
| --- | --- |
| Table `official_mcp_servers` (21 rows) | `backend/app/mcp/servers/models.py:51` — `OfficialMCPServerDB` |
| The one query — LEFT JOIN on `url` to compute `is_installed` | `backend/app/mcp/servers/repository.py:151` — `list_official()` |
| The one service method | `backend/app/mcp/servers/service.py:138` — `list_official()` |
| The one endpoint | `GET /mcp-servers/official` — `backend/app/mcp/servers/router.py:52` |
| Response schema | `OfficialMCPServerResponse(MCPServerResponse)` — `schemas.py:50` |
| The one consumer | `web/src/app/(protected)/mcp-servers/components/mcp-server-dialog.tsx` |
| Seed data (5 migrations) | `ee903a5e6aa0` (create + 13 rows), `e33c42c8ef4f` (Slack), `60eb74a86009` (unique url), `f1a2b3c4d5e6` (icons → R2), `b2c3d4e5f6a7` (7 more rows) |

Crucially the catalog is **pure reference data**:

- Nothing joins it at runtime. "Install" copies the fields into a new `mcp_servers` row
  (`selectOfficialServer` prefills the create form); the catalog row is never linked to.
- No agent/run/toolset path reads it — so unlike the model whitelist it can't take chat down,
  and there is no `models`-style per-workspace enablement table to keep in sync.
- `supports_dcr` exists only on the catalog (not on `mcp_servers`) and is read once, in the form,
  to decide whether static OAuth client credentials are required.

So the migration is: drop a table, add a file + a fetch layer, move one join into Python.

## 2. What has to be built

### 2a. `backend/app/mcp/servers/catalog.py` — mirror of `whitelist.py`

Same four-layer read, freshest first: **process memo (60 s) → Redis (`mcp:catalog`, 7-day TTL) →
CDN file (validated all-or-nothing) → `mcp:catalog:last_good` → bundled `catalog.yaml`**, plus a
single-flight lock (`mcp:catalog:lock`) on the refresh path.

```python
class OfficialServer(BaseModel):
    name: str
    url: str
    auth_type: MCPAuthType = MCPAuthType.none
    icon_url: str | None = None
    description: str | None = None
    supports_dcr: bool | None = None   # only meaningful when auth_type == oauth2

class CatalogDocument(BaseModel):
    schema_version: Literal[1]
    servers: list[OfficialServer]      # non-empty; url unique (replaces uq_official_mcp_servers_url)
```

Validation worth having (all-or-nothing, so a bad upload never half-applies):

- `url` must be http(s) and unique — it is the identity key (`is_installed` matches on it).
- `auth_type` must be a real `MCPAuthType` (the DB enum did this for free before).
- `supports_dcr` must be `None` unless `auth_type == oauth2` — today's data follows that rule and
  the frontend's `requiresStaticOAuthCredentials` assumes it.

Public API: `get_catalog()`, `sync_catalog()` (admin force-fetch, raises instead of falling back,
returns the added/removed diff), `bundled_catalog()`.

**Duplication call:** this is the second instance of the exact same pattern (~120 lines of
fetch/validate/store/fallback/sync). Recommend extracting a small generic helper — e.g.
`app/utils/remote_catalog.py` parameterized by `(url, redis_prefix, bundled_path, parse_fn)` —
and reimplementing `whitelist.py` on top of it in the same PR. If you'd rather not touch the model
path, straight-copying is acceptable but the third catalog will hurt.

### 2b. Settings

`MCPServerSettings` (`backend/app/mcp/servers/settings.py`) gains:

```python
mcp_catalog_url: str | None = "https://pub-7a6e8912b3c448b8a8bfa47a0363f7bc.r2.dev/mcp/catalog.yaml"
```

Same opt-out semantics as `MODEL_WHITELIST_URL` (empty ⇒ bundled snapshot only). Note this is a
genuine new capability for self-hosters: a company can point `MCP_CATALOG_URL` at its own file to
publish an internal list of approved MCP servers.

### 2c. Repository / service / schema

- **Delete** `MCPServerRepository.list_official()`; **add** `list_urls() -> set[str]` (cheap
  `select(MCPServerDB.url)`).
- `MCPServerService.list_official()` becomes `get_catalog()` + `list_urls()` + set membership in
  Python. Note it stays on the service (not a pure helper) because `is_installed` needs the DB.
- `OfficialMCPServerResponse` must stop extending `MCPServerResponse`: file entries have no
  `id`, `created_at`, `updated_at`, or `oauth_client_id`. Make it standalone
  (`name/url/auth_type/icon_url/description/supports_dcr/is_installed`).
  Verified safe: the dialog keys the list on `s.name` (line 669) and never reads `id` or the
  timestamps. The alternative — synthesizing a UUID5 from the URL to preserve the shape — buys
  nothing. Frontend change is then one type edit: `OfficialMCPServer` no longer
  `extends MCPServer`.

### 2d. Alembic

One new revision that `DROP TABLE official_mcp_servers`. Two details:

- **Do not drop the `mcp_auth_type` enum type** — `mcp_servers.auth_type` still uses it.
- The downgrade should recreate the table (and ideally re-seed from the bundled YAML) so a
  `downgrade` doesn't leave the older code broken. The 5 historical migrations stay untouched: on a
  fresh DB they create + seed the table and the new one drops it. Slightly silly but correct, and
  cheaper than rewriting history.
- Watch the shared-dev-DB stamping workflow (see the Alembic multi-branch note) before running it.

### 2e. Seeding the CDN file

One-off: dump the current 21 rows to `catalog.yaml` (`name/url/auth_type/icon_url/description/
supports_dcr`), commit it as the bundled snapshot at `backend/app/mcp/servers/catalog.yaml`, and
upload the identical file to R2 at `mcp/catalog.yaml`. Icons already live on the R2 CDN
(`assets/icons/*.png`) so nothing changes there. Keep UTF-8 — some descriptions use a typographic
apostrophe (Atlassian).

### 2f. Sync endpoint + UI

`POST /mcp-servers/catalog/sync` behind `require_admin`, returning `added / removed /
server_count / fetched_at`, mirroring `POST /model-providers/whitelist/sync`. Raise 400 on
fetch/validation failure rather than silently falling back — the admin pressed the button.

For the button, recommend the **MCP servers page header** (that's where the catalog is consumed and
where an admin notices a missing server), reusing the "Sync catalog" pattern from
`web/src/app/(protected)/settings/workspace-models.tsx:219`. Putting it in Settings next to
workspace models is the symmetric alternative if you'd rather keep all catalog controls together.

### 2g. Tests

`backend/tests/mcp/servers/test_catalog.py`, mirroring `tests/model_providers/test_whitelist.py`:
parse a valid doc, reject each bad shape (bad YAML, non-mapping root, wrong `schema_version`,
empty list, duplicate url, unknown `auth_type`, `supports_dcr` on a non-OAuth entry), and assert
the bundled snapshot is valid and still contains the previously seeded urls. There are currently
no tests covering `list_official`, so also worth one service test that `is_installed` flips when a
matching `mcp_servers.url` exists.

## 3. Behaviour changes to accept

- **Propagation is admin-driven, not instant.** With a 7-day Redis TTL, editing the CDN file does
  nothing until an admin hits sync (or the cache expires). Same deal as models — deliberate.
- **URL uniqueness moves from a DB constraint to file validation.** A duplicate url now fails the
  whole file, and the deployment keeps serving `last_good`/bundled instead of half-applying.
- **The catalog is no longer transactional with the DB.** Irrelevant here since nothing
  foreign-keys it, but it does mean a server can vanish from the catalog while an installed
  `mcp_servers` row keeps working — which is exactly today's behaviour anyway (install copies).
- **Zero availability risk.** No run path touches the catalog; the only reader is the "add server"
  dialog, served from Redis.

## 4. Rough size

Small, self-contained PR: 1 new module + 1 YAML + settings line + 3 small edits (repo/service/
schema) + 1 migration + 1 endpoint + 1 TS type edit + sync button + tests. Add the shared
`remote_catalog` extraction and it's still comfortably one PR — call it half a day.

Suggested title: `refactor(mcp): serve the official server catalog from the CDN`
(path-based release-please bump lands on `backend` + `web`).
