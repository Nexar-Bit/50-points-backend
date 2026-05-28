"""Rank deltas and recent play indicators for tournament leaderboard rows."""

from sqlalchemy.orm import Session

from app.models import LeaderboardEntry, Ticket

STRATEGY_KEYS = ("full_point", "dual_point", "smart_pick")


def refresh_tournament_rank_changes(db: Session, tournament_id: int) -> None:
    rows = (
        db.query(LeaderboardEntry)
        .filter(LeaderboardEntry.tournamentId == tournament_id, LeaderboardEntry.totalPoints > 0)
        .order_by(
            LeaderboardEntry.totalPoints.desc(),
            LeaderboardEntry.bestStreak.desc(),
            LeaderboardEntry.racesPlayed.desc(),
        )
        .all()
    )
    for rank, entry in enumerate(rows, start=1):
        prev = entry.previousRank if entry.previousRank is not None else rank
        entry.rankChange = prev - rank
        entry.previousRank = rank


def get_recent_plays(db: Session, user_id: int, tournament_id: int, ticket_number: int, limit: int = 3) -> list[dict]:
    tickets = (
        db.query(Ticket)
        .filter(
            Ticket.userId == user_id,
            Ticket.tournamentId == tournament_id,
            Ticket.ticketNumber == ticket_number,
            Ticket.isScored == True,
        )
        .order_by(Ticket.createdAt.desc())
        .limit(limit)
        .all()
    )
    plays: list[dict] = []
    for t in reversed(tickets):
        if t.pointsEarned > 0 and t.strategy in STRATEGY_KEYS:
            plays.append({"strategy": t.strategy, "won": True, "points": t.pointsEarned})
        else:
            plays.append({"strategy": t.strategy, "won": False, "points": t.pointsEarned})
    while len(plays) < limit:
        plays.insert(0, {"strategy": None, "won": False, "points": 0})
    return plays[-limit:]


def dominant_strategy_key(entry: LeaderboardEntry) -> str:
    scores = [
        ("full_point", entry.fullPoints or 0),
        ("dual_point", entry.dualPoints or 0),
        ("smart_pick", entry.smartPoints or 0),
    ]
    scores.sort(key=lambda x: x[1], reverse=True)
    return scores[0][0]
