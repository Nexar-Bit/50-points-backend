import traceback

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.routers import admin, auth, leaderboard, profile, races, tickets, tournaments

app = FastAPI(title="50points API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
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
