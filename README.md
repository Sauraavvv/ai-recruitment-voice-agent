# AI Recruitment Voice Calling Agent

A web platform where recruiters upload candidates and an AI voice agent calls them over a real phone line, runs an initial screening conversation in English, and records structured answers, a transcript and a summary in PostgreSQL and Google Sheets.

**Status:** Phase 1 (database and candidate management) implemented, awaiting review.

## Quick start

```bash
make env   # create .env
make up    # start everything with Docker Compose
make create-user email=you@example.com name="Your Name"
```

Then open http://localhost:3000. Full instructions: [docs/setup.md](docs/setup.md).

## Documentation

- [plan.md](plan.md): technical blueprint
- [docs/phases/](docs/phases/README.md): detailed plan for each development phase
- [docs/architecture.md](docs/architecture.md): processes, data flow, module boundaries
- [docs/api.md](docs/api.md): API conventions and endpoints
- [docs/telephony.md](docs/telephony.md): Exotel enablement and protocol notes

## Stack

Next.js + TypeScript + Tailwind · FastAPI + Pydantic v2 · SQLAlchemy 2 + Alembic · PostgreSQL · Redis + ARQ · OpenAI · Deepgram · Kitten TTS · Exotel · Google Sheets API · Docker Compose
