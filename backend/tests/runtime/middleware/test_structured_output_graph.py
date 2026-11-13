from typing import Any

import pytest
from langchain.agents import create_agent
from langchain.agents.structured_output import ToolStrategy
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool
from langchain_core.utils.function_calling import convert_to_openai_tool

from app.runtime.middleware.structured_output import DeferredStructuredOutputMiddleware
from tests.runtime.scripted_model import ScriptedChatModel


SCHEMA = {
    "title": "answer",
    "type": "object",
    "properties": {"answer": {"type": "integer"}},
    "required": ["answer"],
}


@tool
def execute() -> int:
    """Count the products in the source."""
    return 4


class FormattingChatModel(ScriptedChatModel):
    """Reproduce a formatter choosing execute whenever it remains available."""

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        names = {
            convert_to_openai_tool(bound)["function"]["name"]
            for bound in kwargs.get("tools", [])
        }
        if not messages[-1].content.startswith("Based on your answer above,"):
            if self.index == 0 and "execute" not in names:
                message = AIMessage("The source could not be read.")
            else:
                return super()._generate(messages, stop, run_manager, **kwargs)
        elif "execute" in names:
            message = AIMessage(
                "", tool_calls=[{"name": "execute", "args": {}, "id": "format"}]
            )
        elif "answer" in names:
            message = AIMessage(
                "",
                tool_calls=[{"name": "answer", "args": {"answer": 4}, "id": "report"}],
            )
        else:
            message = AIMessage('{"answer": 4}')
        return ChatResult(generations=[ChatGeneration(message=message)])


@pytest.mark.parametrize(
    "response_format",
    [SCHEMA, ToolStrategy(SCHEMA)],
    ids=["provider-native-profile", "tool-strategy"],
)
async def test_an_audit_keeps_its_analysis_tools_but_formats_only_the_report(
    response_format,
):
    model = FormattingChatModel(
        profile={"structured_output": True},
        script=[
            AIMessage(
                "", tool_calls=[{"name": "execute", "args": {}, "id": "analysis"}]
            ),
            "The source contains four products.",
        ],
    )
    agent = create_agent(
        model,
        tools=[execute],
        response_format=response_format,
        middleware=[DeferredStructuredOutputMiddleware()],
    )

    result = await agent.ainvoke(
        {"messages": [{"role": "user", "content": "Count the source products."}]}
    )

    assert result["structured_response"] == {"answer": 4}
    assert [
        message.content
        for message in result["messages"]
        if isinstance(message, ToolMessage) and message.name == "execute"
    ] == ["4"]
