.PHONY: dev-stack migrate dev-backend dev-frontend dev build up down

dev-stack:
	docker compose -f docker-compose.dev.yml up -d --remove-orphans

dev-backend:
	cd backend && uv run alembic upgrade head
	cd backend && uv run uvicorn app.main:app --reload

dev-frontend:
	cd web && npm run dev

dev:
	make -j 3 dev-stack dev-backend dev-frontend

build:
	docker compose build

up:
	docker compose up -d

down:
	docker compose down