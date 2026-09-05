"""Exercise the collection URLs used by the Next.js backend proxy."""

import httpx
from fastapi import FastAPI

from app.auth.dependencies import get_current_user
from app.skills.router import router
from app.skills.service import get_skill_service


async def test_collection_uses_trailing_slash():
    class Service:
        async def list(self, user):
            return []

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: object()
    app.dependency_overrides[get_skill_service] = lambda: Service()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/skills/")
        assert response.status_code == 200
        assert response.json() == []
        # POST reaches payload validation directly, without a redirect that
        # the frontend's streaming proxy deliberately does not follow.
        response = await client.post("/skills/", json={})
        assert response.status_code == 422
