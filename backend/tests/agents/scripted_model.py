"""A chat model that replays a fixed script, for graph-level runtime tests.

`tests/agents/test_runtime.py` asserts on middleware *lists*; the tests that
actually run the graph need a model whose every turn is known in advance, so
the assertion can be "the agent did X", not "the agent was configured with X".

Each entry in `script` is one model turn: either a ready `AIMessage` or a
string (wrapped into an `AIMessage`). Calls past the end of the script raise,
which is what makes an unexpected extra model turn a test failure instead of a
hang.
"""

from collections.abc import Sequence
from typing import Any

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import Runnable
from pydantic import ConfigDict, Field


class ScriptedChatModel(BaseChatModel):
    """Replays `script` one entry per model call, recording what it was sent."""

    script: list[Any]
    calls: list[list[BaseMessage]] = Field(default_factory=list)
    bound_tools: list[Any] = Field(default_factory=list)
    index: int = 0

    model_config = ConfigDict(arbitrary_types_allowed=True)

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> Runnable:
        # create_agent binds the assembled toolset here; keep the same instance
        # so `calls` / `index` stay observable from the test's reference.
        self.bound_tools = list(tools)
        return self.bind(**kwargs)

    def _next(self) -> AIMessage:
        if self.index >= len(self.script):
            msg = (
                f"ScriptedChatModel exhausted after {len(self.script)} turns — "
                "the graph asked for one more model call than the test scripted"
            )
            raise AssertionError(msg)
        entry = self.script[self.index]
        self.index += 1
        return AIMessage(content=entry) if isinstance(entry, str) else entry

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        self.calls.append(list(messages))
        return ChatResult(generations=[ChatGeneration(message=self._next())])
