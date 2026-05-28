from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User, UserStats

router = APIRouter(prefix="/leaderboard", tags=["leaderboard"])


@router.get("")
def global_leaderboard(
    limit: int = Query(default=100, ge=1, le=500),
    page: int = Query(default=1, ge=1),
    modes: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    q = db.query(UserStats, User).join(User, User.id == UserStats.userId).filter(UserStats.totalPoints > 0)

    if modes:
        mode_list = [int(m) for m in modes.split(",") if m.strip().isdigit()]
        if mode_list:
            q = q.filter(User.gameMode.in_(mode_list))

    total = q.count()
    rows = (
        q.order_by(UserStats.totalPoints.desc(), UserStats.bestStreak.desc(), UserStats.totalRaces.desc())
        .offset((page - 1) * limit)
        .limit(limit)
        .all()
    )

    legends = []
    for i, (stats, user) in enumerate(rows):
        legends.append(
            {
                "rank": (page - 1) * limit + i + 1,
                "userId": user.id,
                "username": user.username,
                "avatarColor": user.avatarColor,
                "isGuest": user.isGuest,
                "gameMode": user.gameMode,
                "totalPoints": stats.totalPoints,
                "tournamentsPlayed": stats.tournamentsPlayed,
                "totalRaces": stats.totalRaces,
                "winRate": stats.winRate,
                "bestStreak": stats.bestStreak,
                "titles": stats.titles,
            }
        )

    return {"legends": legends, "total": total, "page": page, "limit": limit}
