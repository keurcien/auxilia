from langfuse import Langfuse
from langfuse.langchain import CallbackHandler

from app.integrations.langfuse.settings import langfuse_settings


def _build_langfuse() -> tuple[Langfuse | None, CallbackHandler | None]:
    if not (
        langfuse_settings.langfuse_base_url
        and langfuse_settings.langfuse_public_key
        and langfuse_settings.langfuse_secret_key
    ):
        return None, None

    client = Langfuse(
        public_key=langfuse_settings.langfuse_public_key,
        secret_key=langfuse_settings.langfuse_secret_key,
        host=langfuse_settings.langfuse_base_url,
        timeout=langfuse_settings.langfuse_timeout,
    )
    return client, CallbackHandler()


langfuse, langfuse_callback_handler = _build_langfuse()
