import json

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session, joinedload

from app.auth_utils import STRATEGIES, get_bearer_user
from app.constants import LAUNCH_GAME_MODES, MAX_FREE_TICKETS
from app.database import get_db
from app.models import Race, Ticket, User
from app.scoring import get_required_picks

router = APIRouter(prefix="/tickets", tags=["tickets"])


class TicketBody(BaseModel):
    raceId: int
    strategy: str
    picks: list[int]
    ticketNumber: int | None = 1


@router.post("")
def submit_ticket(body: TicketBody, payload: dict = Depends(get_bearer_user), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == payload["userId"]).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    if user.gameMode not in LAUNCH_GAME_MODES:
        raise HTTPException(
            status_code=403,
            detail="Paid tournament modes are not available yet. Use Guest or Registered mode.",
        )

    ticket_number = body.ticketNumber if body.ticketNumber is not None else 1
    if ticket_number not in range(1, MAX_FREE_TICKETS + 1):
        raise HTTPException(status_code=400, detail=f"ticketNumber must be 1–{MAX_FREE_TICKETS}")
    if body.strategy not in STRATEGIES:
        raise HTTPException(status_code=400, detail="Invalid strategy")

    required = get_required_picks(body.strategy)
    if len(body.picks) != required:
        raise HTTPException(status_code=400, detail=f"{body.strategy} requires exactly {required} pick(s)")

    race = db.query(Race).options(joinedload(Race.horses)).filter(Race.id == body.raceId).first()
    if not race:
        raise HTTPException(status_code=404, detail="Race not found")
    if race.status not in ("upcoming", "open"):
        raise HTTPException(status_code=400, detail="Race is no longer accepting picks")

    horse_ids = {h.id for h in race.horses}
    for pick_id in body.picks:
        if pick_id not in horse_ids:
            raise HTTPException(status_code=400, detail=f"Horse {pick_id} is not in this race")
    if len(set(body.picks)) != len(body.picks):
        raise HTTPException(status_code=400, detail="Duplicate picks not allowed")

    existing = (
        db.query(Ticket)
        .filter(
            Ticket.userId == payload["userId"],
            Ticket.raceId == body.raceId,
            Ticket.ticketNumber == ticket_number,
        )
        .first()
    )
    if existing:
        raise HTTPException(status_code=409, detail=f"You already submitted ticket #{ticket_number} for this race")

    ticket = Ticket(
        userId=payload["userId"],
        raceId=body.raceId,
        tournamentId=race.tournamentId,
        ticketNumber=ticket_number,
        strategy=body.strategy,
        picks=json.dumps(body.picks),
    )
    db.add(ticket)
    db.commit()
    db.refresh(ticket)

    return {
        "ticket": {
            "id": ticket.id,
            "raceId": ticket.raceId,
            "ticketNumber": ticket.ticketNumber,
            "strategy": ticket.strategy,
            "picks": body.picks,
            "pointsEarned": 0,
            "isScored": False,
        }
    }


@router.get("")
def list_tickets(
    tournamentId: int | None = Query(default=None),
    payload: dict = Depends(get_bearer_user),
    db: Session = Depends(get_db),
):
    q = (
        db.query(Ticket)
        .options(joinedload(Ticket.race).joinedload(Race.horses), joinedload(Ticket.race).joinedload(Race.results))
        .filter(Ticket.userId == payload["userId"])
    )
    if tournamentId is not None:
        q = q.filter(Ticket.tournamentId == tournamentId)

    tickets = q.order_by(Ticket.createdAt.desc()).all()
    return {
        "tickets": [
            {
                "id": t.id,
                "raceId": t.raceId,
                "raceNumber": t.race.raceNumber,
                "raceName": t.race.name,
                "raceStatus": t.race.status,
                "ticketNumber": t.ticketNumber,
                "strategy": t.strategy,
                "picks": json.loads(t.picks),
                "pointsEarned": t.pointsEarned,
                "isScored": t.isScored,
                "horses": [
                    {
                        "id": h.id,
                        "name": h.name,
                        "odds": h.odds,
                        "postPosition": h.postPosition,
                    }
                    for h in t.race.horses
                ],
                "results": [{"position": r.position, "horseId": r.horseId} for r in t.race.results],
                "createdAt": t.createdAt.isoformat() if t.createdAt else None,
            }
            for t in tickets
        ]
    }
