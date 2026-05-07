from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.agents.runs.patch import find_dangling_tool_calls


def _ai_with_calls(*calls):
    return AIMessage(
        content="",
        tool_calls=[{"name": n, "args": {}, "id": i} for n, i in calls],
    )


class TestFindDangling:
    def test_no_messages_returns_empty(self):
        assert find_dangling_tool_calls([]) == []

    def test_only_human_message_returns_empty(self):
        msgs = [HumanMessage(content="hi")]
        assert find_dangling_tool_calls(msgs) == []

    def test_ai_with_no_tool_calls_returns_empty(self):
        msgs = [HumanMessage(content="hi"), AIMessage(content="hello")]
        assert find_dangling_tool_calls(msgs) == []

    def test_fully_answered_tool_call_returns_empty(self):
        msgs = [
            _ai_with_calls(("read_file", "tc1")),
            ToolMessage(content="result", tool_call_id="tc1", name="read_file"),
        ]
        assert find_dangling_tool_calls(msgs) == []

    def test_unanswered_tool_call_gets_patched(self):
        msgs = [_ai_with_calls(("read_file", "tc1"))]
        patches = find_dangling_tool_calls(msgs)
        assert len(patches) == 1
        patch = patches[0]
        assert patch.tool_call_id == "tc1"
        assert patch.name == "read_file"
        assert patch.status == "error"
        assert "tc1" in patch.content

    def test_partial_answers_only_patch_missing(self):
        msgs = [
            _ai_with_calls(("a", "tc-a"), ("b", "tc-b"), ("c", "tc-c")),
            ToolMessage(content="ok", tool_call_id="tc-b", name="b"),
        ]
        patches = find_dangling_tool_calls(msgs)
        assert {p.tool_call_id for p in patches} == {"tc-a", "tc-c"}

    def test_multiple_ai_messages_each_handled(self):
        msgs = [
            _ai_with_calls(("a", "tc-a")),
            ToolMessage(content="ok", tool_call_id="tc-a", name="a"),
            HumanMessage(content="next"),
            _ai_with_calls(("b", "tc-b")),
        ]
        patches = find_dangling_tool_calls(msgs)
        assert {p.tool_call_id for p in patches} == {"tc-b"}

    def test_idempotent_dedup_within_one_call(self):
        # Defensive: same tool_call_id appearing twice should produce one patch.
        msgs = [_ai_with_calls(("a", "dup")), _ai_with_calls(("a", "dup"))]
        patches = find_dangling_tool_calls(msgs)
        assert len(patches) == 1

    def test_custom_reason_appears_in_content(self):
        msgs = [_ai_with_calls(("read_file", "tc1"))]
        patches = find_dangling_tool_calls(msgs, reason="server crashed")
        assert "server crashed" in patches[0].content
