from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings

from app.settings import settings_config


class AgentSettings(BaseSettings):
    recursion_limit: int = Field(
        default=50,
        validation_alias=AliasChoices(
            "AGENT_RECURSION_LIMIT",
            "RECURSION_LIMIT",
        ),
    )

    model_config = settings_config()


agent_settings: AgentSettings = AgentSettings()
