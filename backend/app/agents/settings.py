from pydantic_settings import BaseSettings

from app.settings import settings_config


class AgentSettings(BaseSettings):
    recursion_limit: int = 50

    model_config = settings_config()


agent_settings: AgentSettings = AgentSettings()
