import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session, joinedload

from app.auth_utils import get_bearer_user
from app.database import get_db
from app.models import (
    AchievementCard,
    LeaderboardEntry,
    Race,
    Ticket,
    Tournament,
    User,
    UserStats,
)

router = APIRouter(prefix="/profile", tags=["profile"])

STRATEGY_LABELS = {
    "full_point": "Full Point",
    "dual_point": "Dual Point",
    "smart_pick": "Smart Point",
}


def _global_rank(db: Session, user_id: int, stats: UserStats | None) -> int:
    if not stats:
        return 0
    higher = db.query(UserStats).filter(UserStats.totalPoints > stats.totalPoints).count()
    return higher + 1


def _map_ticket(t):
    picks = json.loads(t.picks)
    horse_names = [h.name for h in t.race.horses if h.id in picks]
    return {
        "id": t.id,
        "race": t.race.name or f"Race {t.race.raceNumber}",
        "track": (t.race.tournament.track if t.race.tournament else None)
        or (t.race.tournament.name if t.race.tournament else "—"),
        "tournamentId": t.tournamentId,
        "tournamentName": t.race.tournament.name if t.race.tournament else "—",
        "tournamentSlug": t.race.tournament.slug if t.race.tournament else None,
        "strategy": STRATEGY_LABELS.get(t.strategy, t.strategy),
        "strategyKey": t.strategy,
        "horses": horse_names,
                "pointsEarned": max(0, t.pointsEarned or 0),
        "isScored": t.isScored,
        "createdAt": t.createdAt.isoformat() if t.createdAt else None,
        "date": t.createdAt.strftime("%d %b %Y") if t.createdAt else "—",
    }


def _strategy_stats(tickets):
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
    return strategy_stats


def _tournament_summaries(tickets):
    by_tid: dict[int, dict] = {}
    for t in tickets:
        tid = t.tournamentId
        tour = t.race.tournament if t.race else None
        if tid not in by_tid:
            by_tid[tid] = {
                "tournamentId": tid,
                "name": tour.name if tour else "Torneo",
                "slug": tour.slug if tour else None,
                "track": tour.track if tour else "—",
                "location": tour.location if tour else None,
                "status": tour.status if tour else "completed",
                "ticketCount": 0,
                "totalPoints": 0,
                "wins": 0,
                "lastPlayed": t.createdAt.isoformat() if t.createdAt else None,
            }
        row = by_tid[tid]
        row["ticketCount"] += 1
        row["totalPoints"] += t.pointsEarned
        if t.pointsEarned > 0:
            row["wins"] += 1
        if t.createdAt and (
            not row["lastPlayed"] or t.createdAt.isoformat() > row["lastPlayed"]
        ):
            row["lastPlayed"] = t.createdAt.isoformat()
    return sorted(by_tid.values(), key=lambda x: x.get("lastPlayed") or "", reverse=True)


def _user_payload(user: User, stats: UserStats | None, global_rank: int, include_email: bool = False):
    data = {
        "id": user.id,
        "username": user.username,
        "avatarColor": user.avatarColor,
        "isGuest": user.isGuest,
        "gameMode": user.gameMode,
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
    }
    if include_email:
        data["email"] = user.email
    return data


def _load_user_tickets(db: Session, user_id: int, limit: int = 50):
    return (
        db.query(Ticket)
        .options(
            joinedload(Ticket.race).joinedload(Race.horses),
            joinedload(Ticket.race).joinedload(Race.tournament),
        )
        .filter(Ticket.userId == user_id)
        .order_by(Ticket.createdAt.desc())
        .limit(limit)
        .all()
    )


def _achievement_cards_list(db: Session, user_id: int):
    rows = (
        db.query(AchievementCard)
        .filter(AchievementCard.userId == user_id)
        .order_by(AchievementCard.earnedAt.desc())
        .all()
    )
    cards = []
    for row in rows:
        try:
            cards.append(json.loads(row.payload))
        except json.JSONDecodeError:
            continue
    return cards


def _build_ranking_tab(db: Session, tournament: Tournament, user_id: int) -> dict | None:
    rows = (
        db.query(LeaderboardEntry, User)
        .join(User, User.id == LeaderboardEntry.userId)
        .filter(LeaderboardEntry.tournamentId == tournament.id)
        .order_by(
            LeaderboardEntry.totalPoints.desc(),
            LeaderboardEntry.bestStreak.desc(),
            LeaderboardEntry.racesPlayed.desc(),
        )
        .all()
    )
    if not rows:
        has_tickets = (
            db.query(Ticket.id)
            .filter(Ticket.userId == user_id, Ticket.tournamentId == tournament.id)
            .first()
        )
        if not has_tickets:
            return None
        return {
            "tournamentId": tournament.id,
            "slug": tournament.slug,
            "name": tournament.name,
            "track": tournament.track,
            "location": tournament.location,
            "status": tournament.status,
            "currentRace": tournament.currentRace,
            "totalRaces": tournament.totalRaces,
            "statusKey": "tracking",
            "leader": None,
            "top3": [],
            "userTickets": [],
            "bestRank": None,
            "turnSecondsRemaining": None,
            "participantCount": 0,
        }

    leaderboard = []
    for rank, (entry, user) in enumerate(rows, start=1):
        leaderboard.append(
            {
                "rank": rank,
                "userId": user.id,
                "username": user.username,
                "avatarColor": user.avatarColor,
                "ticketNumber": entry.ticketNumber,
                "totalPoints": entry.totalPoints,
                "racesPlayed": entry.racesPlayed,
                "winStreak": entry.winStreak,
            }
        )

    user_entries = [e for e in leaderboard if e["userId"] == user_id]
    if not user_entries:
        has_tickets = (
            db.query(Ticket.id)
            .filter(Ticket.userId == user_id, Ticket.tournamentId == tournament.id)
            .first()
        )
        if not has_tickets:
            return None
        user_entries = []

    best_user_rank = min((e["rank"] for e in user_entries), default=None)
    leader = leaderboard[0] if leaderboard else None
    top3 = leaderboard[:3]

    if tournament.status == "completed" and best_user_rank == 1:
        status = "won"
    elif best_user_rank == 1:
        status = "leading"
    elif tournament.status == "live":
        status = "live"
    else:
        status = "tracking"

    turn_seconds = None
    if tournament.status == "live" and tournament.totalRaces:
        remaining = max(0, tournament.totalRaces - (tournament.currentRace or 0))
        turn_seconds = min(600, max(120, remaining * 90))

    return {
        "tournamentId": tournament.id,
        "slug": tournament.slug,
        "name": tournament.name,
        "track": tournament.track,
        "location": tournament.location,
        "status": tournament.status,
        "currentRace": tournament.currentRace,
        "totalRaces": tournament.totalRaces,
        "statusKey": status,
        "leader": leader,
        "top3": top3,
        "userTickets": sorted(user_entries, key=lambda e: e.get("ticketNumber") or 0),
        "bestRank": best_user_rank,
        "turnSecondsRemaining": turn_seconds,
        "participantCount": len({e["userId"] for e in leaderboard}),
    }


@router.get("/ranking-tabs")
def ranking_tabs(payload: dict = Depends(get_bearer_user), db: Session = Depends(get_db)):
    """Live ranking-system tabs for each tournament the player is in."""
    user_id = payload["userId"]

    entry_tids = {
        row[0]
        for row in db.query(LeaderboardEntry.tournamentId)
        .filter(LeaderboardEntry.userId == user_id)
        .distinct()
        .all()
    }
    ticket_tids = {
        row[0]
        for row in db.query(Ticket.tournamentId).filter(Ticket.userId == user_id).distinct().all()
    }
    tournament_ids = entry_tids | ticket_tids
    if not tournament_ids:
        return {"tabs": []}

    tournaments = (
        db.query(Tournament)
        .filter(Tournament.id.in_(tournament_ids))
        .order_by(Tournament.date.desc())
        .all()
    )

    status_order = {"live": 0, "open": 1, "upcoming": 2, "completed": 3}
    tabs = []
    for t in tournaments:
        tab = _build_ranking_tab(db, t, user_id)
        if tab:
            tabs.append(tab)

    tabs.sort(
        key=lambda x: (
            status_order.get(x["status"], 9),
            x["bestRank"] if x["bestRank"] is not None else 999,
        )
    )
    return {"tabs": tabs}


@router.get("")
def profile(payload: dict = Depends(get_bearer_user), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == payload["userId"]).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    stats = db.query(UserStats).filter(UserStats.userId == user.id).first()
    tickets = _load_user_tickets(db, user.id)
    mapped = [_map_ticket(t) for t in tickets]
    global_rank = _global_rank(db, user.id, stats)

    return {
        "user": _user_payload(user, stats, global_rank, include_email=True),
        "recentTickets": mapped[:10],
        "strategyStats": _strategy_stats(tickets),
        "allTickets": mapped,
        "tournamentSummaries": _tournament_summaries(tickets),
        "achievementCards": _achievement_cards_list(db, user.id),
    }


@router.get("/public/{user_id}")
def public_profile(user_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    stats = db.query(UserStats).filter(UserStats.userId == user.id).first()
    tickets = _load_user_tickets(db, user.id, limit=30)
    global_rank = _global_rank(db, user.id, stats)

    return {
        "user": _user_payload(user, stats, global_rank, include_email=False),
        "strategyStats": _strategy_stats(tickets),
        "tournamentSummaries": _tournament_summaries(tickets),
        "achievementCards": _achievement_cards_list(db, user.id),
        "ticketCount": len(tickets),
    }


class AchievementCardBody(BaseModel):
    id: str
    type: str | None = None
    place: int | None = None
    playerName: str | None = None
    playerColor: str | None = None
    tournamentName: str | None = None
    tournamentSlug: str | None = None
    track: str | None = None
    location: str | None = None
    date: str | None = None
    points: int | None = None
    featName: str | None = None
    featNameEn: str | None = None
    earnedAt: str | None = None


@router.post("/achievement-cards")
def save_achievement_card(
    body: AchievementCardBody,
    payload: dict = Depends(get_bearer_user),
    db: Session = Depends(get_db),
):
    user_id = payload["userId"]
    existing = (
        db.query(AchievementCard)
        .filter(AchievementCard.userId == user_id, AchievementCard.cardId == body.id)
        .first()
    )
    card_json = json.dumps(body.model_dump())
    if existing:
        existing.payload = card_json
        db.commit()
        return {"ok": True, "created": False}

    row = AchievementCard(userId=user_id, cardId=body.id, payload=card_json)
    db.add(row)
    db.commit()
    return {"ok": True, "created": True}


@router.get("/public/{user_id}/achievement-cards")
def public_achievement_cards(user_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {"cards": _achievement_cards_list(db, user_id)}
