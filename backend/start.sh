#!/bin/sh
# Start the API on a hosting platform (Render): apply database migrations, then serve.
# One process: live calls share its state. The platform sets $PORT (default 8000).
set -e
alembic upgrade head
exec uvicorn app.main:create_app --factory --host 0.0.0.0 --port "${PORT:-8000}" \
  --workers 1 --proxy-headers --forwarded-allow-ips "*"
