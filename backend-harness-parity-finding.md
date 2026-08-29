# P2-2 — `create_agent` + explicit middleware reproduces `create_deep_agent`

Spike finding for [`backend-design-review.md` §1.4](./backend-design-review.md), the
precondition for **P2-3**. Verified against the installed `deepagents` 0.5.6 /
`langchain` 1.3.17.

**Verdict: parity is exact, and it is now executable.** `app/agents/harness.py`
assembles deepagents' bundle by hand; `tests/agents/test_harness_parity.py` builds a
sandbox agent both ways for four model shapes, captures the `create_agent(**kwargs)`
each path would issue, and asserts they match — middleware for middleware, tool for
tool, byte for byte on the system prompt. The file carries an
`EXPECTED_DEVIATIONS: list[str] = []` that the test asserts is empty, so any future
divergence has to be written down rather than discovered.

## What the harness actually is

`create_deep_agent` is `create_agent` plus this, in this order:

| # | Middleware | Notes |
|---|---|---|
| 1 | `TodoListMiddleware` | adds `write_todos` |
| 2 | `FilesystemMiddleware` | adds `ls`, `read_file`, `write_file`, `edit_file`, `glob`, `grep`, `execute` |
| 3 | `SubAgentMiddleware` | adds `task` |
| 4 | `SummarizationMiddleware` | deepagents' variant: evicted history offloaded to the backend, thresholds sized from the model profile |
| 5 | `PatchToolCallsMiddleware` | the one our own copy was being stripped for |
| … | *the caller's middleware* | our parent stack + `ToolErrorMiddleware` land here |
| n | `AnthropicPromptCachingMiddleware` | unconditional; `"ignore"` makes it a no-op off Anthropic |

…then `system_prompt + "\n\n" + BASE_AGENT_PROMPT`, and a `.with_config` binding
`recursion_limit=9_999` plus `ls_integration: deepagents` trace metadata.

Two things that were true in production and visible nowhere at the call site:

- **Every sandbox agent already has a `task` tool.** deepagents auto-adds a
  `general-purpose` subagent whenever the caller supplies none by that name, which we
  never do. So `SubAgentMiddleware` is always present on the sandbox path — with a
  hidden subagent that inherits the parent's full toolset and runs its own todo /
  filesystem / summarization / prompt-caching stack. Agents with no subagents
  configured are not subagent-free.
- **`recursion_limit=9_999` is what a sandbox subagent runs under**, not langgraph's
  default of 25. The `task` tool invokes a `CompiledSubAgent` with a fresh config, so
  the `.with_config` bound at build time is the budget that applies. Dropping it
  would have silently cut it by 400×; `HARNESS_CONFIG` keeps it, and a test pins it.

### The prompt fragment question

The review asked which prompt fragment, if any, we would have to append ourselves.
Answer: **all of it, and we do.** `harness_system_prompt` appends `BASE_AGENT_PROMPT`
verbatim, plus the harness profile's suffix where one is registered. Measured, for a
sandbox agent with one MCP tool:

| Model | System prompt | Middleware prompt fragments |
|---|---|---|
| `openai:gpt-4o` | 2 264 chars (2 251 of them the harness) | 3 903 chars |
| `anthropic:claude-sonnet-4-6` | 3 721 chars | 3 903 chars |

The ~1.5 KB spread is deepagents' built-in *harness profiles*, which are registered
under four exact model specs (`anthropic:claude-sonnet-4-6`, `claude-opus-4-7`,
`claude-haiku-4-5`, and the Codex line) and contribute nothing but a system-prompt
suffix. Nothing falls back to a provider-wide key, so every other model we serve gets
the plain base prompt.

So a sandbox agent carries roughly **6 KB of harness prompt and 9 extra tools** before
its own instructions and MCP tools. That is unchanged by P2-3 — it is just no longer
invisible.

## What P2-3 changed

Nothing on the sandbox path: the parity test is the claim, and it holds. The changes
below are to the *shape* of the code, plus one deliberate prompt-shape normalisation
called out in the last bullet.

- One construction path. `build_runnable` always calls `create_agent`; a sandbox adds
  middleware and tools to the same list instead of dispatching to a second builder.
- The `PatchToolCallsMiddleware` strip-hack is gone as a *workaround* — the filter
  remains, one line, next to the harness that injects the replacement.
- The dual `str` / `SystemMessage` prompt shape is gone: every caller passes the
  instruction string. `create_agent` normalises a `str` to `SystemMessage(content=str)`,
  so the parent's bytes are unchanged. One shape did change — `ResolvedAgent.compile`
  used to wrap a **subagent's** prompt as a single `{"type": "text"}` content block and
  now passes the string; same content, one less shape.
- The plain path is unchanged, including where `SubAgentMiddleware` sits. It goes
  *after* the caller's stack there and *before* it inside the harness, because those
  are the two positions the two assemblers used. The position is load-bearing: a
  middleware's system-prompt fragment lands in list order, so moving it rewrites the
  prompt of every non-sandbox agent that has subagents. Two tests pin it — one on the
  assembled middleware list, one on the prompt the model actually receives.
- Parent and subagent share `build_agent_middleware`. They differ in exactly two
  documented ways, both forced by the subagent having no checkpointer: no approval gate
  and no tool-call patcher, and a tool budget sized to langgraph's default recursion
  limit rather than ours.

## What this now depends on

`app/agents/harness.py` imports four things deepagents does not consider public:
`graph.BASE_AGENT_PROMPT`, `_version.__version__`, and
`profiles.harness.harness_profiles.{_apply_profile_prompt, _harness_profile_for_model}`.
That is the price of reproducing the assembly, and it is guarded twice: the parity test
fails if any of them stops producing what `create_deep_agent` produces, and
`harness._profile` raises if a resolved profile starts using a feature we do not
reproduce (`extra_middleware`, `excluded_tools`, `excluded_middleware`, a
general-purpose-subagent override) rather than silently dropping it.

This is the shape the deepagents 0.7 upgrade wanted: the surface is now three
middleware classes and one prompt constant, all in one file, with a test that says
whether the upgrade changed behaviour.

## Decisions this makes available (none taken)

Now that the stack is one list, each of these is a one-line diff and a product call —
deliberately **not** made as part of a refactor:

1. **Drop the auto-added `general-purpose` subagent** for agents that configure none.
   Removes the `task` tool and its hidden agent; changes behaviour for existing sandbox
   threads.
2. **Decide summarization and prompt caching for all agents**, rather than inheriting
   them for sandbox agents only. Today plain agents have neither — including long
   threads that would benefit from summarization, and Anthropic threads that are paying
   full price for an uncached prefix.
3. **Trim the harness prompt.** ~2.2 KB of "you are a deep agent" guidance goes to
   every sandbox agent ahead of its own instructions.

Anything acted on here changes the frozen-per-thread system prompt, so it wants the
same care as any prompt change (see `prompt-cache-safe-system-prompt`).
