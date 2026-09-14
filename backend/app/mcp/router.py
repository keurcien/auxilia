"""auxilia's own MCP server.

Mounted by `main.py` so auxilia can expose its agents as MCP tools to other
clients. It currently advertises no tools: the demo `list_agents` / `ask_agent`
pair that used to live here returned hardcoded lorem ipsum and was removed
(backend-design-review.md §4.3) rather than left where a client could call it.

Add real tools here — backed by `AgentService` and the durable run runtime, and
authenticated like every other endpoint — not stubs.
"""

from mcp.server.mcpserver import MCPServer


# Transport options (stateless, JSON responses) are given where the ASGI app is
# built, in `main.py` — MCP SDK v2 moved them off the constructor.
auxilia_mcp = MCPServer("auxilia MCP")
