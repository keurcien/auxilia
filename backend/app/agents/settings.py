from pathlib import Path

from pydantic import ConfigDict
from pydantic_settings import BaseSettings

BASE_DIR = Path(__file__).resolve().parent.parent.parent
ROOT_ENV = BASE_DIR.parent / ".env"


class AgentSettings(BaseSettings):
    recursion_limit: int = 50
    invoke_profiling: bool = False

    model_config: ConfigDict = ConfigDict(
        env_file=ROOT_ENV,
        extra="ignore"
    )


agent_settings: AgentSettings = AgentSettings()
