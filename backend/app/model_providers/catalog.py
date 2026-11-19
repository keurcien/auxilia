import logging
from functools import lru_cache
from typing import Any

import google.auth
from google.auth.exceptions import DefaultCredentialsError
from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import LanguageModelInput
from langchain_core.messages import AIMessage, BaseMessage
from langchain_deepseek import ChatDeepSeek
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI

from app.model_providers.settings import model_provider_settings


logger = logging.getLogger(__name__)

# provider_api_keys()'s "google" slot when no GOOGLE_API_KEY is configured but
# Application Default Credentials are available (GCP service account on
# Cloud Run/GKE/Compute, `gcloud auth application-default login`, or
# GOOGLE_APPLICATION_CREDENTIALS). Signals ChatModelFactory to serve Gemini
# via Vertex AI instead of the API-key-based Gemini Developer API. Never a
# real credential value.
GOOGLE_ADC_SENTINEL = "adc"

# google-genai only requests this scope itself when it resolves ADC
# internally; since we fetch and hand it `credentials=` explicitly (see
# ChatModelFactory), its own scoped fetch never runs (it's skipped whenever
# credentials are already set). Request the scope here instead, or
# unscoped service-account/GCE credentials get passed through and Vertex AI
# calls fail with an insufficient-scope error.
_VERTEX_AI_SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]


@lru_cache(maxsize=1)
def _google_adc() -> tuple[google.auth.credentials.Credentials, str | None] | None:
    """Application Default Credentials for this environment, or None if
    unavailable. The probe can hit the GCE metadata server, so it's cached —
    the answer can't change for the life of the process."""
    try:
        return google.auth.default(scopes=_VERTEX_AI_SCOPES)
    except DefaultCredentialsError:
        return None


# Models that require adaptive thinking (`{"type": "adaptive"}` + `effort`).
# Opus 4.7+ dropped manual extended thinking and return a 400 for the legacy
# `{"type": "enabled", "budget_tokens": ...}` format. Everything else uses
# the legacy `enabled` format. (Opus 5 thinks by default even without the
# opt-in, but it rejects the legacy format too, so it belongs here.) Every
# Claude 5.x id must be listed: whitelist defaults are policy, not a
# wire-format guarantee.
ADAPTIVE_THINKING_MODELS: frozenset[str] = frozenset(
    {
        "claude-opus-4-6",
        "claude-opus-4-8",
        "claude-sonnet-5",
        "claude-opus-5",
        "claude-fable-5-1",
        "claude-haiku-5-5",
        "claude-sonnet-5-5",
        "claude-opus-5-5",
    }
)


def provider_api_keys() -> dict[str, str]:
    """Configured provider → API key, read at call time (not import time) so
    tests and env changes don't fight module state. Which *models* those
    providers may serve is decided by the whitelist + the workspace's
    enablement rows (ModelService), never here."""
    keys = {
        "openai": model_provider_settings.openai_api_key,
        "deepseek": model_provider_settings.deepseek_api_key,
        "anthropic": model_provider_settings.anthropic_api_key,
        "google": model_provider_settings.google_api_key
        or (GOOGLE_ADC_SENTINEL if _google_adc() else None),
        "xiaomi": model_provider_settings.xiaomi_api_key,
        "openrouter": model_provider_settings.openrouter_api_key,
        "meta": model_provider_settings.metaai_api_key,
    }
    return {name: key for name, key in keys.items() if key}


_WEB_SEARCH_ACTION_TYPES = frozenset({"search", "open_page", "find_in_page"})
_WEB_SEARCH_STATUSES = frozenset(
    {"in_progress", "searching", "completed", "failed", "incomplete"}
)


def _repair_web_search_call(item: dict[str, Any]) -> dict[str, Any]:
    """Give a replayed `web_search_call` fields the Responses API accepts.

    The API occasionally streams a web search whose `action` is missing,
    incomplete, or outside the documented variants. The block is persisted
    as-is in the thread checkpoint, and every later turn that replays the
    history then 400s — the thread is stuck. Normalize the action and status,
    defaulting to a bare completed search (all search fields are optional).
    """
    if item.get("type") != "web_search_call":
        return item
    action = item.get("action")
    if not isinstance(action, dict):
        action = {}

    action_type = action.get("type")
    if action_type not in _WEB_SEARCH_ACTION_TYPES:
        if isinstance(action.get("pattern"), str) and isinstance(
            action.get("url"), str
        ):
            action_type = "find_in_page"
        elif "url" in action and "query" not in action and "queries" not in action:
            action_type = "open_page"
        else:
            action_type = "search"

    # `find_in_page` requires both fields. A partial action is still invalid,
    # so degrade it to a valid search rather than trapping the thread again.
    if action_type == "find_in_page" and not (
        isinstance(action.get("pattern"), str) and isinstance(action.get("url"), str)
    ):
        action_type = "search"

    normalized_action: dict[str, Any] = {"type": action_type}
    if action_type == "search":
        if isinstance(action.get("query"), str):
            normalized_action["query"] = action["query"]
        if isinstance(action.get("queries"), list) and all(
            isinstance(query, str) for query in action["queries"]
        ):
            normalized_action["queries"] = action["queries"]
        # Do not replay `sources`: langchain-openai intentionally strips them
        # because the Responses endpoint has rejected provider-returned sources.
    elif action_type == "open_page":
        if action.get("url") is None or isinstance(action.get("url"), str):
            normalized_action["url"] = action.get("url")
    else:
        normalized_action["url"] = action["url"]
        normalized_action["pattern"] = action["pattern"]

    status = item.get("status")
    if status == "success":
        status = "completed"
    elif status == "error":
        status = "failed"
    elif status not in _WEB_SEARCH_STATUSES:
        status = "completed"
    return {**item, "action": normalized_action, "status": status}


class ResponsesChatOpenAI(ChatOpenAI):
    def bind_tools(self, tools, *, strict=None, **kwargs):
        # Responses defaults to strict normalization, which makes optional MCP
        # fields required. Preserve their schema; the MCP server still validates
        # arguments. Explicit strict=True (structured output) remains supported.
        return super().bind_tools(
            tools, strict=False if strict is None else strict, **kwargs
        )

    def _get_request_payload(
        self,
        input_: LanguageModelInput,
        *,
        stop: list[str] | None = None,
        **kwargs: Any,
    ) -> dict:
        messages = [
            _drop_foreign_blocks(message, "openai", _FOREIGN_OPENAI_BLOCK_TYPES)
            for message in self._convert_input(input_).to_messages()
        ]
        payload = super()._get_request_payload(messages, stop=stop, **kwargs)
        items = payload.get("input")
        if isinstance(items, list):
            payload["input"] = [
                _repair_web_search_call(item) if isinstance(item, dict) else item
                for item in items
            ]
        return payload


_ANTHROPIC_SERVER_CALL_TYPES = frozenset({"server_tool_use", "mcp_tool_use"})
_ANTHROPIC_SERVER_RESULT_TYPES = frozenset(
    {
        "code_execution_tool_result",
        "bash_code_execution_tool_result",
        "text_editor_code_execution_tool_result",
        "mcp_tool_result",
        "web_search_tool_result",
        "web_fetch_tool_result",
    }
)
_FOREIGN_V1_BLOCK_TYPES = frozenset(
    {"server_tool_call", "server_tool_call_chunk", "server_tool_result", "non_standard"}
)
# langchain-openai replays every `reasoning` block as a Responses reasoning
# item, foreign fields included (Anthropic's `signature` is a 400).
_FOREIGN_OPENAI_BLOCK_TYPES = _FOREIGN_V1_BLOCK_TYPES | {"reasoning"}


def _drop_foreign_blocks(
    message: BaseMessage, provider: str, block_types: frozenset[str]
) -> BaseMessage:
    """Strip another provider's provider-specific blocks from a replayed AI message.

    A thread can switch models mid-conversation. langchain-anthropic only
    translates v1 server-tool and non-standard blocks produced by Anthropic,
    and langchain-openai replays reasoning and server-tool blocks whatever
    produced them; either API rejects the foreign shapes. The visible answer
    text and the tool calls are kept.
    """
    if (
        not isinstance(message, AIMessage)
        or not isinstance(message.content, list)
        or message.response_metadata.get("model_provider") == provider
    ):
        return message
    content = [
        block
        for block in message.content
        if not (isinstance(block, dict) and block.get("type") in block_types)
    ]
    if len(content) == len(message.content):
        return message
    return message.model_copy(update={"content": content})


def _nested_anthropic_callers(
    messages: list[BaseMessage],
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    """Index non-direct callers that langchain-anthropic drops during replay."""
    calls: dict[str, dict[str, Any]] = {}
    results: dict[str, dict[str, Any]] = {}
    for message in messages:
        if not isinstance(message, AIMessage) or not isinstance(message.content, list):
            continue
        for block in message.content:
            if not isinstance(block, dict):
                continue
            extras = block.get("extras")
            caller = block.get("caller")
            if not isinstance(caller, dict) and isinstance(extras, dict):
                caller = extras.get("caller")
            if not isinstance(caller, dict) or caller.get("type") == "direct":
                continue

            block_type = block.get("type")
            if (
                block_type in _ANTHROPIC_SERVER_CALL_TYPES
                or block_type == "server_tool_call"
            ):
                if isinstance(block.get("id"), str):
                    calls[block["id"]] = caller
            elif block_type in _ANTHROPIC_SERVER_RESULT_TYPES:
                if isinstance(block.get("tool_use_id"), str):
                    results[block["tool_use_id"]] = caller
            elif block_type == "server_tool_result" and isinstance(
                block.get("tool_call_id"), str
            ):
                results[block["tool_call_id"]] = caller
    return calls, results


def _drop_orphaned_server_blocks(payload_messages: list[dict]) -> list[dict]:
    """Remove server-tool blocks whose originating call is not in the request.

    A server tool can finish in a later assistant message than its
    `server_tool_use` (a paused or continued turn). History trimming such as
    summarization cuts on message boundaries and can keep the result while
    dropping the call; Anthropic then rejects every later turn of the thread.
    The same applies to a nested call whose `caller` names a missing call.
    """
    seen_calls: set[str] = set()
    sanitized: list[dict] = []
    for message in payload_messages:
        content = message.get("content")
        if message.get("role") != "assistant" or not isinstance(content, list):
            sanitized.append(message)
            continue
        kept: list = []
        for block in content:
            if not isinstance(block, dict):
                kept.append(block)
                continue
            block_type = block.get("type")
            if block_type in _ANTHROPIC_SERVER_CALL_TYPES:
                caller = block.get("caller")
                parent = caller.get("tool_id") if isinstance(caller, dict) else None
                if parent is not None and parent not in seen_calls:
                    logger.warning(
                        "Dropping replayed %s %s: its caller %s is not in the history",
                        block_type,
                        block.get("id"),
                        parent,
                    )
                    continue
                if isinstance(block.get("id"), str):
                    seen_calls.add(block["id"])
            elif (
                block_type in _ANTHROPIC_SERVER_RESULT_TYPES
                and block.get("tool_use_id") not in seen_calls
            ):
                logger.warning(
                    "Dropping replayed %s for %s: its call is not in the history",
                    block_type,
                    block.get("tool_use_id"),
                )
                continue
            kept.append(block)
        if kept:
            sanitized.append({**message, "content": kept})
    return sanitized


class ReplaySafeChatAnthropic(ChatAnthropic):
    """Keep replayed server-tool blocks valid for the Messages API.

    Restores nested callers until langchain-ai/langchain#41678 ships, drops
    server-tool blocks orphaned by history trimming, and drops server-tool
    blocks produced by another provider.
    """

    def _get_request_payload(
        self,
        input_: LanguageModelInput,
        *,
        stop: list[str] | None = None,
        **kwargs: Any,
    ) -> dict:
        messages = [
            _drop_foreign_blocks(message, "anthropic", _FOREIGN_V1_BLOCK_TYPES)
            for message in self._convert_input(input_).to_messages()
        ]
        calls, results = _nested_anthropic_callers(messages)
        payload = super()._get_request_payload(messages, stop=stop, **kwargs)

        for message in payload.get("messages", []):
            content = message.get("content")
            if not isinstance(content, list):
                continue
            for block in content:
                if not isinstance(block, dict):
                    continue
                block_type = block.get("type")
                if block_type in _ANTHROPIC_SERVER_CALL_TYPES:
                    caller = calls.get(block.get("id"))
                elif block_type in _ANTHROPIC_SERVER_RESULT_TYPES:
                    caller = results.get(block.get("tool_use_id"))
                else:
                    caller = None
                if caller is not None:
                    block["caller"] = caller
        if isinstance(payload.get("messages"), list):
            payload["messages"] = _drop_orphaned_server_blocks(payload["messages"])
        return payload


class ChatModelFactory:
    def create(
        self,
        provider: str,
        model_id: str,
        api_key: str | None,
        reasoning_effort: str | None = None,
        base_url: str | None = None,
        context_window: int | None = None,
    ):
        model = self._build(provider, model_id, api_key, reasoning_effort, base_url)
        # The catalog wins over langchain's bundled profile, which lags new
        # models; whatever reads the window (the context footprint, deepagents'
        # summarization) reads it from the profile.
        if context_window is not None:
            model.profile = {
                **(model.profile or {}),
                "max_input_tokens": context_window,
            }
        return model

    def _build(
        self,
        provider: str,
        model_id: str,
        api_key: str | None,
        reasoning_effort: str | None,
        base_url: str | None,
    ):
        # `reasoning_effort` is a value from the model's whitelist-declared
        # levels (ModelService.ensure_available resolves and clamps it) —
        # never a raw client string. None means "no explicit choice": each
        # branch keeps its historical default behavior, so existing threads
        # run exactly as before.
        #
        # max_retries=0 everywhere: retrying is owned by ModelRetryMiddleware
        # (classified via ModelError.is_retryable, persists the failure as an
        # AIMessage on exhaustion). Leaving the SDK layer's default retries on
        # would multiply the layers — one transient failure could cost up to
        # middleware_attempts × sdk_attempts provider requests.
        if provider != "ollama" and not api_key:
            raise ValueError(f"Provider {provider} requires an API key")
        match provider:
            case "openai":
                # Use Responses for every native OpenAI model so newly added
                # reasoning models can bind tools without an endpoint allowlist.
                # LangChain translates reasoning_effort to reasoning.effort.
                #
                # store=False: the checkpoint replays the whole history on
                # every call, so nothing reads OpenAI's stored copy, and
                # storing fails outright once a turn grows large ("The
                # response is too large to store"). Reasoning then travels
                # encrypted instead of by stored id.
                return ResponsesChatOpenAI(
                    model=model_id,
                    api_key=api_key,
                    max_retries=0,
                    use_responses_api=True,
                    reasoning_effort=reasoning_effort,
                    stream_usage=True,
                    store=False,
                    include=["reasoning.encrypted_content"],
                )
            case "deepseek":
                # DeepSeek V4 selects thinking by parameters: `thinking.type`
                # turns it on/off ("none" maps to disabled), `reasoning_effort`
                # picks the depth (low/high/max; the API defaults to high).
                # max_tokens caps the answer so json_object structured output
                # isn't truncated mid-string (DeepSeek's JSON mode guide warns
                # about this); 32768 matches the other reasoning providers.
                thinking_off = reasoning_effort == "none"
                extra_body: dict = {
                    "thinking": {"type": "disabled" if thinking_off else "enabled"}
                }
                if reasoning_effort and not thinking_off:
                    extra_body["reasoning_effort"] = reasoning_effort
                return ChatDeepSeek(
                    model=model_id,
                    api_key=api_key,
                    max_tokens=32768,
                    max_retries=0,
                    stream_usage=True,
                    extra_body=extra_body,
                )
            case "anthropic":
                kwargs: dict = {}
                if model_id in ADAPTIVE_THINKING_MODELS or reasoning_effort:
                    # Adaptive thinking + output_config.effort. Mandatory on
                    # Opus 4.7+/Sonnet 5 (the legacy budget format 400s there);
                    # older models (e.g. Sonnet 4.6) opt in whenever the user
                    # picked an effort level.
                    #
                    # `display` defaults to "omitted" on Opus 4.7+, which returns
                    # thinking blocks with an empty `thinking` field. langchain
                    # then drops the field when round-tripping the block after a
                    # tool call, and the API rejects it with
                    # `content.0.thinking.thinking: Field required`. Requesting
                    # "summarized" keeps the field populated so it survives the
                    # round-trip (and surfaces reasoning to the UI).
                    kwargs["thinking"] = {"type": "adaptive", "display": "summarized"}
                    kwargs["effort"] = reasoning_effort or "medium"
                else:
                    kwargs["thinking"] = {"type": "enabled", "budget_tokens": 1024}
                return ReplaySafeChatAnthropic(
                    model=model_id,
                    temperature=1,
                    max_tokens=32768,
                    streaming=True,
                    timeout=None,
                    max_retries=0,
                    api_key=api_key,
                    **kwargs,
                )
            case "google":
                auth_kwargs: dict = {}
                if api_key == GOOGLE_ADC_SENTINEL:
                    # No GOOGLE_API_KEY configured; serve Gemini via Vertex AI
                    # using the environment's Application Default Credentials
                    # instead of an API key (e.g. a GCP service account).
                    credentials, project = _google_adc()
                    auth_kwargs["vertexai"] = True
                    auth_kwargs["credentials"] = credentials
                    if project:
                        auth_kwargs["project"] = project
                else:
                    auth_kwargs["api_key"] = api_key
                # thinking_level (aka reasoning_effort) and thinking_budget are
                # mutually exclusive on Gemini 3+ — send at most one: the
                # user's level, else the dynamic budget (historical default).
                # Gemini 4 rejects thinking_budget, so no explicit level means
                # the provider's default.
                if reasoning_effort:
                    auth_kwargs["reasoning_effort"] = reasoning_effort
                elif not model_id.startswith("gemini-4"):
                    auth_kwargs["thinking_budget"] = -1
                return ChatGoogleGenerativeAI(
                    model=model_id,
                    temperature=0,
                    max_tokens=None,
                    timeout=None,
                    max_retries=0,
                    streaming=True,
                    include_thoughts=True,
                    **auth_kwargs,
                )
            case "xiaomi":
                return ChatOpenAI(
                    base_url="https://api.xiaomimimo.com/v1",
                    model=model_id,
                    api_key=api_key,
                    max_retries=0,
                    stream_usage=True,
                )
            case "openrouter":
                # OpenAI-compatible gateway; model_id is the OpenRouter slug,
                # sent verbatim like any other provider's id. The effort level
                # travels as the OpenAI-style `reasoning_effort`, which
                # OpenRouter normalizes for the upstream host. Output is capped
                # generously (GLM 5.2 max = 32768) since deep reasoning
                # produces long chains of thought.
                return ChatOpenAI(
                    base_url="https://openrouter.ai/api/v1",
                    model=model_id,
                    api_key=api_key,
                    max_tokens=32768,
                    max_retries=0,
                    stream_usage=True,
                    extra_body=(
                        {"reasoning_effort": reasoning_effort}
                        if reasoning_effort
                        else None
                    ),
                )
            case "meta":
                # Meta Model API — OpenAI-compatible Chat Completions. None
                # leaves Meta's model-determined effort unchanged.
                return ChatOpenAI(
                    base_url="https://api.meta.ai/v1",
                    model=model_id,
                    api_key=api_key,
                    max_retries=0,
                    stream_usage=True,
                    extra_body=(
                        {"reasoning_effort": reasoning_effort}
                        if reasoning_effort
                        else None
                    ),
                )
            case "ollama":
                if not base_url:
                    raise ValueError("Provider ollama requires a base URL")
                return ChatOpenAI(
                    base_url=f"{base_url.rstrip('/')}/v1",
                    model=model_id,
                    api_key="ollama",
                    max_retries=0,
                    streaming=True,
                    stream_usage=True,
                    timeout=None,
                )
            case _:
                raise ValueError(f"Provider {provider} not supported")
