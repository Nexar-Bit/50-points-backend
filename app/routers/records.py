from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.data.records_catalog import RECORDS_CATALOG
from app.database import get_db
from app.models import LeaderboardEntry, Tournament, User, UserStats

router = APIRouter(prefix="/records", tags=["records"])


def _holder_for_record(db: Session, record: dict) -> dict | None:
    rid = record["id"]
    if rid == "points-1k":
        row = db.query(UserStats, User).join(User, User.id == UserStats.userId).filter(UserStats.totalPoints >= 1000).order_by(UserStats.totalPoints.desc()).first()
    elif rid == "points-5k":
        row = db.query(UserStats, User).join(User, User.id == UserStats.userId).filter(UserStats.totalPoints >= 5000).order_by(UserStats.totalPoints.desc()).first()
    elif rid.startswith("king-"):
        track = record.get("track")
        if not track:
            return None
        t_ids = [t.id for t in db.query(Tournament).filter(Tournament.track == track).all()]
        if not t_ids:
            return None
        row = (
            db.query(LeaderboardEntry, User)
            .join(User, User.id == LeaderboardEntry.userId)
            .filter(LeaderboardEntry.tournamentId.in_(t_ids))
            .order_by(LeaderboardEntry.totalPoints.desc())
            .first()
        )
    else:
        row = (
            db.query(UserStats, User)
            .join(User, User.id == UserStats.userId)
            .order_by(UserStats.totalPoints.desc(), UserStats.bestStreak.desc())
            .first()
        )

    if not row:
        return None
    stats_or_entry, user = row
    points = getattr(stats_or_entry, "totalPoints", 0)
    return {
        "username": user.username,
        "avatarColor": user.avatarColor,
        "value": points,
    }


@router.get("")
def list_records(db: Session = Depends(get_db)):
    records = []
    for item in RECORDS_CATALOG:
        holder = _holder_for_record(db, item)
        records.append(
            {
                **item,
                "holder": holder,
                "unlocked": holder is not None,
            }
        )
    return {"records": records, "total": len(records)}
