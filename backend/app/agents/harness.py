"""deepagents' harness bundle, assembled explicitly.

``create_deep_agent`` is ``create_agent`` plus a fixed middleware bundle
(``deepagents/graph.py``). Calling it gave the runtime a second construction
path with its own prompt assembly, its own middleware order, and a
``PatchToolCallsMiddleware`` strip-hack to work around the copy it injects —
so middleware added to the parent stack behaved differently depending on
whether the agent happened to have a sandbox bound (design review §1.4).

This module composes the same bundle by hand, so ``build_runnable`` has one
path and the stack is one diffable list. It reproduces deepagents 0.7 for the
one call shape the runtime uses (a pre-built model, skills, no memory/
permissions, `interrupt_on` handled by our own HITL middleware);
``tests/agents/test_harness_parity.py`` builds a graph both ways and asserts
the resulting ``create_agent(...)`` calls match, middleware for middleware.
The deviations we take on purpose are listed in that file's
``EXPECTED_DEVIATIONS`` and are exactly these:

- **``TodoListMiddleware`` stays on the main stack.** deepagents 0.7 dropped
  it from the default bundle; the web client renders the ``todos`` channel,
  so the parent keeps it. The general-purpose subagent does not — its todos
  are never shown.
- **No ``DeepAgentState``.** 0.7 compiles with a ``DeltaChannel`` on
  ``messages`` (O(N) checkpoint growth). That channel only materialises
  ``messages`` in ``channel_values`` on snapshot steps, and the runtime reads
  that key raw off checkpoint tuples in several places (``hitl.py``,
  ``protocol/service.py``, ``read_run_result``, the thread read endpoint).
  Adopting it means moving those readers onto ``aget_state`` first.

Two consequences of the reproduction are worth knowing, because neither is
visible at the call site:

- **Every sandbox agent gets a `task` tool.** deepagents auto-adds a
  `general-purpose` subagent whenever the caller supplies none named that
  (and the harness profile does not disable it), so `SubAgentMiddleware` is
  always present on this path — with its own filesystem / summarization stack
  and a copy of the parent's tools.
- **Summarization and Anthropic prompt caching are on**, for sandbox agents
  only. Plain agents get neither. That fork is inherited, not chosen; making
  it explicit here is the point.
"""

from typing import Any

from deepagents._version import _lc_version
from deepagents.middleware._prompt_caching import append_prompt_caching_middleware
from deepagents.middleware.filesystem import FilesystemMiddleware
from deepagents.middleware.patch_tool_calls import PatchToolCallsMiddleware
from deepagents.middleware.subagents import (
    GENERAL_PURPOSE_SUBAGENT,
    SubAgentMiddleware,
)
from deepagents.middleware.summarization import create_summarization_middleware
from deepagents.profiles.harness.harness_profiles import (
    GeneralPurposeSubagentProfile,
    HarnessProfile,
    _apply_profile_prompt,
    _harness_profile_for_model,
)
from langchain.agents.middleware import TodoListMiddleware
from langchain_core.messages import SystemMessage

from app.skills.middleware import FreshSkillsMiddleware


# `create_deep_agent` binds this onto the compiled graph. A subagent invoked by
# the `task` tool inherits the parent's run config, and a bound config wins
# the merge — so on the sandbox path 9_999 is what a *subagent* actually runs
# under (its ToolCallLimitMiddleware is the real budget). The metadata is what
# marks deepagents runs in LangSmith/Langfuse traces.
HARNESS_CONFIG: dict[str, Any] = {
    "recursion_limit": 9_999,
    "metadata": {
        "ls_integration": "deepagents",
        "lc_versions": {"deepagents": _lc_version()},
        "lc_agent_name": None,
    },
}


def _profile(model) -> HarnessProfile:
    """The harness profile deepagents would resolve for this model.

    Built-in profiles cover a few Anthropic model specs, the Codex line and
    Nemotron, and contribute prompt text plus, for some, a general-purpose
    subagent override — both reproduced here. The remaining profile features
    are not, so refuse to build a stack we would silently be assembling wrong.
    """
    profile = _harness_profile_for_model(model, None)
    unsupported = {
        "extra_middleware": profile.extra_middleware,
        "excluded_tools": profile.excluded_tools,
        "excluded_middleware": profile.excluded_middleware,
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


def _base_harness_stack(model, backend, profile: HarnessProfile, skills=None) -> list:
    """The middleware every deepagents stack starts with — main agent and the
    auto-added general-purpose subagent alike, minus the subagent wiring.

    ``skills`` (``SkillsMiddleware`` sources) lands where deepagents puts it on
    a subagent: after the patcher."""
    stack = [
        FilesystemMiddleware(
            backend=backend,
            custom_tool_descriptions=profile.tool_description_overrides,
        ),
        create_summarization_middleware(model, backend),
        PatchToolCallsMiddleware(),
    ]
    if skills is not None:
        stack.append(FreshSkillsMiddleware(backend=backend, sources=skills))
    return stack


def _general_purpose_subagent(
    model, tools: list, backend, profile: HarnessProfile, skills=None
) -> dict | None:
    """deepagents' default subagent: the parent's tools, its own harness stack.

    Inserted whenever the caller supplies no subagent named `general-purpose`,
    which the runtime never does — so on the sandbox path this is always here,
    and is the reason a sandbox agent always has a `task` tool. A harness
    profile can disable it (`GeneralPurposeSubagentProfile(enabled=False)`)
    or override its description and prompt; none of the built-in ones do.
    """
    gp_profile = profile.general_purpose_subagent or GeneralPurposeSubagentProfile()
    if gp_profile.enabled is False:
        return None
    middleware = _base_harness_stack(model, backend, profile, skills)
    append_prompt_caching_middleware(middleware)
    spec: dict = {
        **GENERAL_PURPOSE_SUBAGENT,
        "model": model,
        "tools": tools,
        "middleware": middleware,
    }
    if gp_profile.description is not None:
        spec["description"] = gp_profile.description
    if gp_profile.system_prompt is not None:
        # A GP-specific prompt beats the profile's base prompt; only the
        # profile suffix layers on top.
        prompt = gp_profile.system_prompt
        if profile.system_prompt_suffix is not None:
            prompt = prompt + "\n\n" + profile.system_prompt_suffix
        spec["system_prompt"] = prompt
    else:
        spec["system_prompt"] = _apply_profile_prompt(
            profile, GENERAL_PURPOSE_SUBAGENT["system_prompt"]
        )
    return spec


def harness_middleware(
    *, model, tools: list, backend, subagents=None, skills=None
) -> list:
    """The harness middleware that runs *before* the caller's own stack.

    Order matters and mirrors deepagents exactly: skills (when the agent has
    any), filesystem, the task tool, summarization, then the patcher — with
    our own `TodoListMiddleware` in front (see the module docstring). The
    general-purpose subagent inherits the parent's full toolset and, as in
    deepagents, the parent's skills.
    """
    profile = _profile(model)
    supplied = list(subagents or [])
    # deepagents adds its default subagent only when the caller supplies none by
    # that name — an explicit spec is how a caller overrides it.
    if any(s["name"] == GENERAL_PURPOSE_SUBAGENT["name"] for s in supplied):
        specs = supplied
    else:
        default = _general_purpose_subagent(model, tools, backend, profile, skills)
        specs = [default, *supplied] if default is not None else supplied
    middleware: list = [TodoListMiddleware()]
    if skills is not None:
        middleware.append(FreshSkillsMiddleware(backend=backend, sources=skills))
    middleware.append(
        FilesystemMiddleware(
            backend=backend,
            custom_tool_descriptions=profile.tool_description_overrides,
        )
    )
    if specs:
        middleware.append(
            SubAgentMiddleware(
                backend=backend,
                subagents=specs,
                task_description=profile.tool_description_overrides.get("task"),
            )
        )
    middleware += [
        create_summarization_middleware(model, backend),
        PatchToolCallsMiddleware(),
    ]
    return middleware


def harness_trailing_middleware(model) -> list:
    """The harness middleware that runs *after* the caller's own stack.

    Prompt caching is unconditional in deepagents; Anthropic's is a no-op on
    other providers, and the Bedrock / Fireworks variants are only appended
    when their packages are installed (they are not).
    """
    _profile(model)  # same guard, so a bad profile fails on either entry point
    middleware: list = []
    append_prompt_caching_middleware(middleware)
    return middleware


def harness_system_prompt(model, system_prompt: str | SystemMessage | None):
    """The agent's instructions with the harness profile's prompt appended.

    deepagents 0.7 ships no authored base prompt: the only text the harness
    adds is the profile's (a suffix for a few Anthropic models, nothing for
    everyone else). Caller instructions always come first (deepagents'
    invariant), so an agent's own prompt still outranks the harness guidance.
    """
    profile = _profile(model)
    base_prompt = _apply_profile_prompt(profile, "")
    if system_prompt is None:
        return base_prompt
    if not base_prompt:
        return system_prompt
    if isinstance(system_prompt, SystemMessage):
        return SystemMessage(
            content_blocks=[
                *system_prompt.content_blocks,
                {"type": "text", "text": f"\n\n{base_prompt}"},
            ]
        )
    return system_prompt + "\n\n" + base_prompt
