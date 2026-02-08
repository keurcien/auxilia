from mcp.client.auth import TokenStorage
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken, OAuthMetadata
from redis.asyncio import Redis
from datetime import datetime, timezone, timedelta
from pydantic import BaseModel

from app.settings import app_settings


class StoredToken(BaseModel):
    token_payload: OAuthToken
    expires_at: datetime | None = None


class OAuthStateData(BaseModel):
    """Data stored against an OAuth state parameter."""
    user_id: str
    mcp_server_id: str
    verifier: str


class RedisTokenStorage(TokenStorage):
    """Redis-backed token storage keyed by user_id:mcp_server_id."""

    def __init__(
        self,
        user_id: str,
        mcp_server_id: str,
        *,
        host: str = "localhost",
        port: int = 6379,
        db: int = 0,
        prefix: str = "mcp",
        redis: Redis | None = None,
    ):
        self.user_id = user_id
        self.mcp_server_id = mcp_server_id
        self.redis: Redis = redis or Redis(
            host=host, port=port, db=db, decode_responses=True
        )
        self._prefix = prefix

    def _base(self) -> str:
        return f"{self._prefix}:{self.user_id}:{self.mcp_server_id}"

    def _tokens_key(self) -> str:
        return f"{self._base()}:tokens"

    def _client_info_key(self) -> str:
        return f"{self._base()}:client_info"

    def _oauth_metadata_key(self) -> str:
        return f"{self._base()}:oauth_metadata"

    @staticmethod
    def _state_key(state: str, prefix: str = "mcp") -> str:
        """Global state key (not scoped to user/server since we need to look up by state)."""
        return f"{prefix}:oauth_states:{state}"

    async def get_stored_token(self) -> StoredToken | None:
        """Get the raw stored token including the absolute expires_at timestamp."""
        raw = await self.redis.get(self._tokens_key())
        if not raw:
            return None
        return StoredToken.model_validate_json(raw)

    async def get_tokens(self) -> OAuthToken | None:
        stored_token = await self.redis.get(self._tokens_key())
        if not stored_token:
            print(f"No stored token for user {self.user_id} and MCP server {self.mcp_server_id}")
            return None

        stored_token = StoredToken.model_validate_json(stored_token)
        
        if stored_token.expires_at is not None:
            print(f"Stored token for user {self.user_id} and MCP server {self.mcp_server_id} expires at {stored_token.expires_at}")
            now = datetime.now(timezone.utc)

            if stored_token.token_payload.expires_in is not None:
                remaining = stored_token.expires_at - now
                stored_token.token_payload.expires_in = max(
                    0, int(remaining.total_seconds())
                )

        return stored_token.token_payload

    async def set_tokens(self, tokens: OAuthToken) -> None:
        expires_at: datetime | None = None

        if tokens.expires_in is not None:
            expires_at = datetime.now(timezone.utc) + timedelta(
                seconds=tokens.expires_in
            )

        stored_token = StoredToken(token_payload=tokens, expires_at=expires_at)

        await self.redis.set(
            self._tokens_key(),
            stored_token.model_dump_json()
        )

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        raw = await self.redis.get(self._client_info_key())
        if not raw:
            return None
        return OAuthClientInformationFull.model_validate_json(raw)

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        await self.redis.set(
            self._client_info_key(),
            client_info.model_dump_json(),
        )

    async def set_oauth_metadata(self, oauth_metadata: OAuthMetadata) -> None:
        await self.redis.set(
            self._oauth_metadata_key(),
            oauth_metadata.model_dump_json(),
        )

    async def get_oauth_metadata(self) -> OAuthMetadata | None:
        raw = await self.redis.get(self._oauth_metadata_key())
        if not raw:
            return None
        return OAuthMetadata.model_validate_json(raw)

    async def set_verifier(self, state: str, verifier: str) -> None:
        """Store OAuth state data including user_id, mcp_server_id, and verifier."""
        state_data = OAuthStateData(
            user_id=self.user_id,
            mcp_server_id=self.mcp_server_id,
            verifier=verifier,
        )
        
        await self.redis.set(
            self._state_key(state, self._prefix),
            state_data.model_dump_json(),
            ex=600,
        )

    async def get_verifier(self, state: str) -> str | None:
        """Get verifier from state data."""
        raw = await self.redis.get(self._state_key(state, self._prefix))
        if not raw:
            return None
        state_data = OAuthStateData.model_validate_json(raw)
        return state_data.verifier

    async def delete_verifier(self, state: str) -> None:
        await self.redis.delete(self._state_key(state, self._prefix))

    async def aclose(self) -> None:
        await self.redis.close()


class TokenStorageFactory:
    """Factory for creating token storage instances."""

    def __init__(self):
        self.redis = Redis(
            host=app_settings.redis_host,
            port=app_settings.redis_port,
            db=app_settings.redis_db,
            decode_responses=True,
        )

    def get_storage(self, user_id: str, mcp_server_id: str) -> RedisTokenStorage:
        return RedisTokenStorage(user_id, mcp_server_id, redis=self.redis)

    async def get_state_data(self, state: str) -> OAuthStateData | None:
        """Retrieve OAuth state data by state parameter."""
        raw = await self.redis.get(RedisTokenStorage._state_key(state))
        if not raw:
            return None
        return OAuthStateData.model_validate_json(raw)

    async def get_storage_from_state(self, state: str) -> tuple[RedisTokenStorage, OAuthStateData] | None:
        """
        Recover storage instance from OAuth state parameter.
        
        Returns:
            Tuple of (storage, state_data) or None if state is invalid/expired.
        """
        state_data = await self.get_state_data(state)
        if not state_data:
            return None
        
        storage = self.get_storage(state_data.user_id, state_data.mcp_server_id)
        return storage, state_data
