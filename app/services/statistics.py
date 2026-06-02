"""Statistics levels 1–4 — requirements v1.1."""

from __future__ import annotations

import json
from collections import Counter, defaultdict

from sqlalchemy.orm import Session, joinedload

from app.models import LeaderboardEntry, Race, Ticket, Tournament, User, UserStats

STRATEGY_LABELS = {
    "full_point": "Full Point",
    "dual_point": "Dual Point",
    "smart_pick": "Smart Point",
}


def _strategy_breakdown(tickets: list[Ticket]) -> list[dict]:
    counts: Counter[str] = Counter()
    for t in tickets:
        counts[t.strategy] += 1
    total = sum(counts.values()) or 1
    return [
        {
            "strategy": STRATEGY_LABELS.get(key, key),
            "strategyKey": key,
            "count": count,
            "percent": round(100 * count / total, 1),
        }
        for key, count in counts.most_common()
    ]


def _top_horses(tickets: list[Ticket], limit: int = 10) -> list[dict]:
    horse_counts: Counter[int] = Counter()
    horse_names: dict[int, str] = {}
    for t in tickets:
        picks = json.loads(t.picks) if isinstance(t.picks, str) else t.picks
        for pid in picks:
            horse_counts[int(pid)] += 1
            for h in t.race.horses:
                if h.id == pid:
                    horse_names[pid] = h.name
                    break
    return [
        {
            "horseId": hid,
            "name": horse_names.get(hid, f"Horse #{hid}"),
            "plays": count,
        }
        for hid, count in horse_counts.most_common(limit)
    ]


def tournament_statistics(db: Session, tournament_id: int) -> dict:
    tournament = db.query(Tournament).filter(Tournament.id == tournament_id).first()
    if not tournament:
        return None

    tickets = (
        db.query(Ticket)
        .options(joinedload(Ticket.race).joinedload(Race.horses))
        .filter(Ticket.tournamentId == tournament_id)
        .all()
    )

    entries = (
        db.query(LeaderboardEntry)
        .filter(LeaderboardEntry.tournamentId == tournament_id)
        .order_by(LeaderboardEntry.totalPoints.desc())
        .limit(10)
        .all()
    )

    points_values = [e.totalPoints for e in entries]
    avg_points = round(sum(points_values) / len(points_values), 1) if points_values else 0

    return {
        "level": 1,
        "scope": "tournament",
        "tournamentId": tournament.id,
        "tournamentName": tournament.name,
        "track": tournament.track,
        "topHorses": _top_horses(tickets),
        "strategyUsage": _strategy_breakdown(tickets),
        "pointsDistribution": {
            "averageTop10": avg_points,
            "maxTop10": max(points_values) if points_values else 0,
            "minTop10": min(points_values) if points_values else 0,
        },
        "rankingSnapshot": [
            {
                "rank": i + 1,
                "userId": e.userId,
                "ticketNumber": e.ticketNumber,
                "totalPoints": e.totalPoints,
                "racesPlayed": e.racesPlayed,
            }
            for i, e in enumerate(entries)
        ],
        "totalTickets": len(tickets),
    }


def personal_statistics(db: Session, user_id: int) -> dict:
    user = db.query(User).filter(User.id == user_id).first()
    stats = db.query(UserStats).filter(UserStats.userId == user_id).first()

    tickets = (
        db.query(Ticket)
        .options(
            joinedload(Ticket.race).joinedload(Race.horses),
            joinedload(Ticket.race).joinedload(Race.tournament),
        )
        .filter(Ticket.userId == user_id)
        .all()
    )

    track_counts: Counter[str] = Counter()
    for t in tickets:
        track = t.race.tournament.track if t.race and t.race.tournament else "Unknown"
        track_counts[track] += 1

    favorite_track = track_counts.most_common(1)[0][0] if track_counts else None

    strategy_usage = _strategy_breakdown(tickets)
    favorite_strategy = strategy_usage[0]["strategy"] if strategy_usage else None

    scored = [t for t in tickets if t.isScored]
    wins = sum(1 for t in scored if (t.pointsEarned or 0) > 0)
    win_rate = round(100 * wins / len(scored), 1) if scored else 0

    points_by_month: dict[str, int] = defaultdict(int)
    for t in scored:
        if t.createdAt:
            key = t.createdAt.strftime("%Y-%m")
            points_by_month[key] += t.pointsEarned or 0

    evolution = [
        {"period": period, "points": pts}
        for period, pts in sorted(points_by_month.items())
    ]

    return {
        "level": 4,
        "scope": "personal",
        "userId": user_id,
        "username": user.username if user else None,
        "totalPoints": stats.totalPoints if stats else 0,
        "tournamentsPlayed": stats.tournamentsPlayed if stats else 0,
        "totalRaces": stats.totalRaces if stats else 0,
        "winRate": stats.winRate if stats else win_rate,
        "bestStreak": stats.bestStreak if stats else 0,
        "favoriteTrack": favorite_track,
        "favoriteStrategy": favorite_strategy,
        "topHorses": _top_horses(tickets),
        "strategyUsage": strategy_usage,
        "evolution": evolution,
    }


def track_statistics(db: Session, track_name: str) -> dict | None:
    tournaments = db.query(Tournament).filter(Tournament.track == track_name).all()
    if not tournaments:
        return None

    t_ids = [t.id for t in tournaments]
    tickets = (
        db.query(Ticket)
        .options(joinedload(Ticket.race).joinedload(Race.horses))
        .filter(Ticket.tournamentId.in_(t_ids))
        .all()
    )

    top_entry = (
        db.query(LeaderboardEntry, User)
        .join(User, User.id == LeaderboardEntry.userId)
        .filter(LeaderboardEntry.tournamentId.in_(t_ids))
        .order_by(LeaderboardEntry.totalPoints.desc())
        .first()
    )
    top_player = None
    if top_entry:
        entry, user = top_entry
        top_player = {
            "username": user.username,
            "totalPoints": entry.totalPoints,
            "avatarColor": user.avatarColor,
        }

    participation = len({t.userId for t in tickets})
    return {
        "level": 2,
        "scope": "racetrack",
        "track": track_name,
        "tournamentCount": len(tournaments),
        "participation": participation,
        "topHorses": _top_horses(tickets),
        "strategyUsage": _strategy_breakdown(tickets),
        "topPlayer": top_player,
        "highestRecord": top_player["totalPoints"] if top_player else 0,
    }


def global_statistics(db: Session) -> dict:
    tickets = (
        db.query(Ticket)
        .options(joinedload(Ticket.race).joinedload(Race.horses), joinedload(Ticket.race).joinedload(Race.tournament))
        .all()
    )

    track_participation: Counter[str] = Counter()
    for t in tickets:
        if t.race and t.race.tournament:
            track_participation[t.race.tournament.track] += 1

    most_popular_track = track_participation.most_common(1)[0][0] if track_participation else None

    top_stats = (
        db.query(UserStats, User)
        .join(User, User.id == UserStats.userId)
        .order_by(UserStats.totalPoints.desc())
        .limit(10)
        .all()
    )

    return {
        "level": 3,
        "scope": "global",
        "topHorses": _top_horses(tickets),
        "strategyUsage": _strategy_breakdown(tickets),
        "mostPopularTrack": most_popular_track,
        "trackParticipation": [
            {"track": track, "plays": count}
            for track, count in track_participation.most_common(10)
        ],
        "topPlayers": [
            {
                "username": user.username,
                "totalPoints": stats.totalPoints,
                "avatarColor": user.avatarColor,
                "winRate": stats.winRate,
            }
            for stats, user in top_stats
        ],
        "totalTickets": len(tickets),
    }
