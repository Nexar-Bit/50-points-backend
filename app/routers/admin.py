from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, joinedload

from app.auth_utils import require_admin
from app.database import get_db
from app.models import Horse, Race
from app.routers.races import post_race_result
from app.seed import run_seed
from app.services.tournament_sync import sync_live_tournaments

router = APIRouter(prefix="/admin", tags=["admin"])


class SimulateRaceResultBody(BaseModel):
    raceId: int
    winnerHorseId: int
    officialDividend: float = Field(gt=0)


@router.post("/seed", dependencies=[Depends(require_admin)])
def seed_database(db: Session = Depends(get_db)):
    return run_seed(db)


@router.post("/sync-racing", dependencies=[Depends(require_admin)])
def sync_racing(db: Session = Depends(get_db)):
    """Pull live racecards from public racing sites and update tournaments."""
    return sync_live_tournaments(db, force=True)


@router.post("/simulate/race-result", dependencies=[Depends(require_admin)])
def simulate_race_result(body: SimulateRaceResultBody, db: Session = Depends(get_db)):
    """Set winner + dividend, then score all picks for that race."""
    race = (
        db.query(Race)
        .options(joinedload(Race.horses))
        .filter(Race.id == body.raceId)
        .first()
    )
    if not race:
        raise HTTPException(status_code=404, detail="Race not found")

    horses = sorted(race.horses, key=lambda h: h.postPosition)
    winner = db.query(Horse).filter(Horse.id == body.winnerHorseId, Horse.raceId == body.raceId).first()
    if not winner:
        raise HTTPException(status_code=400, detail="Winner horse not in this race")

    winner.odds = float(body.officialDividend)
    db.flush()

    others = [h for h in horses if h.id != winner.id]
    if len(others) < 2:
        raise HTTPException(status_code=400, detail="Need at least 3 horses to post results")

    results = [
        {"position": 1, "horseId": winner.id},
        {"position": 2, "horseId": others[0].id},
        {"position": 3, "horseId": others[1].id},
    ]
    return post_race_result(body.raceId, results, db)
