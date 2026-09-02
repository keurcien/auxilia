.PHONY: dev-stack migrate dev-backend dev-frontend dev build up down reset rebuild sync-catalog

dev-stack:
	docker compose -f docker-compose.dev.yml up -d --remove-orphans

dev-backend: dev-stack
	until docker exec auxilia-postgres pg_isready -q; do sleep 0.5; done
	cd backend && uv run alembic upgrade head
# --timeout-graceful-shutdown: a reload must not wait forever on the chat
# page's long-lived protocol SSE session (POST /threads/{id}/stream/events);
# uvicorn otherwise blocks the restart until every client disconnects.
	cd backend && uv run uvicorn app.main:app --reload --timeout-graceful-shutdown 5

dev-frontend:
	cd web && npm i
	@echo "Waiting for backend to be ready..."
	@t=0; until curl -sf -o /dev/null http://localhost:8000/docs; do \
		t=$$((t+1)); \
		if [ $$t -ge 600 ]; then echo "Backend still not ready after 5 minutes — check the dev-backend logs."; exit 1; fi; \
		sleep 0.5; \
	done
	cd web && npm run dev

dev:
	make -j 3 dev-stack dev-backend dev-frontend

build:
	docker compose build

rebuild:
	docker compose build --no-cache

up:
	docker compose up -d

down:
	docker compose down

reset:
	docker compose down -v --remove-orphans

# Copy the publishable catalogs (uploaded to the CDN) over the snapshots bundled
# into the backend image. The two must stay byte-identical or the CDN and the
# offline fallback silently diverge — `test_publishable_copy_matches_bundled_snapshot`
# fails otherwise. Run this after editing anything under catalog/.
sync-catalog:
	cp catalog/whitelist.yaml backend/app/model_providers/whitelist.yaml
	cp catalog/catalog.yaml backend/app/mcp/servers/catalog.yaml
	@echo "Bundled snapshots synced from catalog/."
