import asyncio
from mcp.server.fastmcp import FastMCP, Context


auxilia_mcp = FastMCP("auxilia MCP", stateless_http=True, json_response=True)


LOREM_IPSUM = "Lorem ipsum dolor sit amet, consectetur adipiscing elit. Sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat. Duis aute irure dolor in reprehenderit in voluptate velit esse cillum dolore eu fugiat nulla pariatur. Excepteur sint occaecat cupidatat non proident, sunt in culpa qui officia deserunt mollit anim id est laborum."


@auxilia_mcp.tool()
def list_agents() -> dict[str, list[dict[str, str]]]:
    """List all agents available to the user"""
    return {"result": [{"agent_name": "data_analyst", "agent_description": "A data analyst agent capable to run BigQuery queries and analyze data"}]}


@auxilia_mcp.tool()
async def ask_agent(agent_name: str, question: str, ctx: Context) -> dict[str, str]:
    """
    Ask an agent a question
    Args:
        agent_name: The name of the agent to ask
        question: The question to ask the agent
    Returns:
        LOREM IPSUM as it is a test now
    """

    await ctx.info(f"Checking authorization for agent {agent_name}...")
    await asyncio.sleep(0.5)
    await ctx.info(f"Agent {agent_name} is authorized")
    await asyncio.sleep(0.5)
    await ctx.info("Asking agent {agent_name} to answer the question {question}...")
    await asyncio.sleep(0.5)
    await ctx.info("Agent {agent_name} is answering the question {question}...")
    await asyncio.sleep(0.5)
    await ctx.info("Agent {agent_name} has answered the question {question}...")
    await asyncio.sleep(0.5)
    await ctx.info("Agent {agent_name} has answered the question {question} with the following answer: {LOREM_IPSUM}...")
    await asyncio.sleep(0.5)
    return {"result": LOREM_IPSUM}
