from pathlib import Path
from pydantic import ConfigDict
from pydantic_settings import BaseSettings

BASE_DIR = Path(__file__).resolve().parent.parent
ROOT_ENV = BASE_DIR.parent / ".env"


class AppSettings(BaseSettings):
    database_url: str = "postgresql+psycopg://auxilia:auxilia@localhost:5432/auxilia"
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0
    backend_url: str = "http://localhost:8000"

    model_config: ConfigDict = ConfigDict(
        env_file=ROOT_ENV,
        extra="ignore"
    )


app_settings: AppSettings = AppSettings()
