from langfuse import Langfuse
from langfuse.langchain import CallbackHandler
from app.integrations.langfuse.settings import langfuse_settings


if langfuse_settings.langfuse_base_url and langfuse_settings.langfuse_public_key and langfuse_settings.langfuse_secret_key:
    langfuse = Langfuse(
        public_key=langfuse_settings.langfuse_public_key,
        secret_key=langfuse_settings.langfuse_secret_key,
        host=langfuse_settings.langfuse_base_url
    )
    langfuse_callback_handler = CallbackHandler()
else:
    langfuse_callback_handler = None
