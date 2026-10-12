from uuid import uuid4

from langchain_core.messages import ToolMessage

from app.artifacts.tool import present_files_tool
from app.runtime.protocol.messages import serialize_message_preview


def test_tool_schema_hides_identity_and_keeps_only_file_inputs():
    tool = present_files_tool(None, "thread", uuid4())
    assert set(tool.tool_call_schema.model_json_schema()["properties"]) == {"files"}


def test_reloaded_transcript_preserves_references_without_file_bytes():
    message = ToolMessage(
        content="Presented report",
        tool_call_id="call",
        artifact={"auxilia_artifacts": [{"id": "file-id"}]},
    )
    assert serialize_message_preview(message)["artifact"] == message.artifact
