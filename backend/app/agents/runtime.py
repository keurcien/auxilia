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
from langchain.agents.middleware import HumanInTheLoopMiddleware
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select
from app.adapters.message_adapter import (
    to_langchain_message,
    extract_commands,
    extract_rejected_tool_calls,
    extract_approved_tool_call_ids,
)
from app.adapters.stream_adapter import AISDKStreamAdapter
from app.agents.utils import read_agent
from app.mcp.client.auth import ServerlessOAuthProvider, build_oauth_client_metadata
from app.mcp.client.storage import TokenStorageFactory
from app.mcp.servers.models import MCPAuthType, MCPServerDB
from app.models.message import Message
from app.threads.models import ThreadDB
from app.mcp.servers.router import get_mcp_server_api_key
from app.model_providers.settings import model_provider_settings
from app.settings import app_settings


class ModelProvider(BaseModel):
    name: str
    api_key: str

class Model(BaseModel):
    name: str
    provider: str


LLM_PROVIDERS = []
MODELS = []

if model_provider_settings.openai_api_key:
    LLM_PROVIDERS.append(ModelProvider(name="openai", api_key=model_provider_settings.openai_api_key))
    MODELS.append(Model(name="gpt-4o-mini", provider="openai"))
if model_provider_settings.deepseek_api_key:
    LLM_PROVIDERS.append(ModelProvider(name="deepseek", api_key=model_provider_settings.deepseek_api_key))
    MODELS.append(Model(name="deepseek-chat", provider="deepseek"))
if model_provider_settings.anthropic_api_key:
    LLM_PROVIDERS.append(ModelProvider(name="anthropic", api_key=model_provider_settings.anthropic_api_key))
    MODELS.append(Model(name="claude-haiku-4-5", provider="anthropic"))
if model_provider_settings.google_api_key:
    LLM_PROVIDERS.append(ModelProvider(name="google", api_key=model_provider_settings.google_api_key))
    MODELS.append(Model(name="gemini-3-flash-preview", provider="google"))


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

class AgentRuntime:
    def __init__(self, thread: ThreadDB, db: AsyncSession, deps: AgentRuntimeDependencies):
        self.thread = thread
        self.tools = None
        self.db = db
        self._deps = deps

    async def build_mcp_server_config(self, mcp_server_config: dict) -> dict:
        client_metadata = build_oauth_client_metadata(mcp_server_config)
        storage = TokenStorageFactory().get_storage(mcp_server_config.id)

        config = {
            "url": mcp_server_config.url,
            "transport": "streamable_http",
        }

        if mcp_server_config.auth_type == MCPAuthType.none:
            return config
    
        if mcp_server_config.auth_type == MCPAuthType.api_key:
            api_key = await get_mcp_server_api_key(mcp_server_config.id, self.db)
            return {
                **config,
                "headers": {"Authorization": f"Bearer {api_key}"},
            }

        return {
            **config,
            "auth": ServerlessOAuthProvider(
                server_url=mcp_server_config.url,
                client_metadata=client_metadata,
                storage=storage,
            ),
        }

    async def build_multi_mcp_server_configs(self, mcp_server_configs: list[dict]) -> dict:
        return {
            mcp_server_config.name: await self.build_mcp_server_config(mcp_server_config)
            for mcp_server_config in mcp_server_configs
        }

    async def get_tools(
        self,
        multi_mcp_server_configs: dict,
        enabled_tools_map: dict[str, list[str] | None],
    ) -> list[Tool]:
        """
        Fetch tools from MCP servers and filter based on enabled_tools per server.

        Args:
            multi_mcp_server_configs: Dict mapping server_id to server config
            enabled_tools_map: Dict mapping server_id to list of enabled tool names (None means all tools enabled)

        Returns:
            Filtered list of tools
        """
        client = MultiServerMCPClient(multi_mcp_server_configs, tool_name_prefix=True)

        async def fetch_and_filter_tools(server_id: str):
            tools = await client.get_tools(server_name=server_id)
            enabled_tools = enabled_tools_map.get(str(server_id))

            if enabled_tools is None or enabled_tools == ["*"]:
                return tools
            else:
                filtered = [tool for tool in tools if tool.name in enabled_tools]
                return filtered

        tasks = [
            fetch_and_filter_tools(server_id)
            for server_id in multi_mcp_server_configs.keys()
        ]
        results = await asyncio.gather(*tasks)
        tools = [tool for result in results for tool in result]
        return tools

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
        enabled_tools_map = {
            str(mcp_server.id): mcp_server.enabled_tools
            for mcp_server in self.config.mcp_servers
        }

        self.tools = await self.get_tools(mcp_server_configs, enabled_tools_map)

    async def stream(self, messages: list[Message], message_id: str | None = None):
        """Wrapper to keep checkpointer alive during streaming.
        
        Args:
            messages: List of messages to process
            message_id: Optional message ID from frontend (used when resuming after HITL approval)
        """
        async with AsyncPostgresSaver.from_conn_string(app_settings.database_url) as checkpointer:
            model_provider = await self.get_model_provider(self.thread.model_id)
            chat_model = self._deps.model_factory.create(model_provider.name, self.thread.model_id, model_provider.api_key)
            
            agent = create_agent(
                model=chat_model,
                tools=self.tools,
                checkpointer=checkpointer,
                    middleware=[
                    HumanInTheLoopMiddleware( 
                        interrupt_on={
                            "Notion_notion-search": True,
                        },
                        description_prefix="Tool execution pending approval",
                    )
                ],
            )
            langchain_messages = [to_langchain_message(message) for message in messages]
            commands = sum([extract_commands(message) for message in messages if extract_commands(message)], [])
            
            # Extract rejected tool calls to emit error events in the stream
            rejected_tool_calls = sum(
                [extract_rejected_tool_calls(message) for message in messages],
                []
            )
            
            # Extract approved tool call IDs to skip their input events (already shown in UI)
            approved_tool_call_ids = sum(
                [extract_approved_tool_call_ids(message) for message in messages],
                []
            )
            
            is_resume = len(commands) > 0
            resume_message_id = message_id if is_resume else None
            
            if is_resume:
                langchain_stream = agent.astream_events(
                    Command(resume={"decisions": [{"type": command} for command in commands]}),
                    version="v2",
                    config={"configurable": {"thread_id": self.thread.id}},
                )
            else:
                langchain_stream = agent.astream_events(
                    {"messages": langchain_messages},
                    version="v2",
                    config={"configurable": {"thread_id": self.thread.id}},
                )

            ai_sdk_stream_adapter = AISDKStreamAdapter(
                message_id=resume_message_id,
                is_resume=is_resume,
                rejected_tool_calls=rejected_tool_calls,
                approved_tool_call_ids=approved_tool_call_ids,
            )
            ai_sdk_stream = ai_sdk_stream_adapter.to_data_stream(langchain_stream)

            async for chunk in ai_sdk_stream:
                yield chunk