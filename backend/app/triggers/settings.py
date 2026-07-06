from pathlib import Path

from pydantic import ConfigDict
from pydantic_settings import BaseSettings


BASE_DIR = Path(__file__).resolve().parent.parent.parent
ROOT_ENV = BASE_DIR.parent / ".env"


class TriggerSettings(BaseSettings):
    """Trigger-scanner tunables. Env vars are prefixed `TRIGGER_`."""

    # Whether this process runs the in-process due-trigger scanner. Only
    # honored where the run dispatcher runs (always-on worker instances).
    scanner_enabled: bool = True
    # How often the scanner looks for due triggers — the upper bound on how
    # late an occurrence fires. Cron granularity is one minute, so anything
    # well under 60s is enough.
    scan_interval_seconds: int = 20
    # Max triggers claimed per tick per instance (backpressure on the run queue).
    claim_batch_size: int = 50

    model_config: ConfigDict = ConfigDict(
        env_prefix="trigger_", env_file=ROOT_ENV, extra="ignore"
    )


trigger_settings: TriggerSettings = TriggerSettings()
