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


def score_ticket(strategy: str, picks, results: list, horses: list | None = None) -> int:
    """
    Score a ticket per requirements v1.1 (flat points, position-matched picks).

    - Full Point: 50 if the single pick finishes 1st.
    - Dual Point: 25 if pick[0] finishes 1st; 25 if pick[1] finishes 2nd (independent sum).
    - Smart Pick: 30/15/5 if picks[0..2] finish 1st/2nd/3rd respectively (independent sum).
    """
    del horses  # flat points; odds not applied in MVP scoring
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
            total += allocation[i]

    return int(total)
