from types import SimpleNamespace

from app.agents.runtime import _extract_mcp_app_resource_uri


def test_extract_mcp_app_resource_uri_from_meta_ui():
    tool = SimpleNamespace(
        metadata={"_meta": {"ui": {"resourceUri": " ui://chart/pie "}}}
    )

    assert _extract_mcp_app_resource_uri(tool) == "ui://chart/pie"


def test_extract_mcp_app_resource_uri_from_legacy_meta_ui_key():
    tool = SimpleNamespace(
        metadata={
            "_meta": {
                "io.modelcontextprotocol/ui": {"resourceUri": "ui://chart/funnel"}
            }
        }
    )

    assert _extract_mcp_app_resource_uri(tool) == "ui://chart/funnel"
