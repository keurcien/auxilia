"""OAuth completion signal with recovery from successfully persisted tokens."""

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse

from redis.asyncio import Redis

from app.mcp.client.storage import RedisTokenStorage, StoredToken, TokenStorageFactory


def oauth_completion_key(state: str) -> str:
    return "mcp:oauth-complete:" + hashlib.sha256(state.encode()).hexdigest()


def _fingerprint(token: StoredToken | None) -> str | None:
    return (
        hashlib.sha256(token.model_dump_json().encode()).hexdigest() if token else None
    )


@dataclass
class OAuthCompletion:
    state: str | None
    redis: Redis
    storage: RedisTokenStorage | None = None
    previous_token: str | None = None

    @classmethod
    async def for_challenge(
        cls, url: str, *, user_id: str, server_ids: set[str], redis: Redis
    ) -> "OAuthCompletion":
        state = parse_qs(urlparse(url).query).get("state", [None])[0]
        completion = cls(state=state, redis=redis)
        if not state:
            return completion
        recovered = await TokenStorageFactory(redis=redis).get_storage_from_state(state)
        if recovered is not None:
            storage, data = recovered
            # Never treat another user's or another server's token as consent.
            if data.user_id == user_id and data.mcp_server_id in server_ids:
                completion.storage = storage
                completion.previous_token = _fingerprint(
                    await storage.get_stored_token()
                )
        return completion

    async def completed(self) -> bool:
        if self.state and await self.redis.get(oauth_completion_key(self.state)):
            return True
        # The callback might exchange and persist tokens, then lose the marker
        # write. A changed, non-expired token for this verified user/server lets
        # the sandbox reconnect without exchanging an already-consumed code.
        if self.storage is None:
            return False
        token = await self.storage.get_stored_token()
        if token is None or (
            token.expires_at is not None and token.expires_at <= datetime.now(UTC)
        ):
            return False
        return _fingerprint(token) != self.previous_token
