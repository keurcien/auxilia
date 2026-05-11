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
    redis_password: str | None = None
    backend_url: str = "http://localhost:8000"
    log_level: str = "INFO"
    # Per-instance worker count. Each worker is one asyncio task running a
    # dequeue→execute loop, so 8 means up to 8 concurrent agent runs in this
    # process. Horizontal scaling (more Cloud Run instances) multiplies this:
    # cluster capacity = instances × run_worker_concurrency.
    # During astream, workers are mostly async-idle waiting on LLM/MCP HTTP,
    # so the per-instance ceiling can be raised aggressively — tune up if
    # queue depth grows persistently, down if Postgres connections starve.
    run_worker_concurrency: int = 8

    model_config: ConfigDict = ConfigDict(
        env_file=ROOT_ENV,
        extra="ignore"
    )


app_settings: AppSettings = AppSettings()
