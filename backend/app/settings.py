from pathlib import Path

from pydantic_settings import BaseSettings

BASE_DIR = Path(__file__).resolve().parent.parent
ROOT_ENV = BASE_DIR.parent / ".env"


class AppSettings(BaseSettings):
    # Database Configuration
    database_url: str = "postgresql+psycopg://auxilia:auxilia@localhost:5432/auxilia"

    class Config:
        env_file = ROOT_ENV
        extra = "ignore"


app_settings = AppSettings()

