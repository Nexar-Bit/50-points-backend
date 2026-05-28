# BACKEND — 50points API (FastAPI)

Python FastAPI server for authentication, tournaments, tickets, scoring, and leaderboards.

## Setup

```bash
cd BACKEND
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
copy .env.example .env
```

SQLite database: `BACKEND/data/dev.db` (created on first seed).

## Live tournaments (public data)

Live racecards are synced from public sources:

1. **The Racing API** (recommended) — set `RACING_API_USERNAME` / `RACING_API_PASSWORD` in `.env` ([theracingapi.com](https://www.theracingapi.com))
2. **Horse Racing Nation** (fallback scrape) — used automatically when no API key is set

Sync runs automatically when the frontend loads tournaments (`GET /api/tournaments?refresh=1`), or manually:

```bash
curl -X POST http://localhost:8000/api/admin/sync-racing -H "x-admin-secret: change-me-admin-secret"
```

## Run

```bash
uvicorn app.main:app --reload --port 8000
```

API base: `http://localhost:8000/api`

Seed demo data:

```bash
curl -X POST http://localhost:8000/api/admin/seed -H "x-admin-secret: change-me-admin-secret"
```

## Endpoints

| Area | Routes |
|------|--------|
| Auth | `POST /api/auth/login`, `register`, `guest` — `GET /api/auth/me` |
| Tournaments | `GET /api/tournaments`, `/api/tournaments/{slug}`, `.../leaderboard` |
| Tickets | `GET/POST /api/tickets` |
| Leaderboard | `GET /api/leaderboard` |
| Profile | `GET /api/profile` |
| Admin | `POST /api/admin/seed`, `POST /api/races/{id}/result` |
