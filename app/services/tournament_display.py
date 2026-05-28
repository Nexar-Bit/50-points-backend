"""Pick and order tournaments for consistent UI across environments."""

from __future__ import annotations

import re
from typing import Any

from app.services.racing_fetch import US_TRACKS

_SYNC_SLUG_RE = re.compile(
    r"^(" + "|".join(re.escape(track_id) for track_id in US_TRACKS) + r")-\d{4}-\d{2}-\d{2}$"
)


def track_key(slug: str, track_name: str) -> str:
    for track_id in US_TRACKS:
        if slug.startswith(track_id):
            return track_id
    return track_name.lower().strip()


def _pick_best_for_track(group: list[dict[str, Any]]) -> dict[str, Any]:
    """One card per track: prefer today's synced card, then live, then fuller racecards."""

    def score(t: dict[str, Any]) -> tuple:
        slug = t.get("slug") or ""
        is_synced = bool(_SYNC_SLUG_RE.match(slug))
        status = t.get("status") or ""
        return (
            1 if is_synced else 0,
            1 if status == "live" else 0,
            1 if status == "upcoming" else 0,
            t.get("totalRaces") or 0,
            t.get("players") or 0,
        )

    return max(group, key=score)


def dedupe_tournaments_by_track(tournaments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for item in tournaments:
        key = track_key(item.get("slug") or "", item.get("track") or "")
        groups.setdefault(key, []).append(item)
    return [_pick_best_for_track(group) for group in groups.values()]


def sort_tournaments_for_display(tournaments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    status_order = {"live": 0, "upcoming": 1, "completed": 2, "finished": 3}

    def sort_key(t: dict[str, Any]) -> tuple:
        return (
            status_order.get(t.get("status") or "", 99),
            -(t.get("totalRaces") or 0),
            t.get("date") or "",
        )

    return sorted(tournaments, key=sort_key)


def prepare_home_tournaments(tournaments: list[dict[str, Any]], *, limit: int = 3) -> list[dict[str, Any]]:
    live_or_upcoming = [t for t in tournaments if t.get("status") in ("live", "upcoming")]
    deduped = dedupe_tournaments_by_track(live_or_upcoming)
    ordered = sort_tournaments_for_display(deduped)
    return ordered[:limit]
