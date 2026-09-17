# skillkit — Agent Skills from git, inside auxilia

**Status:** implemented 2026-09-17 in `backend/skillkit/` (v0: `LocalSource`,
`ArchiveSource`, `GitHubSource`, `GitLabSource`; the `dulwich` `GitSource`
fallback is not written yet). Written so it can be extracted to its own
package once a second consumer exists. The app consumes it through
`app/skills/bundles.py`, `app/skills/runtime.py` and `app/skills/sources/`.

A small Python library that **resolves, discovers, validates, digests, pins,
diffs and compatibility-checks** [Agent Skills](https://agentskills.io/specification)
from a git repository (GitHub, GitLab, or any host), an archive or a local
directory. It does not load
skills into an agent: deepagents already does that, and this library hands it
files.

---

## 1. What already exists, and what this adds

Three things already implement parts of the draft this supersedes. The library
is defined by the gaps between them, not by re-owning what they do.

| Need | Exists today | Gap |
| --- | --- | --- |
| Parse `SKILL.md` frontmatter, validate `name` (spec rules incl. directory match), cap `description` / `compatibility`, parse `allowed-tools`, `license`, `metadata` | **deepagents 0.7.13** `middleware/skills.py`: `_parse_skill_metadata`, `_validate_skill_name`, `_validate_metadata`, `SkillMetadata` | Private functions; warn-and-continue semantics (a bad name still loads); only reads from a *backend*, one directory level (`<source>/<name>/SKILL.md`) |
| List skills and render the index into the system prompt | **deepagents** `SkillsMiddleware`, `_list_skills`; app subclass `FreshSkillsMiddleware` adds per-run refresh and the `-> Files:` line | None. **Keep using it.** |
| Spec-conformant validation with an executable, a `to_prompt` XML renderer | **skills-ref 0.1.1** (PyPI, Apache-2.0, Python ≥ 3.11, zero deps; maintained under `agentskills/agentskills`). `validate(Path)`, `read_properties(Path)`, `to_prompt(list[Path])`. Rejects *unknown top-level frontmatter keys*. Self-described "for demonstration use" | Works on a filesystem path, not on bytes in memory; no codes, messages only; no bundle/limits/symlink checks |
| Bounded zip import, export, `SkillBundle` model, path rules, 10 MB / 100 files | **app** `app/skills/bundles.py`, `app/skills/schemas.py` | Zip only; no tar; no digest; not reusable outside the app |
| In-memory read-only backend over a set of skills; layout `<root>/<name>/…`; upload to a sandbox with a digest marker | **app** `app/skills/runtime.py` (`SkillsBackend`, `skill_files`, `upload_skills`) | Digest is over the whole set, not per skill |
| Resolve a git ref to a commit, fetch, discover nested layouts, per-skill digest, lockfile, semantic diff, requirements → environment check | — | **This library** |

Rule of thumb: if deepagents or skills-ref does it on data we can give them, call
them. If they only do it on a shape we don't have (a filesystem path, a
backend), do the shape conversion here, not a reimplementation.

## 2. Non-goals

Never in this package: sandbox provisioning or execution; credential storage,
OAuth, GitHub App installation, webhooks; agents, graphs, tool calling, MCP;
authorization (who may enable what); a hosted registry; an authoring UI; the
prompt index (deepagents owns it). Credentials arrive through a provider
interface and are never acquired, refreshed or persisted here.

If a change makes `skillkit` import `app.*`, it belongs in `app/skills/`.

## 3. Layout and dependency rules

```
backend/
├── skillkit/                    # the library (no `app.*` imports, ever)
│   ├── __init__.py              # public API re-exports
│   ├── model.py                 # Skill, Bundle, ResolvedSource, Requirements
│   ├── frontmatter.py           # split + parse; wraps skills-ref where it fits
│   ├── discovery.py             # container walk, shadowing, internal skills
│   ├── data/containers.json     # vendored agent-directory list (see §6)
│   ├── validate.py              # codes E0xx / W0xx over a Bundle
│   ├── digest.py                # per-skill content digest
│   ├── lock.py                  # Lockfile, read/write/equality
│   ├── diff.py                  # SourceDiff, SkillDiff, categories
│   ├── requirements.py          # `auxilia-requires` grammar + EnvironmentManifest + check
│   ├── sources/
│   │   ├── base.py              # SkillSource protocol, CredentialsProvider
│   │   ├── local.py
│   │   ├── archive.py           # zip + tar, bounded extraction
│   │   ├── hosted.py            # HostedSource shape: ref → SHA → tarball
│   │   ├── github.py            # GitHub REST adapter
│   │   ├── gitlab.py            # GitLab REST adapter (any instance URL)
│   │   └── git.py               # dulwich fallback for other hosts
│   ├── adapters/deepagents.py   # bundles → files dict + in-memory backend
│   ├── errors.py
│   └── __main__.py              # thin CLI
└── tests/skillkit/              # offline; fixture repos built at test time
```

- `backend/pyproject.toml` already has `pythonpath = ["."]`, so `import skillkit`
  works for the app and the tests without packaging work.
- Dependencies: `pyyaml`, `httpx`, `packaging` (version specifiers); `dulwich`
  only for the generic `GitSource`. `skills-ref`
  as a runtime dependency **if** its parser works on content strings; otherwise
  the ~60 lines are vendored with attribution (verify at implementation, see
  §7). `deepagents` only from `adapters/`.
- One test asserts the import graph: nothing under `skillkit/` (except
  `adapters/`) imports `app`, `deepagents`, `langchain*` or `sqlalchemy`.

## 4. Concepts

| Term | Meaning |
| --- | --- |
| **Skill** | A directory with `SKILL.md` (frontmatter `name`, `description`, optional `license`, `compatibility`, `metadata`, `allowed-tools`) and any files. `name` must equal the directory name. |
| **Bundle** | The frozen bytes of one skill: `dict[relative posix path, bytes]` plus a **per-skill digest**. Same digest ⇒ interchangeable, cacheable, shareable across agents. |
| **Source** | Something that yields skills: `LocalSource`, `ArchiveSource`, `GitHubSource`, `GitLabSource`, `GitSource`. The app adds a `DatabaseSource` for in-app skills, implementing the same protocol outside the library. |
| **ResolvedSource** | A source at one immutable revision: the revision, the discovered skills (with container and path), and per-skill validation reports. |
| **Lock** | A pin: source → revision, skill → digest and path. Small, diffable, versioned. |
| **Requirements** | What a skill's scripts need from the environment, declared in frontmatter (§8). |
| **EnvironmentManifest** | What an execution image provides: interpreter, packages, install policy, egress. Generated in CI, consumed here. |

## 5. Sources

```python
class CredentialsProvider(Protocol):
    def token(self, host: str) -> str | None: ...

class SkillSource(Protocol):
    def resolve(self) -> ResolvedSource: ...
```

That is the whole protocol. Resolution is the **only** phase that touches the
network. Everything after it is a pure function over bytes.

### Hosted sources — REST, without a git binary

Every major host exposes the same two calls: *resolve a ref to a commit SHA*
and *download an archive of that commit*. `HostedSource` is the shared shape
(resolve → SHA → bounded tarball → `ArchiveSource`); each host is a small
adapter that knows two URLs and one auth header:

| Source | Resolve ref → SHA | Archive | Auth header |
| --- | --- | --- | --- |
| `GitHubSource` | `GET /repos/{owner}/{repo}/commits/{ref}` | `GET /repos/{owner}/{repo}/tarball/{sha}` | `Authorization: Bearer <token>` |
| `GitLabSource` | `GET /api/v4/projects/{id}/repository/commits/{ref}` (`id` = URL-encoded `group/project`) | `GET /api/v4/projects/{id}/repository/archive.tar.gz?sha={sha}` | `PRIVATE-TOKEN: <token>` |

- `ref` may be a tag, a branch or a SHA; the result is always a SHA.
- The instance URL is a parameter, so self-hosted GitLab (and GitHub
  Enterprise) work unchanged. The host *type* is an explicit choice when a
  source is added; only `github.com` and `gitlab.com` are auto-detected.
- Token from the `CredentialsProvider`, keyed by host. Rate limits and
  401 / 404 / 5xx map to `AuthenticationError`, `RevisionNotFound`,
  `SourceUnavailable` (§14).
- `path="skills/"` restricts discovery to a directory of the repo.

Bitbucket and Gitea are the same shape and can be added when someone needs
them; none is in v0.

### `GitSource` — any host, pure Python

For a host without a REST adapter: `dulwich` (pure-Python git) resolves the ref
with `ls-remote` and performs a **shallow fetch of one commit** over smart HTTP
with the same token, then hands the tree to the bundle builder. No `git` binary
needed, which matters because the Cloud Run image may not ship one. Heavier
than the REST path (packfile handling, one more dependency), so it is the
fallback, not the default. `subprocess git` is deliberately not used.

### `ArchiveSource`

Zip and tar(.gz). Bounded: download ≤ 10 MiB, extracted ≤ 25 MiB, ≤ 1000 files
by default, all caller-configurable (the app passes its own 10 MB / 100 files
per skill). Zip-slip, absolute entries and symlinks are rejected, not skipped.

### `LocalSource`

A directory. For tests, the CLI, and local authoring.

## 6. Discovery

Mirrors the Vercel `skills` CLI so a repo that works with `npx skills add` works
here. Rules, with the upstream README as the reference to re-check at
implementation time:

- Containers: the repository root (if it holds `SKILL.md`), `skills/`,
  `skills/.curated/`, `skills/.experimental/`, `skills/.system/`, and the
  agent-specific directories (`.claude/skills/`, `.agents/skills/`, …).
- Each container is walked **up to three levels** to cover flat
  (`skills/<name>/SKILL.md`) and catalog (`skills/<category>/<name>/SKILL.md`)
  layouts. A `SKILL.md` at a shallower level **shadows** anything beneath it.
- `metadata.internal: "true"` hides a skill from default discovery; it remains
  reachable by explicit path (`resolved.get(path=…)`).
- `full_depth=True` widens the walk to any `SKILL.md` in the tree.
- The agent-directory list is **data**, `data/containers.json`, refreshed by a
  scheduled job from upstream, never hand-edited logic.
- Each discovered skill records its `container` (`"skills"`,
  `"skills/.curated"`, …) so the app can implement curation without a
  convention of its own.

deepagents' own walk is one level deep. The adapter (§13) therefore
**flattens**: every skill is mounted at `<root>/<name>/` whatever its path in
the repo. Names are unique per bound set by construction (the app already
enforces this per agent graph).

The compatibility suite (§18) vendors a small upstream-shaped fixture and
asserts identical discovery.

## 7. Validation

A pure function over a `Bundle`. Each issue has a stable code, a severity, a
path and a message, so the app renders its own copy and CI can fail on a
category.

| Code | Severity | Check | Source of truth |
| --- | --- | --- | --- |
| `E001` | error | `SKILL.md` missing / unreadable / > 10 MiB | deepagents limit |
| `E002` | error | Frontmatter missing, not YAML, or not a mapping | spec |
| `E003` | error | `name` missing, > 64 chars, not lowercase alphanumeric + single hyphens, or ≠ directory name | spec; same rule as deepagents `_validate_skill_name` and skills-ref |
| `E004` | error | `description` missing / empty / > 1024 chars | spec (deepagents *truncates*; we refuse) |
| `E005` | error | A path escapes the skill directory, or is `.`/`..`/empty segment | app rule today |
| `E006` | error | Symlink or non-regular file in the bundle | security |
| `E007` | error | Unknown top-level frontmatter key | **skills-ref rejects these**; a repo must pass `skills-ref validate` |
| `E008` | error | `metadata` value that is not a string | spec: `metadata` is string → string; deepagents would `str()` it silently |
| `W001` | warning | Instructions reference a file that is not in the bundle. **With a suggestion**: "referenced as `new-script.py`, found at `scripts/new-script.py`" when a basename matches | the greeting-skill case |
| `W002` | warning | A script appears to reach outside its skill directory (`../`, absolute paths). **Heuristic**, static; the consumer decides whether to escalate | draft |
| `W003` | warning | Duplicate `name` within one source | draft |
| `W004` | warning | `description` shorter than 40 chars, or lacking a "when to use" cue | retrieval quality |
| `W005` | warning | Bundle over the caller's size / file-count limits (errors at the archive layer, warning here for local sources) | app limits |
| `W006` | warning | `compatibility` > 500 chars | spec (deepagents truncates) |
| `W007` | warning | `auxilia-requires` present but unparseable (§8) | this library |

Implementation note: `skills-ref` exposes `validate(Path)`. If its `parser` /
`validator` modules accept content strings, call them for `E002`–`E004`, `E007`,
`E008` and map messages to codes. If they only accept a `Path`, validate from a
temporary directory in the CLI and vendor the rules for the in-memory path.
Either way the **rules are the spec's**, not ours, and the fixture that keeps us
honest is "every skill that passes here passes `skills-ref validate`".

Cross-source name collisions are not validation. The library reports; the app
decides precedence.

## 8. Requirements and the environment manifest

The draft put `metadata: {skillkit: {requires: {…}}}` in frontmatter. That is
**not spec-compliant**: `metadata` is a map of string keys to **string
values**, skills-ref enforces the known-keys list at the top level (so a new
`requires:` key is rejected), and deepagents coerces nested values with `str()`,
producing an unusable string in the model's index. Requirements therefore live
in one string-valued metadata key with a small grammar:

```yaml
---
name: report-builder
description: Builds the weekly revenue report from HubSpot exports. Use when …
compatibility: Requires Python 3.11+ and pandas   # human text, spec field
metadata:
  auxilia-requires: "python>=3.11; pandas>=2.1, openpyxl; egress=none"
---
```

Grammar: `;`-separated clauses. A clause is `python<spec>`, `image<spec>`,
a comma-separated list of PEP 508 package requirements, or `egress=none|allowlist|open`.
Version specifiers are PEP 440, parsed with `packaging`. Unknown clauses →
`W007`, never a hard failure: the skill still loads, the check just cannot
vouch for it. `compatibility` stays human prose and is never parsed.

If the upstream spec later adds a structured field, the key is renamed in one
place and the grammar retired. Proposing it upstream is the right end state.

```yaml
# environment.yaml — generated in CI from the built image, committed with it
version: 1
image: "ghcr.io/acme/agent-runtime:4.2.0"
interpreter: { language: python, version: "3.12.4" }
packages: { pandas: "2.2.1", httpx: "0.27.0" }
runtime_installs: false
egress: none                    # none | allowlist | open
egress_allowlist: []
```

`skill.check(env) -> Verdict(runnable: bool, reasons: list[str])` is a static
comparison and says so: it knows whether declared needs are met, not whether the
script works. A skill with no requirements is `runnable` trivially. Generating
the manifest from an image (Docker introspection) is a separate tool.

## 9. Bundle and digest

`digest = "sha256:" + sha256( for path in sorted(paths): path_nfc + b"\0" + len(content).to_bytes(8) + content )`

- Paths are POSIX, NFC-normalized, relative to the skill directory. `SKILL.md`
  is included like any file.
- File modes and mtimes are **not** part of the digest. Two checkouts of the
  same commit on different filesystems digest the same.
- Symlinks never reach the digest (rejected in `E006`).
- Per skill, so the app can cache and share one skill across agents. A set
  digest, when the sandbox upload marker needs one, is the digest of the sorted
  per-skill digests.

## 10. Lockfile

```json
{
  "version": 1,
  "sources": [
    {
      "type": "github",
      "url": "https://github.com/acme/skills",
      "ref": "main",
      "revision": "9f2c1ab3e5…",
      "resolved_at": "2026-09-17T09:12:04Z",
      "skills": {
        "report-builder": { "digest": "sha256:1a2b…", "path": "skills/report-builder" },
        "kyc-check":      { "digest": "sha256:9d8c…", "path": "skills/.curated/kyc-check" }
      }
    }
  ]
}
```

JSON, stable key order, newline-terminated. `resolved_at` is informational and
excluded from equality. Digests, not contents: small and reviewable.
**Identity is the skill `name`**: a rename is a removal plus an addition; a path
change alone is `unchanged` with `path_changed=True` for display. The format
carries `version` from day one and is migrated, never reinterpreted.

## 11. Diff

The reason for the library. `git diff` is text; a UI and a CI gate need
categories:

| Field | Meaning | Why it is its own flag |
| --- | --- | --- |
| `description_changed` | the retrieval trigger changed | the skill may now fire on different requests; invisible in a text diff |
| `instructions_changed` | `SKILL.md` body changed | behaviour |
| `scripts_changed` | anything under `scripts/` changed | behaviour **and trust** |
| `requirements_changed` | `auxilia-requires` or `compatibility` changed | may become incompatible |
| `references_changed` / `assets_changed` | usually benign | display |
| `path_changed` | moved within the repo | informational |

`SourceDiff.skills` lists `added`, `removed`, `changed`, `unchanged` (by name);
each `SkillDiff` carries per-file added/removed/modified with unified diffs for
text and sizes only for binaries. `lock.diff(resolved)` is offline.

## 12. Public API (illustrative)

```python
from skillkit import GitHubSource, LocalSource, Lockfile, EnvironmentManifest

src = GitHubSource("https://github.com/acme/skills", ref="main", credentials=provider)
resolved = src.resolve()            # network happens here, once
resolved.revision                   # "9f2c1ab…"
for skill in resolved.skills:
    skill.name, skill.description, skill.container, skill.path
    skill.bundle.digest, skill.bundle.files
    skill.validate().ok, skill.validate().issues
    skill.requirements                 # parsed or None
    skill.check(EnvironmentManifest.from_file("environment.yaml"))

lock = Lockfile.from_resolved(resolved, skills=["report-builder"])
lock.write("skills.lock")
changes = Lockfile.read("skills.lock").diff(GitHubSource(...).resolve())
```

Synchronous. Resolution runs at sync time in the app, never inside an agent
run; `await asyncio.to_thread(src.resolve)` is the documented pattern. No async
mirror in v0.

## 13. Adapter: deepagents

`skillkit.adapters.deepagents` is the only module that imports deepagents:

- `skill_files(bundles, root) -> dict[str, bytes]` — the flattened layout
  `<root>/<name>/<file>`, i.e. what `app/skills/runtime.skill_files` does today.
- `InMemorySkillsBackend(files)` — the read-only `StateBackend` subclass that is
  `app/skills/runtime.SkillsBackend` today, moved here.

Stays in the app: `FreshSkillsMiddleware` (per-run index refresh and the
`-> Files:` line), `freeze_run_skills`, `upload_skills`, the graph-wide name
check. Those are product opinions.

Correctness test for the adapter: deleting it breaks nothing in
`tests/skillkit/` outside `tests/skillkit/adapters/`.

## 14. Errors

`SkillkitError` → `SourceError` (`AuthenticationError`, `RevisionNotFound`,
`SourceUnavailable`), `ValidationError`, `LockfileError`, `LimitExceeded`.

The three `SourceError` subclasses are the catalog's "not configured" /
"permanently broken" / "temporarily unavailable" states. They are distinct
types because the app must not tell them apart by matching strings.

## 15. Security constraints

- Bounded extraction (§5); zip-slip, absolute entries, symlinks rejected.
- No network in validation, digest, diff or check. Only `resolve()`.
- The library **never executes skill content**, not to validate, not to infer
  requirements. Requirements are declared.
- Tokens come from the provider and never appear in lockfiles, logs or error
  messages.

## 16. CLI (thin)

`python -m skillkit list|validate|lock|diff|check <source> [--env environment.yaml] [--strict]`.
`validate --strict` and `check` are the intended CI gate for the company skills
repository; they exit non-zero on errors (and on warnings with `--strict`).

## 17. How auxilia consumes it

### One repository for all company skills — yes

Recommended layout, one repo:

```
acme-skills/
├── skills/
│   ├── weekly-brief/SKILL.md
│   ├── margin-audit/{SKILL.md, scripts/…}
│   └── .experimental/…           # discovered, surfaced as a container
├── environment.yaml              # generated in CI from the runtime image
└── .github/workflows/skills.yml  # skillkit validate --strict && check
```

Why one repo works here: the digest and the lock are **per skill**, so one
`main` moving forward does not force anyone to adopt anything; each agent's
pin is a per-skill digest, adopted against a per-skill diff. Categories are
folders (the walk is three levels deep). Split into several repos only when
ownership or access control requires it; the app supports several sources
regardless.

### Sync and adoption

- `skill_sources` table: url, ref, sub-path, credentials reference, last
  revision, last sync state (`ok` / `auth` / `not_found` / `unavailable` from
  §14), last error.
- Sync (manual, scheduled, or webhook; idempotent): resolve → validate →
  upsert one **available version** per skill (name, path, digest, revision,
  frontmatter, validation report, compatibility verdict). Bundles are stored by
  digest (JSONB today; object storage when sizes demand it). **Existing
  bindings are never touched.** A failed sync leaves everything as it was and
  surfaces on the source.
- **Two provenances, two rules, shown in the catalog:**
  in-app skills (`source_id IS NULL`) go live on the next run, because the
  author owns them; sourced skills are **pinned by digest** and adopted
  explicitly against the diff (§11), per skill, per agent or for the whole
  workspace at once. The requirement chip, the `Files` index line and the
  graph-wide name check apply to both.
- `DatabaseSource` in `app/skills/` implements `SkillSource` for in-app skills,
  so the same validate / digest / diff code runs on both.

### Binding is explicit, and that is the point

"Can we bind only the skills that are useful for an agent instead of letting
it guess?" That is what binding already is on `feat/skills`: an agent's index
lists **only the skills enabled on it**, and the model chooses among those by
`description`. Sync makes skills *available*; it enables nothing. Guidance for
the catalog UI: a handful of skills per agent, descriptions that say *when* to
use the skill (`W004` nudges this), and no "enable all". The one place the set
widens is a supervisor graph, whose members share the union of their skills so
a supervisor can hand a script path to a subagent; whether to keep that union
or bind per member is the open question below.

### Extraction map from #321

| Today | Becomes |
| --- | --- |
| `app/skills/bundles.py` (`parse_skill`, `import_archive`, `export_archive`) | `skillkit.frontmatter`, `skillkit.sources.archive`, `skillkit.validate`; the app keeps a thin `parse_skill` that returns its `SkillBundle` |
| `SkillBundle` / `SkillFile` limits | caller-passed limits into `ArchiveSource` and `validate` |
| `runtime.skill_files`, `runtime.SkillsBackend` | `skillkit.adapters.deepagents` |
| set digest in `upload_skills` | digest of sorted per-skill digests |
| `FreshSkillsMiddleware`, `freeze_run_skills`, name check, `script_count` | unchanged, in the app |

## 18. Testing

- Fixture repositories and archives **built at test time** (tempdir + tar/zip
  writers), no checked-in binaries; `GitHubSource` tested against a stub httpx
  transport, never the network.
- Golden files for lockfile and diff output; a format change is visible in review.
- Property tests on the digest: invariant under path order, mtimes and modes;
  sensitive to any byte.
- Adversarial corpus: zip-slip, absolute entries, symlinks, oversized archives,
  invalid YAML, duplicate names, NFC/NFD path pairs, nested `metadata`.
- Compatibility: an upstream-shaped fixture resolves to the same skill set as
  the Vercel CLI's documented rules; every skill that passes our validation
  passes `skills-ref validate`.
- Import-graph test (§3).

## 19. Open questions

1. **Per-member binding in a graph** vs the current shared union. Sharing keeps
   one mount path per skill and the simple name check; per-member is what
   delegation wants. Decide with the capability model, not here.
2. **`skills-ref` as a dependency.** Its README says "for demonstration"; it is
   0.1.1. Depend on it for the rules if its parser takes strings; otherwise
   vendor with attribution and track it.
3. **Upstream a structured requirements field.** Until then `auxilia-requires`
   is a string in `metadata`, which is spec-legal but ours.
4. **Local bundle cache by digest.** Useful, deferred until two call sites
   reimplement it identically.
5. **Which hosts ship in v0.** GitHub and GitLab REST adapters are cheap; the
   `dulwich` `GitSource` is the generic fallback. Bitbucket / Gitea when asked.
6. **Manifest generation** from an image. Separate tool; this library consumes
   the schema only.
