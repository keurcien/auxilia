.PHONY: dev-stack migrate dev-backend dev-frontend dev build up down reset rebuild

dev-stack:
	docker compose -f docker-compose.dev.yml up -d --remove-orphans

dev-backend:
	until docker exec auxilia-postgres pg_isready -q; do sleep 0.5; done
	cd backend && uv run alembic upgrade head
	cd backend && uv run uvicorn app.main:app --reload

dev-frontend:
	cd web && npm i && npm run dev

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
