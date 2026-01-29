from pathlib import Path

from pydantic_settings import BaseSettings

BASE_DIR = Path(__file__).resolve().parent.parent
ROOT_ENV = BASE_DIR.parent / ".env"


class AppSettings(BaseSettings):
    # Database Configuration
    database_url: str = "postgresql+psycopg://auxilia:auxilia@localhost:5432/auxilia"

    # Redis Configuration
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0

    class Config:
        env_file = ROOT_ENV
        extra = "ignore"


app_settings = AppSettings()