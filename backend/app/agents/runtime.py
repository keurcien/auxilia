from app.integrations.langfuse.callback import langfuse_callback_handler
from app.mcp.client.factory import MCPClientConfigFactory
from app.agents.settings import agent_settings
from app.database import get_psycopg_conn_string
from app.model_providers.settings import model_provider_settings
from app.threads.models import ThreadDB
from app.models.message import Message
from app.mcp.servers.models import MCPServerDB
from app.agents.utils import read_agent
from app.adapters.stream.adapter import AISDKStreamAdapter
from app.adapters.stream_adapter import AISDKStreamAdapter, SlackStreamAdapter
import asyncio
from pydantic import BaseModel
from dataclasses import dataclass
from langchain.agents import create_agent
from langchain_core.tools import Tool
from langchain_deepseek import ChatDeepSeek
from langchain_anthropic import ChatAnthropic
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.types import Command
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langchain_core.messages import SystemMessage
from langchain.agents.middleware import HumanInTheLoopMiddleware
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select
from app.adapters.message_adapter import (
    to_langchain_message,
    extract_commands,
    extract_rejected_tool_calls,
    extract_approved_tool_call_ids,
)


class ModelProvider(BaseModel):
    name: str
    api_key: str


class Model(BaseModel):
    name: str
    provider: str


LLM_PROVIDERS = []
MODELS = []

if model_provider_settings.openai_api_key:
    LLM_PROVIDERS.append(ModelProvider(
        name="openai", api_key=model_provider_settings.openai_api_key))
    MODELS.append(Model(name="gpt-4o-mini", provider="openai"))

if model_provider_settings.deepseek_api_key:
    LLM_PROVIDERS.append(ModelProvider(
        name="deepseek", api_key=model_provider_settings.deepseek_api_key))
    MODELS.append(Model(name="deepseek-chat", provider="deepseek"))
    MODELS.append(Model(name="deepseek-reasoner", provider="deepseek"))

if model_provider_settings.anthropic_api_key:
    LLM_PROVIDERS.append(ModelProvider(
        name="anthropic", api_key=model_provider_settings.anthropic_api_key))
    MODELS.append(Model(name="claude-haiku-4-5", provider="anthropic"))
    MODELS.append(Model(name="claude-sonnet-4-5", provider="anthropic"))
    MODELS.append(Model(name="claude-opus-4-5", provider="anthropic"))

if model_provider_settings.google_api_key:
    LLM_PROVIDERS.append(ModelProvider(
        name="google", api_key=model_provider_settings.google_api_key))
    MODELS.append(Model(name="gemini-3-flash-preview", provider="google"))
    MODELS.append(Model(name="gemini-3-pro-preview", provider="google"))


class ChatModelFactory:

    def create(self, provider: str, model_id: str, api_key: str):

        match provider:
            case "openai":
                return ChatOpenAI(model=model_id, api_key=api_key)
            case "deepseek":
                return ChatDeepSeek(model=model_id, api_key=api_key)
            case "anthropic":
                return ChatAnthropic(
                    model=model_id,
                    temperature=1,
                    max_tokens=2048,
                    streaming=True,
                    timeout=None,
                    thinking={"type": "enabled", "budget_tokens": 1024},
                    max_retries=2,
                    api_key=api_key
                )
            case "google":
                return ChatGoogleGenerativeAI(
                    model=model_id,
                    temperature=0,
                    max_tokens=None,
                    timeout=None,
                    max_retries=2,
                    streaming=True,
                    include_thoughts=True,
                    thinking_budget=-1,
                    api_key=api_key,
                )
            case _:
                raise ValueError(f"Provider {provider} not supported")


@dataclass
class AgentRuntimeDependencies:
    model_factory: ChatModelFactory
    mcp_client_config_factory: MCPClientConfigFactory


class AgentRuntime:
    def __init__(self, thread: ThreadDB, db: AsyncSession, deps: AgentRuntimeDependencies):
        self.thread = thread
        self.tools = None
        self.db = db
        self._deps = deps
        self.callbacks = [
            langfuse_callback_handler] if langfuse_callback_handler is not None else []

    @property
    def metadata(self) -> dict:
        return {
            "user_id": self.thread.user_id,
            "thread_id": self.thread.id,
            "agent_id": self.thread.agent_id,
        }

    async def build_multi_mcp_server_configs(self, mcp_server_configs: list[dict]) -> dict:

        return {
            mcp_server_config.name: await self._deps.mcp_client_config_factory.build(mcp_server_config)
            for mcp_server_config in mcp_server_configs
        }

    async def get_tools(
        self,
        multi_mcp_server_configs: dict,
        tool_settings_map: dict[str, dict[str, str] | None],
    ) -> list[Tool]:
        """
        Fetch tools from MCP servers and filter based on tool settings per server.

        Args:
            multi_mcp_server_configs: Dict mapping server_id to server config
            tool_settings_map: Dict mapping server_name to tool status dict (e.g. {"tool_name": "always_allow"})

        Returns:
            Filtered list of tools
        """
        client = MultiServerMCPClient(
            multi_mcp_server_configs, tool_name_prefix=True)

        async def fetch_and_filter_tools(server_id: str):
            tools = await client.get_tools(server_name=server_id)
            tool_settings = tool_settings_map.get(str(server_id))
            always_allowed_tools = [tool for tool in tools if tool.name in [
                server_id + "_" + tool for tool, status in tool_settings.items() if status == "always_allow"]]
            need_approval_tools = [tool for tool in tools if tool.name in [
                server_id + "_" + tool for tool, status in tool_settings.items() if status == "needs_approval"]]
            return always_allowed_tools, need_approval_tools

        tasks = [
            fetch_and_filter_tools(server_id)
            for server_id in multi_mcp_server_configs.keys()
        ]
        results = await asyncio.gather(*tasks)

        always_allowed_tools = [
            tool for result in results for tool in result[0]]
        need_approval_tools = [
            tool for result in results for tool in result[1]]

        return always_allowed_tools, need_approval_tools

    async def get_model_provider(self, model_name: str = "gpt-4o-mini") -> ModelProvider:
        model = next(model for model in MODELS if model.name == model_name)
        return next(
            provider for provider in LLM_PROVIDERS if model.provider == provider.name
        )

    @classmethod
    async def create(cls, thread: ThreadDB, db: AsyncSession, deps: AgentRuntimeDependencies):
        self = cls(thread, db, deps)
        await self.initialize()
        return self

    async def initialize(self):
        self.config = await read_agent(self.thread.agent_id, self.db)

        result = await self.db.execute(
            select(MCPServerDB).where(
                MCPServerDB.id.in_(
                    [mcp_server.id for mcp_server in self.config.mcp_servers]
                )
            )
        )
        mcp_servers = result.scalars().all()
        mcp_servers = list(mcp_servers)

        mcp_server_configs = await self.build_multi_mcp_server_configs(mcp_servers)

        tool_settings = {
            next(server.name for server in mcp_servers if server.id == mcp_server.id): mcp_server.tools
            for mcp_server in self.config.mcp_servers
        }

        self.tools = await self.get_tools(mcp_server_configs, tool_settings)

    async def stream(self, messages: list[Message], message_id: str | None = None, stream_adapter: str = "ai_sdk"):
        """Wrapper to keep checkpointer alive during streaming.

        Args:
            messages: List of messages to process
            message_id: Optional message ID from frontend (used when resuming after HITL approval)
        """
        async with AsyncPostgresSaver.from_conn_string(get_psycopg_conn_string()) as checkpointer:
            model_provider = await self.get_model_provider(self.thread.model_id)
            chat_model = self._deps.model_factory.create(
                model_provider.name, self.thread.model_id, model_provider.api_key)

            tools = self.tools[0] + self.tools[1]
            need_approval_tools = self.tools[1]

            # Catch all tool errors
            for tool in tools:
                tool.handle_tool_error = True

            agent = create_agent(
                model=chat_model,
                tools=tools,
                system_prompt=SystemMessage(content=self.config.instructions),
                checkpointer=checkpointer,
                middleware=[
                    HumanInTheLoopMiddleware(
                        interrupt_on={
                            tool.name: True for tool in need_approval_tools
                        },
                        description_prefix="Tool execution pending approval",
                    )
                ],
            )
            langchain_messages = [to_langchain_message(
                message) for message in messages]
            commands = sum([extract_commands(message)
                           for message in messages if extract_commands(message)], [])

            # Extract rejected tool calls to emit error events in the stream
            rejected_tool_calls = sum(
                [extract_rejected_tool_calls(message) for message in messages],
                []
            )

            # Extract approved tool call IDs to skip their input events (already shown in UI)
            approved_tool_call_ids = sum(
                [extract_approved_tool_call_ids(message)
                 for message in messages],
                []
            )

            is_resume = len(commands) > 0
            resume_message_id = message_id if is_resume else None

            if is_resume:
                langchain_stream = agent.astream_events(
                    Command(
                        resume={"decisions": [{"type": command} for command in commands]}),
                    version="v2",
                    config={
                        "configurable": {"thread_id": self.thread.id},
                        "recursion_limit": agent_settings.recursion_limit,
                        "callbacks": self.callbacks,
                        "metadata": self.metadata
                    },
                )
            else:
                langchain_stream = agent.astream_events(
                    {"messages": langchain_messages},
                    version="v2",
                    config={
                        "configurable": {"thread_id": self.thread.id},
                        "recursion_limit": agent_settings.recursion_limit,
                        "callbacks": self.callbacks,
                        "metadata": self.metadata
                    },
                )

            if stream_adapter == "ai_sdk":
                ai_sdk_stream_adapter = AISDKStreamAdapter(
                    message_id=resume_message_id,
                    is_resume=is_resume,
                    rejected_tool_calls=rejected_tool_calls,
                    approved_tool_call_ids=approved_tool_call_ids,
                )
                stream = ai_sdk_stream_adapter.to_data_stream(
                    langchain_stream)
            elif stream_adapter == "slack":
                slack_stream_adapter = SlackStreamAdapter()
                stream = slack_stream_adapter.to_data_stream(
                    langchain_stream)

            async for chunk in stream:
                yield chunk
