import logging
import traceback
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.database import Base, SessionLocal, engine
from app.models import (  # noqa: F401
    AchievementCard,
    Group,
    GroupHologram,
    GroupHologramCooldown,
    GroupMember,
    Horse,
    LeaderboardEntry,
    Race,
    RaceResult,
    Ticket,
    Tournament,
    User,
    UserStats,
)
from app.routers import admin, auth, groups, leaderboard, profile, races, records, statistics, tickets, tournaments
from app.seed import ensure_seeded_if_empty
from app.services.tournament_sync import run_sync_job, start_background_sync, stop_background_sync

logger = logging.getLogger(__name__)


def _ensure_leaderboard_columns():
    """SQLite dev DB only: add rank snapshot columns if missing."""
    from sqlalchemy import inspect, text

    if not str(engine.url).startswith("sqlite"):
        return

    try:
        insp = inspect(engine)
        if "LeaderboardEntry" not in insp.get_table_names():
            return
        cols = {c["name"] for c in insp.get_columns("LeaderboardEntry")}
        alters = []
        if "previousRank" not in cols:
            alters.append("ALTER TABLE LeaderboardEntry ADD COLUMN previousRank INTEGER")
        if "rankChange" not in cols:
            alters.append("ALTER TABLE LeaderboardEntry ADD COLUMN rankChange INTEGER DEFAULT 0")
        if "lastPointsChange" not in cols:
            alters.append("ALTER TABLE LeaderboardEntry ADD COLUMN lastPointsChange INTEGER DEFAULT 0")
        if not alters:
            return
        with engine.begin() as conn:
            for sql in alters:
                conn.execute(text(sql))
    except Exception:
        pass


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Base.metadata.create_all(bind=engine)
    _ensure_leaderboard_columns()
    db = SessionLocal()
    try:
        ensure_seeded_if_empty(db)
    finally:
        db.close()

    try:
        await __import__("asyncio").to_thread(run_sync_job)
    except Exception:
        logger.exception("Initial racing sync failed on startup; API will continue")
    sync_task = start_background_sync()

    yield

    stop_background_sync()
    if sync_task and not sync_task.done():
        sync_task.cancel()
        try:
            await sync_task
        except Exception:
            pass


app = FastAPI(title="50points API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_origin_regex=settings.cors_origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

api_prefix = "/api"


@app.get("/")
def root():
    return {
        "name": "50points API",
        "docs": "/docs",
        "health": "/health",
        "api": "/api",
    }


@app.get(api_prefix)
def api_root():
    return {
        "message": "50points API",
        "docs": "/docs",
        "endpoints": {
            "auth": {
                "POST /api/auth/login": "Login",
                "POST /api/auth/register": "Register",
                "POST /api/auth/guest": "Guest session",
                "GET /api/auth/me": "Current user (Bearer token)",
            },
            "tournaments": {
                "GET /api/tournaments": "List tournaments",
                "GET /api/tournaments/{slug}": "Tournament detail",
                "GET /api/tournaments/{slug}/leaderboard": "Tournament leaderboard",
            },
            "tickets": {
                "GET /api/tickets": "User tickets (auth)",
                "POST /api/tickets": "Submit ticket (auth)",
            },
            "leaderboard": {
                "GET /api/leaderboard": "Global legends",
            },
            "profile": {
                "GET /api/profile": "User profile (auth)",
            },
            "admin": {
                "POST /api/admin/seed": "Seed database (x-admin-secret)",
            },
            "races": {
                "POST /api/races/{race_id}/result": "Score race (x-admin-secret)",
            },
        },
    }


app.include_router(auth.router, prefix=api_prefix)
app.include_router(tournaments.router, prefix=api_prefix)
app.include_router(tickets.router, prefix=api_prefix)
app.include_router(leaderboard.router, prefix=api_prefix)
app.include_router(profile.router, prefix=api_prefix)
app.include_router(admin.router, prefix=api_prefix)
app.include_router(races.router, prefix=api_prefix)
app.include_router(statistics.router, prefix=api_prefix)
app.include_router(records.router, prefix=api_prefix)
app.include_router(groups.router, prefix=api_prefix)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.exception_handler(Exception)
async def unhandled_exception(_request: Request, exc: Exception):
    if settings.environment == "development":
        return JSONResponse(
            status_code=500,
            content={"detail": str(exc), "traceback": traceback.format_exc()},
        )
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})
