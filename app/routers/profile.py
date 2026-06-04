import json
from datetime import datetime, timedelta, timezone

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

DAY_LABELS_EN = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
DAY_LABELS_ES = ["Lun", "Mar", "Mie", "Jue", "Vie", "Sab", "Dom"]

ACHIEVEMENT_CATALOG = [
    {"id": "first_win", "icon": "star", "color": "#f59e0b", "group": "Iniciacion", "groupEn": "Beginner"},
    {"id": "streak_5", "icon": "flame", "color": "#a855f7", "group": "Racha", "groupEn": "Streak"},
    {"id": "daily_top10", "icon": "trending", "color": "#06b6d4", "group": "Ranking", "groupEn": "Ranking"},
    {"id": "full_point_master", "icon": "zap", "color": "#7c3aed", "group": "Full Point", "groupEn": "Full Point"},
    {"id": "smart_pick_pro", "icon": "target", "color": "#f59e0b", "group": "Smart Pick", "groupEn": "Smart Pick"},
    {"id": "comeback_kid", "icon": "trending", "color": "#10b981", "group": "Comeback", "groupEn": "Comeback"},
    {"id": "tournament_champion", "icon": "crown", "color": "#f59e0b", "group": "Dominancia", "groupEn": "Dominance"},
    {"id": "points_1000", "icon": "zap", "color": "#a855f7", "group": "Puntos", "groupEn": "Points"},
    {"id": "perfect_smart", "icon": "shield", "color": "#06b6d4", "group": "Smart Pick", "groupEn": "Smart Pick"},
    {"id": "gulfstream_king", "icon": "crown", "color": "#f59e0b", "group": "Hipodromo", "groupEn": "Racetrack"},
    {"id": "full_point_50x", "icon": "star", "color": "#ef4444", "group": "Legendario", "groupEn": "Legendary"},
    {"id": "vip_hall", "icon": "achievements", "color": "#d97706", "group": "Mitico", "groupEn": "Mythic"},
]


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


def _consecutive_wins(tickets, strategy: str, needed: int) -> bool:
    streak = 0
    for t in sorted(tickets, key=lambda x: x.createdAt or datetime.min.replace(tzinfo=timezone.utc)):
        if t.strategy != strategy:
            streak = 0
            continue
        if (t.pointsEarned or 0) > 0:
            streak += 1
            if streak >= needed:
                return True
        else:
            streak = 0
    return False


def _max_daily_points(tickets) -> int:
    by_day: dict = {}
    for t in tickets:
        if not t.createdAt or not t.isScored:
            continue
        key = t.createdAt.date().isoformat()
        by_day[key] = by_day.get(key, 0) + max(0, t.pointsEarned or 0)
    return max(by_day.values()) if by_day else 0


def _performance_history(tickets):
    """Points earned per day for the last 7 calendar days (UTC)."""
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    days = [today - timedelta(days=i) for i in range(6, -1, -1)]
    totals = {d.date(): 0 for d in days}
    for t in tickets:
        if not t.isScored or not t.createdAt:
            continue
        d = t.createdAt.date()
        if d in totals:
            totals[d] += max(0, t.pointsEarned or 0)
    return [
        {
            "day": DAY_LABELS_EN[d.weekday()],
            "dayEs": DAY_LABELS_ES[d.weekday()],
            "points": totals[d.date()],
            "date": d.date().isoformat(),
        }
        for d in days
    ]


def _achievements_for_user(
    stats: UserStats | None,
    tickets,
    strategy_stats: dict,
    global_rank: int,
    achievement_cards: list,
) -> list:
    has_win = any((t.pointsEarned or 0) > 0 for t in tickets)
    best_streak = stats.bestStreak if stats else 0
    titles = stats.titles if stats else 0
    total_points = stats.totalPoints if stats else 0
    records = stats.records if stats else 0
    smart = strategy_stats.get("smart_pick") or {}

    has_winner_card = any(
        c.get("type") in ("tournament_winner", "TOURNAMENT_WINNER") or c.get("place") == 1
        for c in achievement_cards
    )
    gulfstream_pts = 0
    for t in tickets:
        track = ""
        if t.race and t.race.tournament:
            track = (t.race.tournament.track or "") + (t.race.tournament.name or "")
        if "gulfstream" in track.lower():
            gulfstream_pts = max(gulfstream_pts, t.pointsEarned or 0)

    rules = {
        "first_win": has_win,
        "streak_5": best_streak >= 5,
        "daily_top10": global_rank > 0 and global_rank <= 10,
        "full_point_master": _consecutive_wins(tickets, "full_point", 3),
        "smart_pick_pro": _consecutive_wins(tickets, "smart_pick", 5),
        "comeback_kid": records >= 1,
        "tournament_champion": titles > 0 or has_winner_card,
        "points_1000": _max_daily_points(tickets) >= 1000,
        "perfect_smart": (smart.get("wins") or 0) >= 3 and (smart.get("count") or 0) >= 3,
        "gulfstream_king": gulfstream_pts >= 100,
        "full_point_50x": any(
            t.strategy == "full_point" and (t.pointsEarned or 0) >= 50 for t in tickets
        ),
        "vip_hall": global_rank > 0 and global_rank <= 10 and total_points >= 5000,
    }

    out = []
    for item in ACHIEVEMENT_CATALOG:
        out.append({**item, "unlocked": bool(rules.get(item["id"], False))})
    return out


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
    tickets = _load_user_tickets(db, user.id, limit=200)
    mapped = [_map_ticket(t) for t in tickets]
    global_rank = _global_rank(db, user.id, stats)
    strategy_stats = _strategy_stats(tickets)
    achievement_cards = _achievement_cards_list(db, user.id)

    return {
        "user": _user_payload(user, stats, global_rank, include_email=True),
        "recentTickets": mapped[:10],
        "strategyStats": strategy_stats,
        "allTickets": mapped,
        "tournamentSummaries": _tournament_summaries(tickets),
        "achievementCards": achievement_cards,
        "performanceHistory": _performance_history(tickets),
        "achievements": _achievements_for_user(
            stats, tickets, strategy_stats, global_rank, achievement_cards
        ),
    }


@router.get("/public/{user_id}")
def public_profile(user_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    stats = db.query(UserStats).filter(UserStats.userId == user.id).first()
    tickets = _load_user_tickets(db, user.id, limit=200)
    global_rank = _global_rank(db, user.id, stats)
    strategy_stats = _strategy_stats(tickets)
    achievement_cards = _achievement_cards_list(db, user.id)

    return {
        "user": _user_payload(user, stats, global_rank, include_email=False),
        "strategyStats": strategy_stats,
        "tournamentSummaries": _tournament_summaries(tickets),
        "achievementCards": achievement_cards,
        "achievements": _achievements_for_user(
            stats, tickets, strategy_stats, global_rank, achievement_cards
        ),
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
