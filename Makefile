.PHONY: dev-stack migrate dev-backend dev-frontend dev build up down reset rebuild

dev-stack:
	docker compose -f docker-compose.dev.yml up -d --remove-orphans

dev-backend: dev-stack
	until docker exec auxilia-postgres pg_isready -q; do sleep 0.5; done
	cd backend && uv run alembic upgrade head
	cd backend && uv run uvicorn app.main:app --reload

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
