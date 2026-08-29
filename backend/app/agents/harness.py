"""deepagents' harness bundle, assembled explicitly.

``create_deep_agent`` is ``create_agent`` plus a fixed middleware bundle
(``deepagents/graph.py``). Calling it gave the runtime a second construction
path with its own prompt assembly, its own middleware order, and a
``PatchToolCallsMiddleware`` strip-hack to work around the copy it injects —
so middleware added to the parent stack behaved differently depending on
whether the agent happened to have a sandbox bound (design review §1.4).

This module composes the same bundle by hand, so ``build_runnable`` has one
path and the stack is one diffable list. Everything here is a faithful
reproduction of deepagents 0.5.6 for the one call shape the runtime uses (a
pre-built model, no skills/memory/permissions, `interrupt_on` handled by our
own HITL middleware), **not** a redesign: ``tests/agents/test_harness_parity.py``
builds a graph both ways and asserts the resulting ``create_agent(...)`` calls
match, middleware for middleware. Deliberate deviations belong in
``build_runnable``, one commented line at a time — not here.

Two consequences of that reproduction are worth knowing, because neither is
visible at the call site today:

- **Every sandbox agent gets a `task` tool.** deepagents auto-adds a
  `general-purpose` subagent whenever the caller supplies none named that, so
  `SubAgentMiddleware` is always present on this path — with its own todo /
  filesystem / summarization stack and a copy of the parent's tools.
- **Summarization and Anthropic prompt caching are on**, for sandbox agents
  only. Plain agents get neither. That fork is inherited, not chosen; making
  it explicit here is the point.
"""

from typing import Any

from deepagents._version import __version__ as _deepagents_version
from deepagents.graph import BASE_AGENT_PROMPT
from deepagents.middleware.filesystem import FilesystemMiddleware
from deepagents.middleware.patch_tool_calls import PatchToolCallsMiddleware
from deepagents.middleware.subagents import (
    GENERAL_PURPOSE_SUBAGENT,
    SubAgentMiddleware,
)
from deepagents.middleware.summarization import create_summarization_middleware
from deepagents.profiles.harness.harness_profiles import (
    HarnessProfile,
    _apply_profile_prompt,
    _harness_profile_for_model,
)
from langchain.agents.middleware import TodoListMiddleware
from langchain_anthropic.middleware import AnthropicPromptCachingMiddleware
from langchain_core.messages import SystemMessage


# `create_deep_agent` binds this onto the compiled graph. The parent overrides
# `recursion_limit` from its own run config, but a *subagent* compiled on the
# sandbox path is invoked by the `task` tool with a fresh config, so 9_999 is
# what it actually runs under (its ToolCallLimitMiddleware is the real budget).
# The metadata is what marks deepagents runs in LangSmith/Langfuse traces.
HARNESS_CONFIG: dict[str, Any] = {
    "recursion_limit": 9_999,
    "metadata": {
        "ls_integration": "deepagents",
        "versions": {"deepagents": _deepagents_version},
        "lc_agent_name": None,
    },
}


def _profile(model) -> HarnessProfile:
    """The harness profile deepagents would resolve for this model.

    Built-in profiles cover three Anthropic model specs and the Codex line,
    and all of them contribute nothing but a system-prompt suffix. The other
    profile features exist, though, and a deepagents upgrade could start using
    them — so refuse to build a stack we would silently be assembling wrong.
    """
    profile = _harness_profile_for_model(model, None)
    unsupported = {
        "extra_middleware": profile.extra_middleware,
        "excluded_tools": profile.excluded_tools,
        "excluded_middleware": profile.excluded_middleware,
        "general_purpose_subagent": profile.general_purpose_subagent,
    }
    used = sorted(name for name, value in unsupported.items() if value)
    if used:
        msg = (
            f"deepagents harness profile for {type(model).__name__} uses "
            f"{used}, which app/agents/harness.py does not reproduce. "
            "Port the missing branch from deepagents.graph.create_deep_agent "
            "(and extend tests/agents/test_harness_parity.py)."
        )
        raise RuntimeError(msg)
    return profile


def _base_harness_stack(model, backend, profile: HarnessProfile) -> list:
    """The middleware every deepagents stack starts with — main agent and the
    auto-added general-purpose subagent alike, minus the subagent wiring."""
    return [
        TodoListMiddleware(),
        FilesystemMiddleware(
            backend=backend,
            custom_tool_descriptions=profile.tool_description_overrides,
        ),
        create_summarization_middleware(model, backend),
        PatchToolCallsMiddleware(),
    ]


def _general_purpose_subagent(model, tools: list, backend, profile: HarnessProfile):
    """deepagents' default subagent: the parent's tools, its own harness stack.

    Inserted whenever the caller supplies no subagent named `general-purpose`,
    which the runtime never does — so on the sandbox path this is always here,
    and is the reason a sandbox agent always has a `task` tool.
    """
    return {
        **GENERAL_PURPOSE_SUBAGENT,
        "model": model,
        "tools": tools,
        "middleware": [
            *_base_harness_stack(model, backend, profile),
            AnthropicPromptCachingMiddleware(unsupported_model_behavior="ignore"),
        ],
        "system_prompt": _apply_profile_prompt(
            profile, GENERAL_PURPOSE_SUBAGENT["system_prompt"]
        ),
    }


def harness_middleware(*, model, tools: list, backend, subagents=None) -> list:
    """The harness middleware that runs *before* the caller's own stack.

    Order matters and mirrors deepagents exactly: todos, filesystem, the task
    tool, summarization, then the patcher. ``tools`` must already include the
    sandbox lifecycle tools — the general-purpose subagent inherits the
    parent's full toolset.
    """
    profile = _profile(model)
    supplied = list(subagents or [])
    # deepagents adds its default subagent only when the caller supplies none by
    # that name — an explicit spec is how a caller overrides it.
    specs = (
        supplied
        if any(s["name"] == GENERAL_PURPOSE_SUBAGENT["name"] for s in supplied)
        else [_general_purpose_subagent(model, tools, backend, profile), *supplied]
    )
    return [
        TodoListMiddleware(),
        FilesystemMiddleware(
            backend=backend,
            custom_tool_descriptions=profile.tool_description_overrides,
        ),
        SubAgentMiddleware(
            backend=backend,
            subagents=specs,
            task_description=profile.tool_description_overrides.get("task"),
        ),
        create_summarization_middleware(model, backend),
        PatchToolCallsMiddleware(),
    ]


def harness_trailing_middleware(model) -> list:
    """The harness middleware that runs *after* the caller's own stack.

    Prompt caching is unconditional in deepagents; `"ignore"` makes it a no-op
    on non-Anthropic models.
    """
    _profile(model)  # same guard, so a bad profile fails on either entry point
    return [AnthropicPromptCachingMiddleware(unsupported_model_behavior="ignore")]


def harness_system_prompt(model, system_prompt: str | SystemMessage | None):
    """The agent's instructions with deepagents' harness prompt appended.

    Caller instructions always come first (deepagents' invariant), so an
    agent's own prompt still outranks the harness guidance.
    """
    profile = _profile(model)
    base_prompt = _apply_profile_prompt(profile, BASE_AGENT_PROMPT)
    if system_prompt is None:
        return base_prompt
    if isinstance(system_prompt, SystemMessage):
        return SystemMessage(
            content_blocks=[
                *system_prompt.content_blocks,
                {"type": "text", "text": f"\n\n{base_prompt}"},
            ]
        )
    return system_prompt + "\n\n" + base_prompt
