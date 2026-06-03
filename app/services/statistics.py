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

STRATEGY_SHORT = {
    "full_point": "FP",
    "dual_point": "DP",
    "smart_pick": "SP",
}

HORSE_CHART_COLORS = ["#a855f7", "#06b6d4", "#f59e0b", "#ef4444", "#22c55e", "#64748b"]
POINTS_PER_RACE_BET = 50


def _strategy_breakdown(tickets: list[Ticket]) -> list[dict]:
    counts: Counter[str] = Counter()
    for t in tickets:
        counts[t.strategy] += 1
    total = sum(counts.values()) or 1
    return [
        {
            "strategy": STRATEGY_LABELS.get(key, key),
            "strategyShort": STRATEGY_SHORT.get(key, key),
            "strategyKey": key,
            "count": count,
            "percent": round(100 * count / total, 1),
        }
        for key, count in counts.most_common()
    ]


def _track_profitability(tickets: list[Ticket]) -> dict:
    """Average scored points per ticket grouped by racetrack."""
    by_track: dict[str, list[int]] = defaultdict(list)
    for t in tickets:
        if not t.isScored or not t.race or not t.race.tournament:
            continue
        by_track[t.race.tournament.track].append(t.pointsEarned or 0)
    if not by_track:
        return {"mostProfitableTrack": None, "mostDifficultTrack": None}
    averages = {track: sum(vals) / len(vals) for track, vals in by_track.items()}
    return {
        "mostProfitableTrack": max(averages, key=averages.get),
        "mostDifficultTrack": min(averages, key=averages.get),
        "trackAverages": [
            {"track": track, "averagePoints": round(avg, 1)}
            for track, avg in sorted(averages.items(), key=lambda x: x[1], reverse=True)
        ],
    }


def _parse_picks(ticket: Ticket) -> list[int]:
    raw = json.loads(ticket.picks) if isinstance(ticket.picks, str) else ticket.picks
    return [int(p) for p in raw]


def _horses_meta(race: Race) -> dict[int, dict]:
    return {h.id: {"name": h.name, "number": h.postPosition} for h in race.horses}


def _top_horses(
    tickets: list[Ticket],
    limit: int = 10,
    horses_meta: dict[int, dict] | None = None,
) -> list[dict]:
    horse_counts: Counter[int] = Counter()
    horse_names: dict[int, str] = {}
    horse_numbers: dict[int, int | None] = {}
    for t in tickets:
        for pid in _parse_picks(t):
            horse_counts[pid] += 1
            if horses_meta and pid in horses_meta:
                horse_names[pid] = horses_meta[pid]["name"]
                horse_numbers[pid] = horses_meta[pid].get("number")
            elif t.race and t.race.horses:
                for h in t.race.horses:
                    if h.id == pid:
                        horse_names[pid] = h.name
                        horse_numbers[pid] = h.postPosition
                        break
    return [
        {
            "horseId": hid,
            "name": horse_names.get(hid, f"Horse #{hid}"),
            "number": horse_numbers.get(hid),
            "plays": count,
        }
        for hid, count in horse_counts.most_common(limit)
    ]


def _finish_result_rows(
    race: Race,
    tickets: list[Ticket],
    user_id: int | None = None,
    value_key: str = "avg",
) -> list[dict]:
    """Finish order table: avg points (general) or user ticket points (personal)."""
    meta = _horses_meta(race)
    results = sorted(race.results, key=lambda r: r.position)
    user_tickets = [t for t in tickets if t.userId == user_id] if user_id else []
    user_pick_ids = set()
    for t in user_tickets:
        user_pick_ids.update(_parse_picks(t))
    user_race_pts = sum(t.pointsEarned or 0 for t in user_tickets if t.isScored)

    rows = []
    for i, res in enumerate(results[:5]):
        horse = meta.get(res.horseId, {})
        horse_name = horse.get("name", f"Horse #{res.horseId}")
        horse_num = horse.get("number")
        scored_for_horse = [
            t
            for t in tickets
            if t.isScored and res.horseId in _parse_picks(t)
        ]
        avg_pts = (
            round(sum(t.pointsEarned or 0 for t in scored_for_horse) / len(scored_for_horse), 1)
            if scored_for_horse
            else 0
        )
        highlight = user_id is not None and res.horseId in user_pick_ids
        if value_key == "user":
            pts_display = user_race_pts if highlight else 0
        else:
            pts_display = avg_pts

        rows.append(
            {
                "position": f"{res.position}°",
                "positionNum": res.position,
                "horse": horse_name,
                "horseNumber": horse_num,
                "points": pts_display,
                "highlight": highlight,
                "color": HORSE_CHART_COLORS[i % len(HORSE_CHART_COLORS)],
            }
        )
    return rows


def _race_winner(race: Race) -> dict | None:
    if not race.results:
        return None
    meta = _horses_meta(race)
    top = min(race.results, key=lambda r: r.position)
    info = meta.get(top.horseId, {})
    return {
        "horse": info.get("name", f"Horse #{top.horseId}"),
        "horseNumber": info.get("number"),
        "position": top.position,
    }


def _user_race_rank(tickets: list[Ticket], user_id: int) -> tuple[int, int, int]:
    totals: dict[int, int] = defaultdict(int)
    for t in tickets:
        if t.isScored:
            totals[t.userId] += t.pointsEarned or 0
    user_pts = totals.get(user_id, 0)
    ranked = sorted(totals.items(), key=lambda x: x[1], reverse=True)
    rank = next((i + 1 for i, (uid, _) in enumerate(ranked) if uid == user_id), 0)
    return user_pts, rank, len(ranked)


def _top_horse_options(tickets: list[Ticket], limit: int = 3) -> list[dict]:
    top = _top_horses(tickets, limit=limit)
    total = sum(h["plays"] for h in top) or 1
    return [
        {"name": h["name"], "percent": f"{round(100 * h['plays'] / total)}%"}
        for h in top
    ]


def _strategy_distribution_segments(strategy_usage: list[dict]) -> list[dict]:
    if not strategy_usage:
        return []
    return [
        {
            "label": s["strategyShort"],
            "value": s["percent"],
            "color": HORSE_CHART_COLORS[i % len(HORSE_CHART_COLORS)],
        }
        for i, s in enumerate(strategy_usage[:4])
    ]


def _tournament_evolution(db: Session, tournament_id: int, user_id: int | None = None) -> dict:
    races = (
        db.query(Race)
        .filter(Race.tournamentId == tournament_id)
        .order_by(Race.raceNumber)
        .all()
    )
    labels = []
    personal_vals = []
    general_vals = []
    for race in races:
        labels.append(race.raceNumber)
        race_tickets = (
            db.query(Ticket).filter(Ticket.raceId == race.id, Ticket.isScored == True).all()
        )
        if race_tickets:
            general_vals.append(
                round(sum(t.pointsEarned or 0 for t in race_tickets) / len(race_tickets), 1)
            )
        else:
            general_vals.append(0)
        if user_id:
            user_race = [t for t in race_tickets if t.userId == user_id]
            personal_vals.append(sum(t.pointsEarned or 0 for t in user_race))
        else:
            personal_vals.append(0)
    return {
        "raceLabels": labels,
        "personalEvolution": personal_vals,
        "generalEvolution": general_vals,
    }


def race_statistics(db: Session, race_id: int, user_id: int | None = None) -> dict | None:
    race = (
        db.query(Race)
        .options(
            joinedload(Race.horses),
            joinedload(Race.results),
            joinedload(Race.tournament),
        )
        .filter(Race.id == race_id)
        .first()
    )
    if not race:
        return None

    tickets = (
        db.query(Ticket)
        .options(joinedload(Ticket.race).joinedload(Race.horses))
        .filter(Ticket.raceId == race_id)
        .all()
    )

    meta = _horses_meta(race)
    scored = [t for t in tickets if t.isScored]
    earned = [t.pointsEarned or 0 for t in scored]
    avg_points = round(sum(earned) / len(earned), 1) if earned else 0
    winner = _race_winner(race)

    result = {
        "level": "race",
        "scope": "race",
        "raceId": race.id,
        "raceNumber": race.raceNumber,
        "raceName": race.name or f"Carrera {race.raceNumber}",
        "raceStatus": race.status,
        "tournamentId": race.tournamentId,
        "tournamentName": race.tournament.name if race.tournament else None,
        "track": race.tournament.track if race.tournament else None,
        "topHorses": _top_horses(tickets, horses_meta=meta),
        "strategyUsage": _strategy_breakdown(tickets),
        "totalTickets": len(tickets),
        "uniquePlayers": len({t.userId for t in tickets}),
        "averagePointsEarned": avg_points,
        "profitability": {
            "averagePoints": avg_points,
            "maxPoints": max(earned) if earned else 0,
            "minPoints": min(earned) if earned else 0,
        },
        "generalOutcome": {
            "averagePoints": avg_points,
            "averagePosition": round(
                sum(r.position for r in race.results[:5]) / len(race.results[:5]), 1
            )
            if race.results
            else 0,
            "winnerHorse": winner["horse"] if winner else None,
            "winnerNumber": winner["horseNumber"] if winner else None,
            "finishTable": _finish_result_rows(race, tickets, value_key="avg"),
        },
    }

    if user_id is not None:
        user_tickets = [t for t in tickets if t.userId == user_id]
        user_scored = [t for t in user_tickets if t.isScored]
        user_earned = sum(t.pointsEarned or 0 for t in user_scored)
        user_pts, user_rank, field_size = _user_race_rank(tickets, user_id)
        result["personal"] = {
            "topHorses": _top_horses(user_tickets, horses_meta=meta),
            "strategyUsage": _strategy_breakdown(user_tickets),
            "totalTickets": len(user_tickets),
            "pointsEarned": user_earned,
            "averagePointsEarned": round(user_earned / len(user_scored), 1) if user_scored else 0,
        }
        result["personalOutcome"] = {
            "pointsEarned": user_pts,
            "rank": user_rank,
            "fieldSize": field_size,
            "winnerHorse": winner["horse"] if winner else None,
            "winnerNumber": winner["horseNumber"] if winner else None,
            "finishTable": _finish_result_rows(race, tickets, user_id=user_id, value_key="user"),
        }

    return result


def tournament_statistics(db: Session, tournament_id: int, user_id: int | None = None) -> dict:
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

    leader = entries[0] if entries else None
    leader_user = db.query(User).filter(User.id == leader.userId).first() if leader else None

    payload = {
        "level": 1,
        "scope": "tournament",
        "tournamentId": tournament.id,
        "tournamentName": tournament.name,
        "track": tournament.track,
        "totalRaces": tournament.totalRaces,
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
        "leader": {
            "username": leader_user.username if leader_user else None,
            "totalPoints": leader.totalPoints if leader else 0,
        },
        "totalPointsDistributed": sum(e.totalPoints for e in entries),
        "strategyDistribution": _strategy_distribution_segments(_strategy_breakdown(tickets)),
        "topHorseOptions": _top_horse_options(tickets),
    }

    if user_id is not None:
        user_entry = next((e for e in entries if e.userId == user_id), None)
        user_rank = next((i + 1 for i, e in enumerate(entries) if e.userId == user_id), 0)
        user_tickets = [t for t in tickets if t.userId == user_id]
        user_scored = [t for t in user_tickets if t.isScored]
        user_wins = sum(1 for t in user_scored if (t.pointsEarned or 0) > 0)
        hit_rate = round(100 * user_wins / len(user_scored), 1) if user_scored else 0
        avg_user_pts = (
            round(user_entry.totalPoints / user_entry.racesPlayed, 1)
            if user_entry and user_entry.racesPlayed
            else 0
        )
        payload["user"] = {
            "rank": user_rank,
            "fieldSize": len(entries),
            "totalPoints": user_entry.totalPoints if user_entry else 0,
            "racesPlayed": user_entry.racesPlayed if user_entry else 0,
            "averagePoints": avg_user_pts,
            "hitRate": hit_rate,
            "topHorses": _top_horses(user_tickets, limit=3),
            "strategyUsage": _strategy_breakdown(user_tickets),
            "strategyDistribution": _strategy_distribution_segments(
                _strategy_breakdown(user_tickets)
            ),
        }
        payload["performance"] = _tournament_evolution(db, tournament_id, user_id=user_id)

    payload["performanceGeneral"] = _tournament_evolution(db, tournament_id, user_id=None)
    return payload


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

    points_played = len(scored) * POINTS_PER_RACE_BET
    points_won = stats.totalPoints if stats else sum(t.pointsEarned or 0 for t in scored)
    profitability = (
        round(100 * (points_won - points_played) / points_played, 1) if points_played else 0
    )

    entries = (
        db.query(LeaderboardEntry)
        .filter(LeaderboardEntry.userId == user_id)
        .order_by(LeaderboardEntry.totalPoints.desc())
        .all()
    )
    best_entry = max(entries, key=lambda e: e.totalPoints) if entries else None
    all_entries = (
        db.query(LeaderboardEntry)
        .order_by(LeaderboardEntry.tournamentId, LeaderboardEntry.totalPoints.desc())
        .all()
    )
    ranks_by_tournament: dict[int, list] = defaultdict(list)
    for e in all_entries:
        ranks_by_tournament[e.tournamentId].append(e)
    best_rank = None
    best_rank_label = None
    for tid, t_entries in ranks_by_tournament.items():
        ordered = sorted(t_entries, key=lambda x: x.totalPoints, reverse=True)
        for i, e in enumerate(ordered):
            if e.userId == user_id:
                r = i + 1
                if best_rank is None or r < best_rank:
                    best_rank = r
                    tourn = db.query(Tournament).filter(Tournament.id == tid).first()
                    best_rank_label = tourn.name if tourn else f"Tournament #{tid}"
                break

    best_race_ticket = max(scored, key=lambda t: t.pointsEarned or 0) if scored else None
    best_race_label = None
    best_race_pts = 0
    best_race_track = None
    if best_race_ticket and best_race_ticket.race:
        best_race_label = best_race_ticket.race.name or f"Carrera {best_race_ticket.race.raceNumber}"
        best_race_pts = best_race_ticket.pointsEarned or 0
        if best_race_ticket.race.tournament:
            best_race_track = best_race_ticket.race.tournament.track

    line_points = [e["points"] for e in evolution] if evolution else []
    if len(line_points) < 2 and scored:
        line_points = []
        by_race_num: dict[int, int] = defaultdict(int)
        for t in scored:
            if t.race:
                by_race_num[t.race.raceNumber] += t.pointsEarned or 0
        line_points = [by_race_num[k] for k in sorted(by_race_num.keys())]

    return {
        "level": 4,
        "scope": "personal",
        "userId": user_id,
        "username": user.username if user else None,
        "totalPoints": points_won,
        "tournamentsPlayed": stats.tournamentsPlayed if stats else 0,
        "totalRaces": stats.totalRaces if stats else len({t.raceId for t in scored}),
        "winRate": stats.winRate if stats else win_rate,
        "bestStreak": stats.bestStreak if stats else 0,
        "favoriteTrack": favorite_track,
        "favoriteStrategy": favorite_strategy,
        "topHorses": _top_horses(tickets),
        "strategyUsage": strategy_usage,
        "evolution": evolution,
        "metrics": {
            "pointsPlayed": points_played,
            "pointsWon": points_won,
            "profitabilityPct": profitability,
            "bestRank": best_rank,
            "bestRankLabel": best_rank_label,
            "bestRankField": (
                len(ranks_by_tournament.get(best_entry.tournamentId, [])) if best_entry else 0
            ),
            "evolutionLine": line_points,
            "accuracyPct": win_rate,
            "averagePointsPerRace": round(points_won / len(scored), 1) if scored else 0,
            "bestRaceLabel": best_race_label,
            "bestRacePoints": best_race_pts,
            "bestRaceTrack": best_race_track,
            "racesPlayedCount": len({t.raceId for t in scored}),
        },
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
    race_participation: Counter[int] = Counter()
    race_labels: dict[int, str] = {}
    for t in tickets:
        if t.raceId:
            race_participation[t.raceId] += 1
            if t.race:
                race_labels[t.raceId] = f"Carrera {t.race.raceNumber}"

    top_races = [
        {
            "raceId": rid,
            "label": race_labels.get(rid, f"Race #{rid}"),
            "plays": count,
        }
        for rid, count in race_participation.most_common(5)
    ]

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
        "topRacesByParticipation": top_races,
        "profitability": _track_profitability(tickets),
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

    profitability = _track_profitability(tickets)

    return {
        "level": 3,
        "scope": "global",
        "topHorses": _top_horses(tickets),
        "strategyUsage": _strategy_breakdown(tickets),
        "mostPopularTrack": most_popular_track,
        "mostProfitableTrack": profitability.get("mostProfitableTrack"),
        "mostDifficultTrack": profitability.get("mostDifficultTrack"),
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
        "profitability": profitability,
    }
