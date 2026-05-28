import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from app.auth_utils import get_bearer_user
from app.database import get_db
from app.models import Race, Ticket, Tournament, User, UserStats

router = APIRouter(prefix="/profile", tags=["profile"])

STRATEGY_LABELS = {
    "full_point": "Full Point",
    "dual_point": "Dual Point",
    "smart_pick": "Smart Pick",
}


@router.get("")
def profile(payload: dict = Depends(get_bearer_user), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == payload["userId"]).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    stats = db.query(UserStats).filter(UserStats.userId == user.id).first()
    tickets = (
        db.query(Ticket)
        .options(
            joinedload(Ticket.race).joinedload(Race.horses),
            joinedload(Ticket.race).joinedload(Race.tournament),
        )
        .filter(Ticket.userId == user.id)
        .order_by(Ticket.createdAt.desc())
        .limit(50)
        .all()
    )

    global_rank = 1
    if stats:
        higher = db.query(UserStats).filter(UserStats.totalPoints > stats.totalPoints).count()
        global_rank = higher + 1

    mapped = []
    for t in tickets:
        picks = json.loads(t.picks)
        horse_names = [h.name for h in t.race.horses if h.id in picks]
        mapped.append(
            {
                "id": t.id,
                "race": t.race.name or f"Race {t.race.raceNumber}",
                "track": (t.race.tournament.track if t.race.tournament else None) or (t.race.tournament.name if t.race.tournament else "—"),
                "strategy": STRATEGY_LABELS.get(t.strategy, t.strategy),
                "strategyKey": t.strategy,
                "horses": horse_names,
                "pointsEarned": t.pointsEarned,
                "isScored": t.isScored,
                "createdAt": t.createdAt.isoformat() if t.createdAt else None,
            }
        )

    strategy_stats = {
        "full_point": {"count": 0, "wins": 0, "points": 0, "totalPoints": 0, "best": 0},
        "dual_point": {"count": 0, "wins": 0, "points": 0, "totalPoints": 0, "best": 0},
        "smart_pick": {"count": 0, "wins": 0, "points": 0, "totalPoints": 0, "best": 0},
    }
    for t in tickets:
        s = strategy_stats.get(t.strategy)
        if not s:
            continue
        s["count"] += 1
        if t.pointsEarned > 0:
            s["wins"] += 1
        s["points"] += t.pointsEarned
        s["totalPoints"] += t.pointsEarned
        s["best"] = max(s["best"], t.pointsEarned)

    return {
        "user": {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "avatarColor": user.avatarColor,
            "isGuest": user.isGuest,
            "createdAt": user.createdAt.isoformat() if user.createdAt else None,
            "globalRank": global_rank,
            "stats": {
                "totalPoints": stats.totalPoints,
                "tournamentsPlayed": stats.tournamentsPlayed,
                "totalRaces": stats.totalRaces,
                "winRate": stats.winRate,
                "bestStreak": stats.bestStreak,
                "titles": stats.titles,
                "records": stats.records,
            }
            if stats
            else None,
        },
        "recentTickets": mapped[:10],
        "strategyStats": strategy_stats,
        "allTickets": mapped,
    }
