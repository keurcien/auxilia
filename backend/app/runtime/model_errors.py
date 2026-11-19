"""Turn a model provider failure into a run error a reader can act on.

Providers fail with their own wording (`prompt is too long: 1033140 tokens >
1000000 maximum`, `context_length_exceeded`, a bare 529). langchain already
classifies most of them into `langchain_core.exceptions.ModelError`
subclasses, so the run record stores one sentence per class instead of the
raw provider text. Every message starts with a stable label followed by a
colon: the web client keys its error title on that label, and the Slack,
Telegram and WhatsApp consumers relay the sentence as-is.
"""

import re

from langchain_core.exceptions import (
    ContextOverflowError,
    ModelAPIError,
    ModelAuthenticationError,
    ModelConnectionError,
    ModelError,
    ModelNotFoundError,
    ModelPermissionDeniedError,
    ModelRateLimitError,
    ModelTimeoutError,
)


CONTEXT_OVERFLOW_LABEL = "Context window exceeded"

# Providers that don't raise `ContextOverflowError` (OpenAI-compatible
# gateways) still say so in their message.
_OVERFLOW_MARKERS = (
    "prompt is too long",
    "context_length_exceeded",
    "maximum context length",
    "context window",
    "input token count",
)

# (sent, maximum) as each provider words it.
_OVERFLOW_COUNTS = (
    # Anthropic: "prompt is too long: 1033140 tokens > 1000000 maximum"
    re.compile(r"(?P<sent>\d[\d,]*) tokens > (?P<max>\d[\d,]*) maximum"),
    # OpenAI: "maximum context length is 128000 tokens. However, your
    # messages resulted in 130512 tokens"
    re.compile(
        r"maximum context length is (?P<max>\d[\d,]*) tokens.*?"
        r"resulted in (?P<sent>\d[\d,]*) tokens",
        re.DOTALL,
    ),
    # Gemini: "The input token count (1100000) exceeds the maximum number of
    # tokens allowed (1048576)"
    re.compile(
        r"input token count \((?P<sent>\d[\d,]*)\) exceeds the maximum number "
        r"of tokens allowed \((?P<max>\d[\d,]*)\)"
    ),
)


def _chain(exc: BaseException):
    """The exception and everything it was raised from, outermost first."""
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = current.__cause__ or current.__context__


def _count(value: str) -> int:
    return int(value.replace(",", ""))


def context_overflow_error(text: str) -> str:
    sizes = ""
    for pattern in _OVERFLOW_COUNTS:
        if match := pattern.search(text):
            sizes = (
                f" ({_count(match['sent']):,} tokens sent, the model accepts "
                f"{_count(match['max']):,})"
            )
            break
    return (
        f"{CONTEXT_OVERFLOW_LABEL}: this conversation no longer fits in the "
        f"model's context window{sizes}. Start a new conversation, switch to a "
        "model with a larger context window, or enable tool discovery on the "
        "agent so fewer tool definitions are sent with each request."
    )


def _is_overloaded(exc: BaseException) -> bool:
    status = getattr(exc, "status_code", None)
    return status in (503, 529) or "overloaded" in str(exc).lower()


def describe_model_error(exc: BaseException) -> str | None:
    """A readable run error for a provider failure, or None when `exc` isn't
    one (the caller keeps its own message)."""
    for error in _chain(exc):
        text = str(error)
        if isinstance(error, ContextOverflowError) or (
            isinstance(error, ModelError)
            and not isinstance(error, ModelRateLimitError)
            and any(marker in text.lower() for marker in _OVERFLOW_MARKERS)
        ):
            return context_overflow_error(text)
        if isinstance(error, ModelRateLimitError):
            return (
                "Model rate limit reached: the provider is refusing more "
                "requests for now. Wait a minute and send your message again."
            )
        if isinstance(error, ModelAPIError) and _is_overloaded(error):
            return (
                "Model provider overloaded: the provider is temporarily over "
                "capacity. Try again in a few minutes or switch to another model."
            )
        if isinstance(error, ModelAPIError):
            return (
                "Model provider error: the provider failed to answer. Try again "
                "in a moment or switch to another model."
            )
        if isinstance(error, (ModelTimeoutError, ModelConnectionError)):
            return (
                "Model provider unreachable: the request to the provider timed "
                "out or lost its connection. Try again in a moment."
            )
        if isinstance(error, ModelAuthenticationError):
            return (
                "Model provider rejected the API key: ask a workspace admin to "
                "check the provider configuration."
            )
        if isinstance(error, ModelPermissionDeniedError):
            return (
                "Model access denied: the provider API key is not allowed to use "
                "this model. Ask a workspace admin or switch to another model."
            )
        if isinstance(error, ModelNotFoundError):
            return (
                "Model not found: the provider no longer serves this model. "
                "Switch to another model."
            )
    return None
