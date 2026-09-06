# deepagents 0.7 upgrade (Stage 2) — spike findings

> **Status (2026-09-06): implemented on branch `feat/deepagents-0.7`, uncommitted.**
> Decisions taken as recommended below: base prompt dropped, lean fragments accepted,
> sandbox-scoped `delete` tool accepted (not yet in the sandbox `tools` map), the
> general-purpose subagent kept but without `TodoListMiddleware`, subagent tool budget
> sized from the parent's `recursion_limit`. Result: 1040 passed / 1 skipped, ruff and
> mypy clean, the parity test re-pinned to 0.7.13 with two recorded deviations (todos on
> the main stack, no `DeepAgentState`) and now also comparing tool descriptions and the
> bound graph config. Not done: live QA (sandbox chat, subagent HITL, an Anthropic thread).

**Date**: 2026-09-06. Follows the Stage 2 section of
[`framework-upgrade-assessment.md`](./framework-upgrade-assessment.md). Method: a
throwaway worktree (`spike/deepagents-0.7`, uncommitted) with `deepagents>=0.7.13`,
`uv lock` + `uv sync`, full pytest / ruff / mypy, a side-by-side diff of
`create_deep_agent` 0.5.6 vs 0.7.13 through the existing parity test, and two probes.

## TL;DR

- **The upgrade is small and mostly mechanical.** 1026 tests pass on 0.7.13 out of the
  box; the 13 failures are the parity test (expected — it pins 0.5.6), one plain-path
  prompt test, and one lazy-backend test. mypy adds 8 `override` errors, ruff is clean,
  the MCP client patches still bind on mcp 1.29.1.
- **Almost no glue becomes deletable.** `harness.py` is what *protects* us from 0.7's
  prompt rewrite; the subagent HITL plumbing (`hitl.py`, emitter interrupt swallow,
  namespace resolution) is unchanged in need and passes green. What can go is small:
  the deprecated `BASE_AGENT_PROMPT` import, the `_profile` guard's fourth clause, and
  the "only `execute` raises" special case in `LazySandboxBackend`.
- **One wrong belief to fix, upgrade or not:** `task`-spawned subagents *do* inherit
  the parent's `recursion_limit` (probe below). `SUBAGENT_RECURSION_LIMIT = 25` sizes
  plain-path subagents' tool budget to 12 calls when they actually run under the
  parent's 50.
- **Behaviour changes the owner must accept or pin:** ~4 KB of harness prompt
  fragments and ~5 KB of `task` tool description disappear, `write_file` becomes
  overwrite, and a recursive `delete` tool appears on every sandbox agent.

## What resolves

`uv lock --upgrade-package deepagents ...` (dry run and real, both clean):

| Package | From | To |
| --- | --- | --- |
| deepagents | 0.5.6 | 0.7.13 |
| langchain | 1.3.17 | 1.4.0 |
| langchain-core | 1.6.0 | 1.6.2 |
| langchain-anthropic | 1.6.1 | 1.7.1 |
| langchain-google-genai | 4.3.5 | 4.3.7 |
| langchain-mcp-adapters | 0.3.0 | 0.3.2 |
| mcp | 1.26.0 | 1.29.1 |
| langsmith | 0.8.0 | 0.12.2 |

langgraph / checkpoint / checkpoint-postgres do not move. deepagents 0.7.13 requires
langchain ≥ 1.3.18, so langchain 1.4.0 rides along (Stage 1 verified 1.3.17; 1.4.0 is
one more minor and every test passes on it).

## Test results on 0.7.13

```
13 failed, 1026 passed, 1 skipped
```

| Failure | Why | Fix |
| --- | --- | --- |
| `test_harness_parity.py` (11) | Pins the 0.5.6 bundle; 0.7 drops `TodoListMiddleware` and the base prompt | Re-pin (see "harness" below) |
| `test_runtime_behaviour::test_subagent_wiring_keeps_the_caller_prompt_ahead_of_the_task_block` | Asserts on the ``## `task` (subagent spawner)`` heading; 0.7's `SubAgentMiddleware` default `system_prompt=None` injects no fragment | Assert on middleware order, or pass our own fragment |
| `test_lazy::test_disconnected_awrite_returns_error_result` | 0.7 `BaseSandbox.awrite` runs a `_awrite_preflight` through `aexecute` *before* our `write` guard, and `LazySandboxBackend.execute` raises while disconnected | Make `execute` return `ExecuteResponse(exit_code=1)` while disconnected |

mypy (clean on main) reports 8 new errors, all real signature drift:

- `app/sandbox/lazy.py:114` `glob(path: str = "/")` → protocol now `str | None = None`
- `app/sandbox/lazy.py:119` `grep(...)` → protocol adds keyword-only `max_count: int | None = None`; `FilesystemMiddleware` calls `backend.grep(..., max_count=...)`, so this is a runtime `TypeError` on the first `grep` tool call, not just a type error
- `app/sandbox/cloudrun/backend.py:119`, `app/sandbox/daytona/backend.py:50` — our **lifecycle** `delete(self)` now shadows the protocol's **file** `delete(self, file_path) -> DeleteResult`. Through `LazySandboxBackend` the file tool reaches the inherited `BaseSandbox.delete` (routes via `execute`), so it works today, but the collision is a trap. Rename the lifecycle method (OpenSandbox already uses `kill()`), and update the two providers' `_destroy_backend`.

## What `create_deep_agent` builds now (side by side)

Captured with the parity test's own `describe()` on both assemblers, `openai:gpt-4o`,
one MCP tool, one sandbox tool:

| | ours (`harness.py`, 0.5.6 shape) | `create_deep_agent` 0.7.13 |
| --- | --- | --- |
| Main stack | Todo, Filesystem, SubAgent, Summarization, Patch, *caller*, PromptCaching | Filesystem, SubAgent, Summarization, Patch, *caller*, PromptCaching |
| General-purpose subagent stack | Todo, Filesystem, Summarization, Patch, PromptCaching | Filesystem, Summarization, Patch, PromptCaching |
| System prompt (openai) | 2 280 chars (agent + `BASE_AGENT_PROMPT`) | 20 chars (agent only) |
| System prompt (sonnet-4-6 profile) | 3 737 chars | 1 477 chars (agent + profile suffix) |
| `TodoListMiddleware` fragment | 1 370 chars | absent |
| `FilesystemMiddleware` fragment | **none on both** (0.7 default) | none |
| `SubAgentMiddleware` fragment | **none on both** (0.7 default) | none |
| `task` tool description | 1 419 chars on both (was 6 573 on 0.5.6) | 1 419 chars |
| Filesystem tools | `ls read_file write_file edit_file` **`delete`** `glob grep execute` on both | same |
| `state_schema` | not passed | `DeepAgentState` (`DeltaChannel` messages) |

Two things in that table matter more than the parity failure itself:

1. **The prompt changes on upgrade whatever we do in `harness.py`.** The 0.5.6
   fragments (`FILESYSTEM_SYSTEM_PROMPT` 1 166 chars, `TASK_SYSTEM_PROMPT` 2 140,
   `SUMMARIZATION_SYSTEM_PROMPT` 416, `EXECUTION_SYSTEM_PROMPT` 279) are gone from the
   library, and the middleware defaults to injecting nothing. `harness.py` already
   passes no `system_prompt=` to those middleware, so "ours" lost them too. Keeping
   them means vendoring ~4 KB of 0.5.6 text and passing it as `system_prompt=` /
   `task_description=` / `custom_tool_descriptions=`. Not recommended: upstream's
   position is that the tool schemas carry that information now.
2. **`delete` is auto-exposed on every sandbox agent** because 0.7's `BaseSandbox`
   implements file `delete` (recursive, via `execute`), and `_supports_delete` checks
   `type(backend).delete is not BackendProtocol.delete`. It deletes inside the
   ephemeral sandbox only, and permission rules classify it as a write. Options:
   accept, gate with `interrupt_on={"delete": True}`, or omit it via
   `FilesystemMiddleware(tools=[...])` (the allowlist must include `read_file`).

## Glue inventory: keep / change / remove

| Glue | Verdict | Notes |
| --- | --- | --- |
| `app/agents/harness.py` (explicit bundle) | **Keep** | It is the reason 0.7's rewrite is a *diff* and not a surprise. Re-pin it to 0.7: drop the base prompt (or vendor it), decide the GP subagent's todo, and keep `TodoListMiddleware` on the main stack — the web UI renders the `todos` channel (`conversation-body.tsx`). |
| `from deepagents.graph import BASE_AGENT_PROMPT` | **Remove** | Deprecated in 0.7, gone in 0.9, warns at import. Either drop the base prompt or vendor the text in our repo. |
| `harness._profile` guard | **Shrink** | `general_purpose_subagent` is now a real profile feature (`GeneralPurposeSubagentProfile`); `extra_middleware` is now `materialize_extra_middleware()`; profiles gained `base_system_prompt` (handled inside `_apply_profile_prompt`). Keep the guard for `excluded_tools` / `excluded_middleware` / `extra_middleware`. |
| `HARNESS_CONFIG` | **Change** | Metadata key is now `lc_versions: {"deepagents": _lc_version()}`; `recursion_limit: 9_999` stays if we want sandbox subagents on that budget (see recursion note). |
| `PatchToolCallsMiddleware` duplicate filter in `build_runnable` | **Keep** | Still injected by the harness; langchain still asserts on duplicate names. 0.7's version also patches dangling `invalid_tool_calls` from an aborted turn and rewrites via `REMOVE_ALL_MESSAGES`; it does not overlap `RepairInvalidToolCallsMiddleware`, which repairs *this* turn's calls. |
| `SubAgentMiddleware(backend=StateBackend, ...)` (plain path) | **Change** | Pass an instance. 0.7 stores and never reads `backend` on this class, so the class "works", but the type is `BackendProtocol`. |
| Plain-path `SubAgentMiddleware` position | **Keep** | Only a system-prompt-fragment ordering concern; the fragment is now empty, so the placement is cosmetic — leave it, drop the heading assertion in the test. |
| `RepairInvalidToolCallsMiddleware`, `CurrentDateMiddleware`, `DeferredStructuredOutputMiddleware`, `ToolErrorMiddleware` binding | **Keep** | Nothing upstream replaces them. |
| `app/agents/hitl.py` namespace descent, `emit._is_bubbling_interrupt`, `protocol/service.py` namespace resolution | **Keep** | `task`/`atask` still `ainvoke` the subagent inside the tool under `tools:<task-id>`; the only change is that the parent's config now reaches it through langgraph's ambient config instead of an explicit `configurable` copy. `test_hitl.py`, `test_emit.py` and the protocol tests are green on 0.7.13. |
| `LazySandboxBackend` per-method guards | **Keep, extend** | Probe: guarding only `execute` makes `ls` return a *silent* empty listing and `delete` say "not found", so the explicit guards stay. Add `max_count` to `grep`, `path: str \| None = None` to `glob`, and make `execute` return `ExecuteResponse(output=NOT_CONNECTED_MSG, exit_code=1)` instead of raising — that covers the new `awrite` preflight route and any future `BaseSandbox` helper. Delete the "only `execute` still raises" paragraph. |
| `files_update`, `ls_info`/`glob_info`/`grep_raw` | n/a | We never used them. |
| `_VALUES_DROP` includes `files` (emitter) | **Keep** | 0.7.8 only adds the `files` channel for state backends; harmless. |
| `tests/agents/test_harness_parity.py` | **Re-pin** | Keep it — it is what made this spike a 15-minute diff. `EXPECTED_DEVIATIONS` finally gets entries if we keep todos on the GP subagent or vendor the base prompt. |

## Probe: subagents inherit the parent's `recursion_limit`

`runtime.py` (`SUBAGENT_RECURSION_LIMIT = 25`), `build_agent_middleware`'s docstring,
`test_runtime.py:179`, `backend-harness-parity-finding.md` and
`subagent-hitl-assessment.md:276` all state that `task` does not forward the parent's
`recursion_limit`, so a subagent runs under langgraph's default of 25. A probe
(`recursion_probe.py` in the session scratchpad: `create_agent` parent +
`SubAgentMiddleware` + a `CompiledSubAgent` whose node records its config) shows:

```
deepagents 0.5.6  -> {'recursion_limit': 777, 'configurable_keys': [...]}
deepagents 0.7.13 -> {'recursion_limit': 777, 'configurable_keys': [...]}
```

The tool node runs under the parent's config, and `ensure_config` seeds the
subagent's run from that ambient config, so `recursion_limit` propagates on both
versions. Consequences:

- Plain-path subagents run under `agent_settings.recursion_limit` (50), but their
  `ToolCallLimitMiddleware` is sized `(25 - 1) // 2 = 12`. They stop at half the
  budget they have. `ResolvedAgent.compile` should size from the parent's limit.
- `HARNESS_CONFIG`'s `recursion_limit=9_999` is still what a *sandbox* subagent runs
  under (the bound config wins the merge), so dropping it would cut that budget to
  50, not to 25.
- The comments and the two docs should be corrected with the upgrade PR.

## `DeepAgentState` — do not adopt without rewiring the checkpoint readers

0.7's `create_deep_agent` passes `state_schema=DeepAgentState`, whose `messages`
channel is a `DeltaChannel` (O(N) checkpoint growth instead of O(N²)). Migration of
existing threads is safe (`from_checkpoint` accepts a plain-list blob). But a
`DeltaChannel` writes `messages` into `channel_values` only on snapshot steps (every
50 updates), and we read `checkpoint["channel_values"]["messages"]` raw in six places:
`hitl.py:342`, `protocol/service.py:272-418`, `runtime.py:683`,
`threads/router.py:73`. Every one of them would see stale or missing messages. Adopting
it means moving those readers onto `graph.aget_state(...)`. Worth a separate ticket for
long threads; not part of this upgrade.

## Other behaviour changes to note

- `write_file` is now create-or-overwrite; the old "read first" guard is gone.
- `ls` / `glob` render empty results as `No files found`; `read_file` gutter format
  changed. No code of ours parses them.
- `PatchToolCallsMiddleware.before_agent` now rewrites the history via
  `RemoveMessage(REMOVE_ALL_MESSAGES)`. The emitter ignores `RemoveMessage` writes, and
  0.5.6 already re-wrote the full list, so the wire is unchanged.
- mcp 1.29.1 still opens the standalone GET stream on the `initialized` notification
  (`streamable_http.py:551`) — the wedge risk from the memory notes is unchanged.
- langchain-anthropic 1.7.1: not exercised against a live model in this spike;
  re-check the adaptive-thinking branch in `ChatModelFactory` on a real Opus call.

## Decisions for the owner

1. **Base prompt**: drop `BASE_AGENT_PROMPT` (upstream lean default) or vendor the
   2 257 chars. Recommendation: drop; agent instructions already lead.
2. **Fragments**: accept the loss of the four middleware fragments (~4 KB) and the
   shorter `task` description, or vendor them. Recommendation: accept.
3. **`delete` tool**: accept, HITL-gate, or omit via `FilesystemMiddleware(tools=)`.
   Recommendation: accept (sandbox-scoped), and add it to the sandbox `tools` map so
   workspace editors can disable or gate it like any other tool.
4. **General-purpose subagent**: keep auto-adding it (upstream default) or use this
   moment to drop it for agents that configure no subagents (finding §"Decisions",
   item 1). Either way, drop `TodoListMiddleware` from *its* stack: the UI shows only
   the supervisor's todos.
5. **Subagent tool budget**: size from the parent's `recursion_limit` (bug fix,
   independent of the upgrade).

All of 1–4 change the frozen-per-thread prompt once, which any framework upgrade does.

## Suggested PR shape

1. Bump `deepagents>=0.7.13` (+ the lock moves above).
2. `harness.py`: drop `BASE_AGENT_PROMPT`, `lc_versions` metadata, shrink `_profile`,
   remove todo from the GP stack; decide GP auto-add.
3. `runtime.py`: `StateBackend()`; fix `SUBAGENT_RECURSION_LIMIT` and its docstrings.
4. `sandbox/lazy.py`: `grep(max_count)`, `glob(path=None)`, `execute` returns an error
   response; rename lifecycle `delete` → `kill` in cloudrun/daytona + providers.
5. Re-pin `test_harness_parity.py`; fix the two other tests.
6. Manual QA: one sandbox chat (create sandbox, write/edit/delete, `task`), one
   subagent HITL approve/reject, one Anthropic thread.

## Spike artefacts

Worktree: `/private/tmp/claude-501/-Users-keurcien-Documents-projects-auxilia/e59ee7db-3261-4e9d-bdf7-c9418014928f/scratchpad/wt-da07`
on branch `spike/deepagents-0.7` (no commits; only `pyproject.toml` + `uv.lock` changed).
Remove with `git worktree remove <path> --force && git branch -D spike/deepagents-0.7`.
