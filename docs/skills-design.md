# Skills: the `feat/skills` implementation

A second implementation of the skills blueprint (`docs/skills-blueprint.md` on
`feat/skills-preview`), written from `main` on 2026-09-09 to compare against
the preview branch. Same feature, same behaviour table, smaller machinery.

## What is the same

- The bundle format and limits: `SKILL.md` with `name` (1–64, lowercase +
  hyphens) and `description` (1–1024), ≤100 files under safe relative paths,
  ≤10 MB, binaries base64. Import accepts a zip with exactly one `SKILL.md`
  (its folder is the root) or a bare `.md`; export writes `<name>/…`.
- Authorization: every workspace user reads and uses every skill; owner or
  workspace admin edits and deletes. Enabling a skill on an agent needs
  `editor` on the agent.
- Disclosure through deepagents' `SkillsMiddleware` (subclassed so the index
  is rebuilt every run) and `read_file`; no custom skill tool. One skill set
  per graph, names unique across a supervisor and its subagents, refused at
  attach time and when a subagent joins, and fatal at run time.
- Eager sandbox per run: the runtime opens (reconnects or creates) the
  thread's sandbox before the graph is built, stamps `threads.sandbox_id`,
  uploads the skill files once per content digest, persists at turn end, and
  tells the model with one host-authored message when a gone sandbox was
  replaced. The lifecycle tools are gone. A provider outage is a typed 409
  (`sandbox_unavailable`) from the run gate and from `is-ready`, and the
  chat replaces the composer with a notice.
- Explicit save with a revision token (409 on a stale one), delete refused
  while enabled anywhere, rename refused while enabled anywhere.
- Every row of the blueprint's "what happens when something is removed"
  table holds.

## What is different, and why

| Topic | Preview | This branch | Why |
| --- | --- | --- | --- |
| Storage | One JSONB `bundle` with `name`, `description`, `instructions`, `content`, `files` | `content` (the document) plus `files` JSONB, and `name` / `description` columns copied out on save | The document is the single source of truth; the two indexed columns serve the library list and the graph-wide name check without parsing. Nothing is stored twice except what a query needs. |
| List endpoint | Returned every file of every skill | `SkillSummary` rows: `json_array_length(files)` counted in SQL, no document, no files | The library never loads a bundle it is not opening (one query, ~10 columns). |
| Frozen set | `runs.skill_snapshot`, keyed by agent id, one copy per run, plus a query for the last interrupted run on resume | `threads.skill_snapshot`: one list of bundles per thread, refreshed by every new turn, reused by a resume | Identical observable behaviour (a resume never swaps skills under a pending tool call) with O(threads) storage instead of O(runs), no cross-run lookup, and no per-agent duplication now that the graph shares one set. The worker commits the stamp before streaming. |
| Sandbox-less agents | `SkillFilesMiddleware` diffed every skill file into the checkpointed `files` channel; `StateBackend` served them | `SkillsBackend`: a read-only in-memory `StateBackend` subclass over the frozen bundles, given to `SkillsMiddleware` and to `FilesystemMiddleware(tools=["ls", "read_file"])` | Nothing in the checkpoint (the preview wrote up to 10 MB of skill files into every thread that used them), nothing on disk, nothing stale in old threads. The index is served from memory on the sandbox path too, so a turn costs no sandbox round trip for it. |
| Attaching | `PUT/DELETE /agents/{id}/skills/{skill_id}`, a checkbox list calling them one by one | `skill_ids` in the agent's `AgentConfig`; the editor's explicit save carries it like MCP servers, sandboxes and subagents | One atomic config save, one dirty baseline, one permission gate. `AgentResponse.skills` carries the selection for the editor. |
| Editor | Composed the frontmatter from inputs; other frontmatter keys were lost on save | The draft *is* the document. `splitSkillMarkdown` gives name / description / body inputs over it and carries every other frontmatter line through; a document it cannot round-trip (folded scalars, nested keys) is edited raw, with the SKILL.md tab always available | `license`, `compatibility`, `metadata`, `allowed-tools` survive a save, and deepagents shows them. No YAML dependency in the browser; the backend stays the authority. |
| Provider "created" messages | `create()` / `connect()` returned `(backend, message)` for the model | Return the backend | The model never sees the lifecycle any more. |
| Invalid sandbox row | Logged, agent ran without code execution | `SandboxUnavailableError` (409 at the gate, failed run in the worker) | Silently running without the sandbox contradicts the "never reaches the model" decision. |

## Shape of the change

Backend: `app/skills/` (models, schemas, bundles, repository, service, router,
runtime, middleware), one migration (`c4d5e6f7a8b9`: `skills`, `agent_skills`,
`threads.sandbox_id`, `threads.skill_snapshot`), `app/sandbox/provider.py`
rewritten around `open_sandbox` / `SandboxGoneError` / `ensure_sandboxes_available`,
`lazy.py` and `tools.py` deleted, `Agent.build(resume=…)` freezing the set and
`Agent._setup` opening the sandbox, harness parity extended to skills.

Frontend: `/skills` library (cards, import), `/skills/new` and `/skills/[id]`
editor (read mode, form or raw document, files panel), a Skills section in
the agent editor's capabilities column, the sidebar entry, host notices in the
chat, and the `sandbox_unavailable` state on both chat pages.

## Verification

- Backend: 1107 tests pass (`tests/skills/` adds 58: parsing and archives,
  service rules on a real SQLite database, the in-memory backend, the sandbox
  upload and digest, freezing on the thread, a sandbox-less agent listing and
  reading a skill through the real graph, the sandbox agent getting the files
  uploaded, the HTTP surface), `ruff` and `mypy` clean.
- Migration: upgrade, `alembic check` (no drift), downgrade and re-upgrade on
  a scratch Postgres database.
- Frontend: `tsc`, the strict pre-commit ESLint config on every touched file,
  63 vitest tests (6 new for the form helpers).
- Not done: a live run against a sandbox provider and a browser pass. The
  shared dev database is stamped on the preview branch's migration lineage
  (`ef67ab89cd01`, with its own `skills` tables), so this branch cannot run
  against it until those are unapplied and the database re-stamped at
  `b7e2f4a9c1d3`.

## Known limits (inherited from the blueprint's decisions)

Sandboxes are never cleaned up; the availability probe runs on every run
creation; the one sandbox per run uses the first bound member's provider; the
host notice is skipped on a resume; the skill list in the system prompt costs
one prompt-cache miss when it changes; edits the model makes inside the
skills root are wiped on the next upload.

## Naming: one noun, a requirement chip

The design canvas explored two vocabularies for the library (App Screens 23a
vs 23c). 23a split skills into two *types* — "playbook" (SKILL.md only) and
"toolkit" (with scripts) — and 23d then needed a page of state transitions to
keep that type honest (confirm when the last script goes, warn when a first
one arrives, badge flips on every agent). 23c keeps one noun, **skill**, and
states the only fact a reader needs at attach time as a chip: `runs anywhere`
or `needs code execution · N scripts`. The branch implements 23c:

- "Skill" is what the open Agent Skills layout, the `SKILL.md` file name, the
  `/skills` URL, deepagents' `SkillsMiddleware` and every other tool call it.
  A second noun would have to be learned, and "toolkit" collides with the
  agent editor's TOOLS section (MCP servers + sandbox).
- The distinction is *derived* from the files (anything under `scripts/`) and
  flips when a file is added or removed. A derived property shown as a chip
  updates itself; the same property promoted to a type needs the 23d cascade.
- It has a gap: a skill whose only supporting files are references is neither
  a playbook nor a toolkit. The chip has no gap.

"Playbook" survives as the plain word for the markdown-only shape in copy —
the New menu's "Write a skill — a step-by-step playbook any agent can
follow" — not as a badge, a nav item or an API field. The chip is one
component (`skill-requirement-chip.tsx`); swapping in typed badges later is a
local change.

The 23d rule is kept where it costs nothing: attaching is always allowed and
the row shows `scripts inactive — this agent doesn't run code` (grey in read
mode, amber with "Turn on code execution" in edit mode); removing the sandbox
while enabled skills have scripts asks first and leaves them enabled; a
skill in use cannot be deleted, and the guard links to each agent.
