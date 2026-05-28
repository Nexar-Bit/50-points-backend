import json

ALLOCATIONS = {
    "full_point": [50],
    "dual_point": [25, 25],
    "smart_pick": [30, 15, 5],
}


def get_required_picks(strategy: str) -> int:
    return { "full_point": 1, "dual_point": 2, "smart_pick": 3 }.get(strategy, 0)


def score_ticket(strategy: str, picks, results: list, horses: list) -> int:
    picks_arr = json.loads(picks) if isinstance(picks, str) else picks
    winner = next((r for r in results if r.get("position") == 1 or getattr(r, "position", None) == 1), None)
    if not winner:
        return 0

    winner_horse_id = winner.get("horseId") if isinstance(winner, dict) else winner.horseId
    allocation = ALLOCATIONS.get(strategy, [])

    for i, pick_id in enumerate(picks_arr):
        if pick_id == winner_horse_id:
            base = allocation[i] if i < len(allocation) else 0
            horse = next((h for h in horses if (h.get("id") if isinstance(h, dict) else h.id) == winner_horse_id), None)
            odds = horse.get("odds") if isinstance(horse, dict) else (horse.odds if horse else 1)
            return round(base * odds)
    return 0
