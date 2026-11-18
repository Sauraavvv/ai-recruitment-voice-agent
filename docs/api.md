# API conventions

Interactive reference (development only): http://localhost:8000/docs

## Versioning

Feature endpoints live under `/api/v1`. Health endpoints are at the root (`/health`, `/health/ready`) for infrastructure probes.

## Response envelope

Success:

```json
{ "data": { ... }, "meta": { "page": 1, "page_size": 25, "total": 120 } }
```

`meta` appears only where it means something (e.g. paginated lists).

Error:

```json
{
  "error": {
    "code": "validation_error",
    "message": "Request validation failed",
    "details": [ ... ],
    "request_id": "3f2c9a..."
  }
}
```

| HTTP | `code` | When |
|---|---|---|
| 401 | `unauthorized` | Not logged in (from Phase 1) |
| 404 | `not_found` | Unknown route or resource |
| 409 | e.g. `duplicate_phone` | Conflicts with existing data |
| 422 | `validation_error` | Request body or parameters invalid; `details` lists fields |
| 500 | `internal_error` | Unexpected error; details are in the server log under `request_id` |
| 503 | — | `/health/ready` when a dependency is down (body still uses `data`) |

## Request ids

Every HTTP response has an `X-Request-ID` header. Send your own (letters, digits, `.`, `_`, `-`, max 64 chars) to correlate logs; otherwise one is generated.

## Pagination (from Phase 1)

Query parameters `page` (1-based) and `page_size` (max 100). Totals in `meta.total`.

## Health

| Endpoint | Purpose | Response |
|---|---|---|
| `GET /health` | Liveness: process is up | `200 {"data": {"status": "ok", "version": "0.0.0"}}` |
| `GET /health/ready` | Readiness: database, Redis and worker heartbeat | `200` when all ok; `503` with `components` showing which failed and a short `errors` reason |

External providers (OpenAI, Deepgram, Exotel, Google Sheets) are not part of readiness; their status will be at `GET /api/v1/settings/status` (Phase 8).
