from pathlib import Path
from pydantic import ConfigDict
from pydantic_settings import BaseSettings

BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent
ROOT_ENV = BASE_DIR.parent / ".env"


class SlackSettings(BaseSettings):
    slack_signing_secret: str = ""
    slack_bot_token: str = ""

    model_config: ConfigDict = ConfigDict(
        env_file=ROOT_ENV,
        extra="ignore",
    )


slack_settings = SlackSettings()
