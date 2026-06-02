from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from typing import Optional

from app.auth_utils import get_bearer_user, optional_bearer_user
from app.database import get_db
from app.models import Tournament
from app.services.statistics import (
    global_statistics,
    personal_statistics,
    race_statistics,
    tournament_statistics,
    track_statistics,
)

router = APIRouter(prefix="/statistics", tags=["statistics"])


@router.get("/race/{race_id}")
def get_race_stats(
    race_id: int,
    db: Session = Depends(get_db),
    payload: Optional[dict] = Depends(optional_bearer_user),
):
    user_id = payload["userId"] if payload else None
    data = race_statistics(db, race_id, user_id=user_id)
    if not data:
        raise HTTPException(status_code=404, detail="Race not found")
    return data


@router.get("/tournament/{tournament_id}")
def get_tournament_stats(tournament_id: int, db: Session = Depends(get_db)):
    data = tournament_statistics(db, tournament_id)
    if not data:
        raise HTTPException(status_code=404, detail="Tournament not found")
    return data


@router.get("/tournament/slug/{slug}")
def get_tournament_stats_by_slug(slug: str, db: Session = Depends(get_db)):
    t = db.query(Tournament).filter(Tournament.slug == slug).first()
    if not t:
        raise HTTPException(status_code=404, detail="Tournament not found")
    return tournament_statistics(db, t.id)


@router.get("/personal")
def get_personal_stats(payload: dict = Depends(get_bearer_user), db: Session = Depends(get_db)):
    return personal_statistics(db, payload["userId"])


@router.get("/track/{track_name}")
def get_track_stats(track_name: str, db: Session = Depends(get_db)):
    data = track_statistics(db, track_name)
    if not data:
        raise HTTPException(status_code=404, detail="Track not found")
    return data


@router.get("/global")
def get_global_stats(db: Session = Depends(get_db)):
    return global_statistics(db)
