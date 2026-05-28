from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth_utils import require_admin
from app.database import get_db
from app.seed import run_seed
from app.services.tournament_sync import sync_live_tournaments

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/seed", dependencies=[Depends(require_admin)])
def seed_database(db: Session = Depends(get_db)):
    return run_seed(db)


@router.post("/sync-racing", dependencies=[Depends(require_admin)])
def sync_racing(db: Session = Depends(get_db)):
    """Pull live racecards from public racing sites and update tournaments."""
    return sync_live_tournaments(db, force=True)
