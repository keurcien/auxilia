from mcp.client.auth import TokenStorage
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken, OAuthMetadata
from redis.asyncio import Redis
from datetime import datetime, timezone, timedelta
from pydantic import BaseModel



class StoredToken(BaseModel):
    token_payload: OAuthToken
    expires_at: datetime


class RedisTokenStorage(TokenStorage):
    """Redis-backed token storage."""

    def __init__(
        self,
        mcp_server_id: str,
        *,
        host: str = "localhost",
        port: int = 6379,
        db: int = 0,
        prefix: str = "mcp",
        redis: Redis | None = None,
    ):
        self.mcp_server_id = mcp_server_id
        self.redis: Redis = redis or Redis(
            host=host, port=port, db=db, decode_responses=True
        )
        self._prefix = prefix

    def _base(self) -> str:
        return f"{self._prefix}:{self.mcp_server_id}"

    def _verifiers_key(self) -> str:
        return f"{self._base()}:verifiers"

    def _tokens_key(self) -> str:
        return f"{self._base()}:tokens"

    def _client_info_key(self) -> str:
        return f"{self._base()}:client_info"

    def _oauth_metadata_key(self) -> str:
        return f"{self._base()}:oauth_metadata"

    async def get_verifier(self, state: str) -> str | None:
        return await self.redis.hget(self._verifiers_key(), state)

    async def set_verifier(self, state: str, verifier: str) -> None:
        await self.redis.hset(self._verifiers_key(), state, verifier)

    async def delete_verifier(self, state: str) -> None:
        await self.redis.hdel(self._verifiers_key(), state)

    async def get_tokens(self) -> OAuthToken | None:
        stored_token = await self.redis.get(self._tokens_key())
        if not stored_token:
            print(f"No stored token for MCP server {self.mcp_server_id}")
            return None

        stored_token = StoredToken.model_validate_json(stored_token)
        
        if stored_token.expires_at is not None:
            print(f"Stored token for MCP server {self.mcp_server_id} expires at {stored_token.expires_at}")
            now = datetime.now(timezone.utc)
            # if now >= stored_token.expires_at:
            #     return None

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

    async def aclose(self) -> None:
        await self.redis.close()


class TokenStorageFactory:
    """Factory for creating token storage instances."""

    def __init__(self):
        self.redis = Redis(host="localhost", port=6379, db=0, decode_responses=True)

    def get_storage(self, mcp_server_id: str) -> RedisTokenStorage:
        return RedisTokenStorage(mcp_server_id)
