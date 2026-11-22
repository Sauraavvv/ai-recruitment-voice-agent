#!/usr/bin/env bash
# Isolated backend for the Playwright E2E test (phase-08 §7): its own database
# (recruitment_ai_e2e, recreated each run), Redis db 1, and NO provider keys, so nothing is
# dialed and nothing reaches the real Google Sheet. Started by playwright.config.ts.
set -euo pipefail
cd "$(dirname "$0")/../../../backend"

export APP_ENV=test
export APP_SECRET_KEY="e2e-only-secret-key-0123456789abcdefgh"
export DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5433/recruitment_ai_e2e"
export REDIS_URL="redis://localhost:6380/1"
export FRONTEND_ORIGIN="http://localhost:3011"
export FRONTEND_URL="http://localhost:3011"
export TTS_PRELOAD=false
# Calling hours all day, every day: the page shows the same reasons whatever the time of day
export CALLING_DAYS="mon,tue,wed,thu,fri,sat,sun"
export CALLING_HOUR_START=0
export CALLING_HOUR_END=24
# Empty = not configured (overrides anything in an .env file)
for name in OPENAI_API_KEY DEEPGRAM_API_KEY EXOTEL_API_KEY EXOTEL_API_TOKEN EXOTEL_ACCOUNT_SID \
  EXOTEL_SUBDOMAIN EXOTEL_CALLER_ID EXOTEL_APP_ID PUBLIC_BACKEND_URL \
  GOOGLE_SERVICE_ACCOUNT_JSON GOOGLE_SHEET_ID TELEPHONY_CAPTURE_DIR; do
  export "$name="
done

.venv/bin/python - <<'PY'
import asyncio
from app.tests.conftest import ensure_database
asyncio.run(ensure_database("postgresql+asyncpg://postgres:postgres@localhost:5433/recruitment_ai_e2e", recreate=True))
PY
.venv/bin/alembic upgrade head >/dev/null
echo "e2e-only-password-123" | .venv/bin/python -m app.scripts.create_user \
  --email e2e@example.com --name "E2E Admin" --role super_admin
exec .venv/bin/uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8011
