import base64

from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from py_vapid import Vapid
from pydantic import model_validator
from pydantic_settings import BaseSettings

from app.settings import settings_config


class WebPushSettings(BaseSettings):
    vapid_public_key: str = ""
    vapid_private_key: str = ""
    vapid_subject: str = ""
    delivery_interval_seconds: float = 0.5
    max_attempts: int = 5
    ttl_seconds: int = 3600

    @property
    def enabled(self) -> bool:
        return bool(
            self.vapid_public_key and self.vapid_private_key and self.vapid_subject
        )

    @model_validator(mode="after")
    def validate_vapid_configuration(self) -> WebPushSettings:
        configured = (
            self.vapid_public_key,
            self.vapid_private_key,
            self.vapid_subject,
        )
        if not any(configured):
            return self
        if not all(configured):
            raise ValueError(
                "WEB_PUSH_VAPID_PUBLIC_KEY, WEB_PUSH_VAPID_PRIVATE_KEY and "
                "WEB_PUSH_VAPID_SUBJECT must be configured together."
            )
        if not self.vapid_subject.startswith(("mailto:", "https://")):
            raise ValueError("WEB_PUSH_VAPID_SUBJECT must be a mailto: or HTTPS URI.")
        try:
            padding = "=" * (-len(self.vapid_public_key) % 4)
            public_key = base64.urlsafe_b64decode(self.vapid_public_key + padding)
            if len(public_key) != 65 or public_key[0] != 4:
                raise ValueError
            vapid = Vapid.from_string(self.vapid_private_key)
            derived_public_key = vapid.public_key.public_bytes(
                Encoding.X962,
                PublicFormat.UncompressedPoint,
            )
            if derived_public_key != public_key:
                raise ValueError
        except Exception as exc:
            raise ValueError("The configured VAPID key pair is invalid.") from exc
        return self

    model_config = settings_config(env_prefix="web_push_")


web_push_settings = WebPushSettings()
