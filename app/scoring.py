import json

ALLOCATIONS = {
    "full_point": [50],
    "dual_point": [25, 25],
    "smart_pick": [30, 15, 5],
}

# Pick index → finishing position required for that allocation slot
_POSITION_BY_SLOT = {
    "full_point": [1],
    "dual_point": [1, 2],
    "smart_pick": [1, 2, 3],
}


def get_required_picks(strategy: str) -> int:
    return {"full_point": 1, "dual_point": 2, "smart_pick": 3}.get(strategy, 0)


def _normalize_results(results: list) -> dict[int, int]:
    """Map finishing position (1-based) → horseId."""
    by_position: dict[int, int] = {}
    for r in results:
        if isinstance(r, dict):
            pos = r.get("position")
            horse_id = r.get("horseId")
        else:
            pos = getattr(r, "position", None)
            horse_id = getattr(r, "horseId", None)
        if pos is not None and horse_id is not None:
            by_position[int(pos)] = int(horse_id)
    return by_position


def _normalize_picks(picks) -> list[int]:
    if isinstance(picks, str):
        return [int(x) for x in json.loads(picks)]
    return [int(x) for x in picks]


def _horse_dividend(horses: list | None, horse_id: int) -> float:
    """Official payout dividend / odds for the selected horse (multiplier)."""
    if not horses:
        return 1.0
    for h in horses:
        hid = h.get("id") if isinstance(h, dict) else h.id
        if int(hid) == int(horse_id):
            raw = h.get("odds") if isinstance(h, dict) else h.odds
            try:
                val = float(raw)
            except (TypeError, ValueError):
                return 1.0
            return val if val > 0 else 1.0
    return 1.0


def score_ticket(strategy: str, picks, results: list, horses: list | None = None) -> int:
    """
    Score a ticket: base allocation × horse dividend when the pick hits the required position.

    Example (Full Point): 50 pts on horse #3 in race 6, horse wins at dividend 4.20 → 50 × 4.20 = 210 pts.

    - Full Point: pick must finish 1st → 50 × dividend.
    - Dual Point: pick[0] 1st → 25 × its dividend; pick[1] 2nd → 25 × its dividend (independent).
    - Smart Pick: 30/15/5 × each pick's dividend for 1st/2nd/3rd slots (independent).
    """
    picks_arr = _normalize_picks(picks)
    if not picks_arr or strategy not in ALLOCATIONS:
        return 0

    by_position = _normalize_results(results)
    if not by_position:
        return 0

    allocation = ALLOCATIONS[strategy]
    required_positions = _POSITION_BY_SLOT[strategy]
    total = 0

    for i, pick_id in enumerate(picks_arr):
        if i >= len(allocation):
            break
        required_pos = required_positions[i] if i < len(required_positions) else None
        if required_pos is None:
            continue
        actual_horse = by_position.get(required_pos)
        if actual_horse is not None and int(pick_id) == int(actual_horse):
            base = allocation[i]
            dividend = _horse_dividend(horses, pick_id)
            total += round(base * dividend)

    return int(total)
