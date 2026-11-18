# Run from the repository root. Paths are quoted because the folder name contains a space.
SHELL := /bin/bash
BACKEND := backend
VENV := $(BACKEND)/.venv/bin

.PHONY: help env up down logs ps test test-docker lint fmt typecheck lock venv check-secrets shell-db

help:
	@grep -E '^[a-z-]+:' Makefile | cut -d: -f1 | tr '\n' ' '; echo

env:  ## Create .env with a random APP_SECRET_KEY (won't overwrite an existing .env)
	@if [ -f .env ]; then echo ".env already exists"; else \
	  sed "s|^APP_SECRET_KEY=.*|APP_SECRET_KEY=$$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')|" .env.example > .env; \
	  echo "Created .env"; fi

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f --tail=100

ps:
	docker compose ps

venv:
	cd "$(BACKEND)" && uv venv -p python3.12 .venv -q && uv pip install -q -p .venv -r requirements.txt -r requirements-dev.txt

lock:
	cd "$(BACKEND)" && uv pip compile requirements.in --python-version 3.12 --generate-hashes -o requirements.txt -q \
	  && uv pip compile requirements-dev.in --python-version 3.12 -o requirements-dev.txt -q

test:
	cd "$(BACKEND)" && .venv/bin/pytest -q

test-docker:  ## Runs tests inside the backend container against the real Postgres and Redis
	docker compose exec -T \
	  -e TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@postgres:5432/recruitment_ai \
	  -e TEST_REDIS_URL=redis://redis:6379/0 \
	  backend pytest -q -p no:cacheprovider

lint:
	cd "$(BACKEND)" && .venv/bin/ruff check . && .venv/bin/ruff format --check .
	cd frontend && npm run lint

fmt:
	cd "$(BACKEND)" && .venv/bin/ruff check --fix . && .venv/bin/ruff format .
	cd frontend && npm run format

typecheck:
	cd "$(BACKEND)" && .venv/bin/mypy
	cd frontend && npm run typecheck

check-secrets:
	@if command -v gitleaks >/dev/null; then gitleaks detect --no-banner -v; \
	else echo "gitleaks not installed (brew install gitleaks)"; exit 1; fi

shell-db:
	docker compose exec postgres psql -U postgres -d recruitment_ai
