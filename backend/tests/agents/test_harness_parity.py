"""`build_runnable` must build what `create_deep_agent` builds.

The runtime used to have two construction paths: plain agents through
`create_agent`, sandbox agents through `create_deep_agent`. P2-3 collapsed
them onto `create_agent` by assembling deepagents' middleware bundle
explicitly (`app/agents/harness.py`) — which is only safe if the explicit
assembly is a faithful reproduction. That is what these tests check: both
paths are built for the same inputs, the `create_agent(**kwargs)` each one
would issue is captured, and the two are compared middleware for middleware,
tool for tool, byte for byte on the prompt and on every tool description.

Deliberate deviations are listed in `EXPECTED_DEVIATIONS` with a reason, and
`comparable()` is where each one is asserted and then factored out of the
comparison. Anything not on that list has to match exactly, so a deepagents
upgrade that changes the bundle fails here first, and the decision to follow
it or not gets written down in this file.
"""

from datetime import UTC, datetime
from unittest.mock import patch

import deepagents.graph as deepagents_graph
import pytest
from deepagents.graph import DeepAgentState
from deepagents.middleware.patch_tool_calls import PatchToolCallsMiddleware
from deepagents.middleware.subagents import CompiledSubAgent, SubAgentMiddleware
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import SystemMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI

from app.agents.current_date import CurrentDateMiddleware
from app.agents.harness import HARNESS_CONFIG
from app.agents.runtime import build_runnable
from app.agents.structured_output import (
    FORMAT_TOOL,
    DeferredStructuredOutputMiddleware,
)
from app.agents.tool_errors import ToolErrorMiddleware
from app.sandbox.lazy import LazySandboxBackend
from tests.agents.scripted_model import ScriptedChatModel


EXPECTED_DEVIATIONS: list[str] = [
    "TodoListMiddleware leads the main stack: deepagents 0.7 dropped it from "
    "the default bundle, but the web client renders the `todos` channel.",
    "No DeepAgentState: its DeltaChannel only materialises `messages` in "
    "channel_values on snapshot steps, and hitl.py / protocol/service.py / "
    "read_run_result / the thread read endpoint read that key raw.",
]
"""Differences we accept between the two assemblies. Each is asserted in
`comparable()`; add an entry there when you add one here."""


@tool
def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b


@tool
def create_sandbox(timeout_minutes: int = 30) -> str:
    """Stand-in for the sandbox lifecycle tools."""
    return "ok"


TOOLS = [add]
SANDBOX_TOOLS = [create_sandbox]


MODELS = {
    # A pre-built instance with no resolvable provider: the empty-profile path.
    "scripted": lambda: ScriptedChatModel(script=[]),
    # Resolves to a built-in harness profile, so the prompt grows a suffix.
    "anthropic-profiled": lambda: ChatAnthropic(
        model_name="claude-sonnet-4-6", api_key="test"
    ),
    # An Anthropic model with no registered profile.
    "anthropic-unprofiled": lambda: ChatAnthropic(
        model_name="claude-3-5-sonnet-20241022", api_key="test"
    ),
    "openai": lambda: ChatOpenAI(model="gpt-4o", api_key="test"),
}


class _Sentinel:
    """Stands in for the compiled graph so nothing is actually built."""

    config: dict | None = None

    def with_config(self, config):
        self.config = config
        return self


def _capture(target: str):
    """Patch `create_agent` at `target` and record the kwargs it was called with.

    The graph config bound afterwards with `.with_config` lands in
    `seen["config"]` once the assembler returns.
    """
    seen: dict = {}
    graph = _Sentinel()

    def fake_create_agent(model=None, **kwargs):
        seen["model"] = model
        seen.update(kwargs)
        return graph

    class _patcher:
        def __enter__(self):
            self._p = patch(target, fake_create_agent)
            self._p.__enter__()

        def __exit__(self, *exc):
            self._p.__exit__(*exc)
            seen["config"] = graph.config

    return seen, _patcher()


def via_deep_agent(model, **kwargs):
    """What `create_deep_agent` would have handed to `create_agent`."""
    seen, patcher = _capture("deepagents.graph.create_agent")
    with patcher:
        deepagents_graph.create_deep_agent(model=model, checkpointer=None, **kwargs)
    return seen


def via_build_runnable(model, **kwargs):
    """What `build_runnable` hands to `create_agent` for the same inputs."""
    seen, patcher = _capture("app.agents.runtime.create_agent")
    with (
        patcher,
        patch("app.sandbox.tools.create_sandbox_tools", return_value=SANDBOX_TOOLS),
    ):
        build_runnable(model=model, sandbox_provider=None, **kwargs)
    return seen


def describe(seen: dict) -> dict:
    """A comparable projection of one `create_agent(**kwargs)` call.

    Middleware instances are not comparable by identity or equality, so each
    is reduced to what actually reaches the model: its class, its registered
    name, the tools it injects (name and description), and any system-prompt
    fragment it contributes.
    """
    return {
        "model": seen["model"],
        "tools": [t.name for t in seen["tools"]],
        "system_prompt": _prompt_text(seen["system_prompt"]),
        "response_format": seen["response_format"],
        "state_schema": seen.get("state_schema"),
        "middleware": [_describe_middleware(m) for m in seen["middleware"]],
    }


def _describe_middleware(m) -> dict:
    described = {
        "class": type(m).__name__,
        "name": m.name,
        "tools": [t.name for t in getattr(m, "tools", [])],
        "tool_descriptions": {t.name: t.description for t in getattr(m, "tools", [])},
        "system_prompt": getattr(m, "system_prompt", None),
    }
    if isinstance(m, SubAgentMiddleware):
        # Recurse, or the auto-added general-purpose subagent goes uncompared:
        # its own filesystem / summarization / prompt-caching stack and its
        # profile-suffixed prompt are all invisible from the outside, and
        # dropping any of them would diverge from `create_deep_agent` silently.
        described["subagents"] = [_describe_subagent(s) for s in m._subagents]
    return described


def _describe_subagent(spec) -> dict:
    """A subagent spec as the harness handed it over.

    A `CompiledSubAgent` is opaque by design — it carries a built runnable, and
    the point of the caller-supplied ones is that we do not rebuild them here.
    A declarative spec (which is what the general-purpose subagent is) still
    carries its whole stack, so that is what gets compared.
    """
    described = {
        "name": spec["name"],
        "description": spec["description"],
        "compiled": "runnable" in spec,
    }
    if "runnable" not in spec:
        described |= {
            "system_prompt": spec["system_prompt"],
            "tools": [t.name for t in spec.get("tools") or []],
            "middleware": [_describe_middleware(m) for m in spec["middleware"]],
        }
    return described


def _prompt_text(prompt) -> str:
    if prompt is None or isinstance(prompt, str):
        return prompt or ""
    return "".join(
        block["text"] for block in prompt.content_blocks if block.get("type") == "text"
    )


def comparable(ours: dict, deep: dict) -> tuple[dict, dict]:
    """Assert each expected deviation, then return both projections without it.

    Everything left has to match exactly.
    """
    assert len(EXPECTED_DEVIATIONS) == 2
    # Shallow copies: the projections hold the model instance, which does not
    # deepcopy (its HTTP client carries a lock), and nothing below mutates deeper.
    ours = {**ours, "middleware": list(ours["middleware"])}
    deep = {**deep, "middleware": list(deep["middleware"])}

    # 1. TodoListMiddleware leads our main stack and is absent from deepagents'.
    assert ours["middleware"][0]["class"] == "TodoListMiddleware"
    assert ours["middleware"][0]["tools"] == ["write_todos"]
    assert all(m["class"] != "TodoListMiddleware" for m in deep["middleware"])
    del ours["middleware"][0]

    # 2. deepagents compiles with DeepAgentState; we keep create_agent's default.
    assert deep["state_schema"] is DeepAgentState
    assert ours["state_schema"] is None
    del ours["state_schema"], deep["state_schema"]

    return ours, deep


def _both(
    model,
    *,
    base_middleware=(),
    subagents=None,
    instructions="You are a test agent",
    output_schema=None,
) -> tuple[dict, dict]:
    """Build both ways from one set of inputs and project each for comparison.

    The `create_deep_agent` side reproduces the *old call site*, not just the
    old function: it appended the sandbox tools, dropped its own
    `PatchToolCallsMiddleware` (deepagents injects one and langchain asserts on
    duplicates), appended the deferred-formatting middleware when a schema was
    given, and put `ToolErrorMiddleware` last. That call site is the behaviour
    P2-3 had to preserve.
    """
    backend = LazySandboxBackend()
    deep_middleware = [
        m for m in base_middleware if not isinstance(m, PatchToolCallsMiddleware)
    ]
    if output_schema is not None:
        deep_middleware.append(DeferredStructuredOutputMiddleware(FORMAT_TOOL))
    deep = via_deep_agent(
        model,
        tools=[*TOOLS, *SANDBOX_TOOLS],
        system_prompt=instructions,
        backend=backend,
        middleware=[*deep_middleware, ToolErrorMiddleware()],
        subagents=subagents,
        response_format=output_schema,
    )
    ours = via_build_runnable(
        model,
        tools=TOOLS,
        system_prompt=instructions,
        sandbox_backend=backend,
        base_middleware=base_middleware,
        subagents=subagents,
        output_schema=output_schema,
    )
    return describe(deep), describe(ours)


@pytest.mark.parametrize("model_name", list(MODELS))
def test_sandbox_assembly_matches_create_deep_agent(model_name):
    """The whole point: same model, same tools, same middleware order, same
    prompt, same tool descriptions — whichever assembler built it, modulo the
    two deviations on record."""
    model = MODELS[model_name]()

    deep, ours = _both(model)

    ours, deep = comparable(ours, deep)
    assert ours == deep


@pytest.mark.parametrize("model_name", list(MODELS))
def test_harness_prompt_is_reproduced_verbatim(model_name):
    """Called out separately because the prompt is the part a diff of class
    names would not catch — and the part a per-thread frozen prompt cannot
    tolerate drifting. deepagents 0.7 ships no authored base prompt: only a
    registered profile adds anything to the agent's own instructions."""
    model = MODELS[model_name]()

    deep, ours = _both(model)

    assert ours["system_prompt"] == deep["system_prompt"]
    assert ours["system_prompt"].startswith("You are a test agent")
    if model_name == "anthropic-profiled":
        assert "<use_parallel_tool_calls>" in ours["system_prompt"]
    else:
        assert ours["system_prompt"] == "You are a test agent"


def test_caller_subagents_are_appended_after_the_general_purpose_one():
    """deepagents inserts its default subagent at index 0 and keeps the
    caller's after it; the `task` tool description enumerates them in that
    order, so a swap would be a visible behaviour change."""
    model = MODELS["openai"]()
    subagents = [
        CompiledSubAgent(name="helper", description="helps", runnable=_Sentinel())
    ]

    deep, ours = _both(model, subagents=subagents)

    task = next(m for m in ours["middleware"] if m["name"] == "SubAgentMiddleware")
    listing = task["tool_descriptions"]["task"]
    assert listing.index("general-purpose") < listing.index("helper")
    assert task == next(
        m for m in deep["middleware"] if m["name"] == "SubAgentMiddleware"
    )


def test_caller_middleware_keeps_its_place_in_the_stack():
    """The caller's stack sits between the harness and prompt caching — which
    is where deepagents put it, and the reason a parent middleware's hooks fire
    in the same order on both paths."""
    model = MODELS["openai"]()
    schema = {"title": "answer", "type": "object", "properties": {}}

    deep, ours = _both(
        model, base_middleware=[PatchToolCallsMiddleware()], output_schema=schema
    )

    ours, deep = comparable(ours, deep)
    names = [m["class"] for m in ours["middleware"]]
    assert names == [m["class"] for m in deep["middleware"]]
    assert names.index("PatchToolCallsMiddleware") < names.index(
        "DeferredStructuredOutputMiddleware"
    )
    assert names.index("DeferredStructuredOutputMiddleware") < names.index(
        "ToolErrorMiddleware"
    )
    assert names[-1] == "AnthropicPromptCachingMiddleware"


def test_a_system_message_prompt_is_extended_the_same_way():
    """`build_runnable`'s callers pass a plain string today, but the harness
    keeps deepagents' `SystemMessage` branch so the two stay interchangeable —
    including on a profiled model, where there is something to append."""
    for model_name in ("openai", "anthropic-profiled"):
        deep, ours = _both(
            MODELS[model_name](), instructions=SystemMessage("You are a test agent")
        )

        assert ours["system_prompt"] == deep["system_prompt"]


def test_graph_config_matches_deepagents():
    """`create_deep_agent` binds a recursion budget and trace metadata onto the
    graph, and a bound config wins the merge with the parent's run config — so
    it is what a sandbox *subagent* runs under. Compare against the real thing
    rather than a constant, so a metadata rename upstream shows up here."""
    model = MODELS["openai"]()
    deep = via_deep_agent(
        model, tools=[*TOOLS, *SANDBOX_TOOLS], backend=LazySandboxBackend()
    )
    with (
        patch("app.sandbox.tools.create_sandbox_tools", return_value=[create_sandbox]),
        patch("app.agents.runtime.create_agent", return_value=_Sentinel()),
    ):
        built = build_runnable(
            model=model,
            tools=[add],
            system_prompt="hi",
            sandbox_backend=LazySandboxBackend(),
        )

    assert built.config == HARNESS_CONFIG == deep["config"]
    assert HARNESS_CONFIG["recursion_limit"] == 9_999


def test_no_sandbox_means_no_harness():
    """The plain path is untouched by all of this: no todos, no filesystem, no
    prompt caching, and the agent's instructions are the whole prompt."""
    seen, patcher = _capture("app.agents.runtime.create_agent")
    with patcher:
        build_runnable(
            model=MODELS["openai"](),
            tools=[add],
            system_prompt="You are a test agent",
            base_middleware=[],
        )

    described = describe(seen)
    assert described["system_prompt"] == "You are a test agent"
    assert described["tools"] == ["add"]
    assert [m["class"] for m in described["middleware"]] == ["ToolErrorMiddleware"]
    assert seen["config"] is None


def test_a_caller_supplied_general_purpose_subagent_replaces_the_default():
    """deepagents treats an explicit `general-purpose` spec as an override, not
    an addition. Prepending ours unconditionally would give the agent two
    subagents under one name."""
    model = MODELS["openai"]()
    subagents = [
        CompiledSubAgent(
            name="general-purpose", description="ours", runnable=_Sentinel()
        )
    ]

    deep, ours = _both(model, subagents=subagents)

    task = next(m for m in ours["middleware"] if m["name"] == "SubAgentMiddleware")
    assert [s["name"] for s in task["subagents"]] == ["general-purpose"]
    assert task["subagents"][0]["compiled"] is True
    assert task == next(
        m for m in deep["middleware"] if m["name"] == "SubAgentMiddleware"
    )


def test_general_purpose_subagent_carries_no_todo_middleware():
    """The parent keeps `TodoListMiddleware` for the UI; the hidden
    general-purpose subagent has no UI, so it follows deepagents 0.7 and drops
    the tool and its prompt fragment."""
    deep, ours = _both(MODELS["openai"]())

    task = next(m for m in ours["middleware"] if m["name"] == "SubAgentMiddleware")
    (general_purpose,) = task["subagents"]
    assert general_purpose["name"] == "general-purpose"
    assert "TodoListMiddleware" not in [
        m["class"] for m in general_purpose["middleware"]
    ]
    assert task == next(
        m for m in deep["middleware"] if m["name"] == "SubAgentMiddleware"
    )


def test_plain_path_wires_subagents_after_the_caller_stack():
    """The plain path has always put `SubAgentMiddleware` on the far side of the
    caller's middleware, where the harness puts its own *before*. Since
    deepagents 0.7 the middleware injects no prompt fragment, so the position
    only orders hooks — but it is still the position every plain agent with
    subagents has run under, and a move is a behaviour change to make on
    purpose."""
    seen, patcher = _capture("app.agents.runtime.create_agent")
    caller = CurrentDateMiddleware(datetime(2026, 1, 1, tzinfo=UTC))
    with patcher:
        build_runnable(
            model=MODELS["openai"](),
            tools=TOOLS,
            system_prompt="You are a test agent",
            base_middleware=[caller],
            subagents=[
                CompiledSubAgent(
                    name="helper", description="helps", runnable=_Sentinel()
                )
            ],
        )

    names = [type(m).__name__ for m in seen["middleware"]]
    assert names == [
        "CurrentDateMiddleware",
        "SubAgentMiddleware",
        "ToolErrorMiddleware",
    ]
