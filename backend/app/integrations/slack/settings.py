from pydantic_settings import BaseSettings

from app.settings import settings_config


class SlackSettings(BaseSettings):
    slack_signing_secret: str = ""
    slack_bot_token: str = ""

    model_config = settings_config()


slack_settings = SlackSettings()
