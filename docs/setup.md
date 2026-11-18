# Local setup

## Prerequisites

| Tool | Version used | Install |
|---|---|---|
| Docker Desktop (with Compose v2) | latest | `brew install --cask docker`, then open Docker once |
| Python | 3.12 (for running backend tests outside Docker) | `brew install python@3.12` |
| uv | 0.13+ | `brew install uv` |
| Node.js | 26 (local); Docker image `node:26-alpine` | `brew install node` |
| git | 2.54 | Xcode command line tools |

Recorded on the development machine (Phase 0, 2026-11-18): macOS 26.6.2, Apple Silicon (`arm64`), Python 3.12.16, Node 26.7.0, npm 11.19.0, git 2.54.0, uv 0.13.9.

Apple Silicon note: Docker builds `linux/arm64` images locally. A production server is likely `linux/amd64`; build and test the backend image for that architecture before Phase 3 adds ONNX-based TTS.

The project folder name contains a space (`project 2`). Quote paths in shell commands and scripts.

## First run

```bash
make env          # creates .env with a random APP_SECRET_KEY (doesn't overwrite an existing .env)
make up           # builds and starts postgres, redis, backend, worker, frontend
make ps           # all services should be "running" / "healthy"
```

| URL | What |
|---|---|
| http://localhost:3000 | Frontend: system status page |
| http://localhost:8000/health | Backend liveness |
| http://localhost:8000/health/ready | Database, Redis and worker readiness |
| http://localhost:8000/docs | API reference (development only) |

Host ports for Postgres and Redis are **5433** and **6380** so they don't clash with local installs. Backend and frontend host ports come from `BACKEND_PORT` and `FRONTEND_PORT` in `.env` (default 8000 / 3000); change them if another app already uses those ports, and keep `FRONTEND_ORIGIN`/`FRONTEND_URL` in step with `FRONTEND_PORT`. On the original dev machine they are **8010** and **3010**.

## Backend tests and checks without Docker

```bash
make venv         # creates backend/.venv with Python 3.12 and installs dependencies
make test         # pytest (the real-services test is skipped unless postgres/redis are running)
make lint         # ruff + eslint
make typecheck    # mypy + tsc
```

## Dependencies

- Backend: edit `backend/requirements.in` or `requirements-dev.in`, then `make lock` (pins exact versions with hashes in `requirements.txt`).
- Frontend: `npm install <pkg>` inside `frontend/`.

## Configuration

All settings come from `.env` (see `.env.example`). The backend refuses to start if a required variable is missing or invalid and prints the variable names. Provider keys (OpenAI, Deepgram, Exotel, Google) can stay empty until their phase.

Never commit `.env`. Run `make check-secrets` (needs `brew install gitleaks`) before committing.

## Common problems

| Symptom | Fix |
|---|---|
| `Invalid configuration… APP_SECRET_KEY: is required` | Run `make env`, or set a 32+ character value in `.env` |
| `/health/ready` shows `worker: error` | Worker not running or just started; check `docker compose logs worker` (heartbeat every 30 s) |
| Port already in use | Stop the other service or change the host port in `docker-compose.yml` |
| Frontend shows "Backend unreachable" | Backend container not up; `docker compose logs backend` |
