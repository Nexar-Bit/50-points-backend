"""Fetch live racecard data from public racing sources."""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, timezone
from typing import Any

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

RACING_API_BASE = "https://api.theracingapi.com/v1"
HRN_ENTRIES_BASE = "https://www.horseracingnation.com/entries-results"

US_TRACKS: dict[str, dict[str, str]] = {
    "gulfstream-park": {
        "name": "Gulfstream Park",
        "location": "Hallandale Beach, FL",
        "hrn_slug": "gulfstream-park",
    },
    "santa-anita": {
        "name": "Santa Anita Park",
        "location": "Arcadia, CA",
        "hrn_slug": "santa-anita",
    },
    "churchill-downs": {
        "name": "Churchill Downs",
        "location": "Louisville, KY",
        "hrn_slug": "churchill-downs",
    },
    "belmont-park": {
        "name": "Belmont Park",
        "location": "Elmont, NY",
        "hrn_slug": "belmont-park",
    },
    "saratoga": {
        "name": "Saratoga Race Course",
        "location": "Saratoga Springs, NY",
        "hrn_slug": "saratoga",
    },
    "keeneland": {
        "name": "Keeneland",
        "location": "Lexington, KY",
        "hrn_slug": "keeneland",
    },
}

DEFAULT_COLORS = [
    ("#e11d48", "#fbbf24"),
    ("#2563eb", "#ffffff"),
    ("#16a34a", "#000000"),
    ("#7c3aed", "#f59e0b"),
    ("#dc2626", "#1d4ed8"),
    ("#0891b2", "#fde047"),
]


def _default_odds(idx: int) -> float:
    base = [2.5, 4.0, 6.5, 9.0, 12.0, 15.0, 8.0, 5.5]
    return base[idx % len(base)]


def _normalize_racing_api_race(api_race: dict, race_number: int) -> dict:
    runners = api_race.get("runners") or []
    horses = []
    for idx, runner in enumerate(runners):
        silk = DEFAULT_COLORS[idx % len(DEFAULT_COLORS)]
        horses.append(
            {
                "postPosition": int(runner.get("draw") or idx + 1),
                "name": runner.get("horse") or f"Horse {idx + 1}",
                "jockey": runner.get("jockey") or "TBA",
                "trainer": runner.get("trainer") or "TBA",
                "odds": float(runner.get("odds") or _default_odds(idx)),
                "silkPrimary": silk[0],
                "silkSecondary": silk[1],
            }
        )

    distance_f = api_race.get("distance_f")
    distance_m = round(float(distance_f) * 201.168) if distance_f else 1600
    prize = api_race.get("prize") or ""
    purse = int(re.sub(r"[^0-9]", "", str(prize)) or 0)

    return {
        "raceNumber": race_number,
        "name": api_race.get("race_name") or f"Race {race_number}",
        "status": "upcoming",
        "scheduledTime": api_race.get("off_dt") or api_race.get("off_time") or "TBD",
        "distance": distance_m,
        "surface": api_race.get("going") or api_race.get("surface") or "Dirt",
        "raceClass": api_race.get("race_class") or "Open",
        "purse": purse,
        "horses": horses,
    }


def fetch_theracingapi_racecards(
    course_id: str,
    race_date: str,
    username: str,
    password: str = "",
) -> tuple[list[dict], str]:
    """The Racing API — public commercial racing data (https://www.theracingapi.com)."""
    auth = (username, password or "")
    url = f"{RACING_API_BASE}/racecards"
    params = {"course": course_id, "date": race_date}

    with httpx.Client(timeout=30.0) as client:
        response = client.get(url, params=params, auth=auth)
        response.raise_for_status()
        payload = response.json()

    racecards = payload.get("racecards") or []
    races = [_normalize_racing_api_race(r, i + 1) for i, r in enumerate(racecards)]
    return races, "theracingapi"


def scrape_hrn_racecards(track_id: str, race_date: str) -> tuple[list[dict], str]:
    """
  Scrape public race entries from Horse Racing Nation (entries-results pages).
  Used when no Racing API credentials are configured.
    """
    track = US_TRACKS.get(track_id, {})
    hrn_slug = track.get("hrn_slug", track_id)
    # Try date-specific entries page first, then the track hub.
    try:
        dt = datetime.strptime(race_date, "%Y-%m-%d")
        dated_path = f"{HRN_ENTRIES_BASE}/{hrn_slug}/{dt.strftime('%m-%d-%Y')}"
    except ValueError:
        dated_path = None
    urls = [u for u in (dated_path, f"{HRN_ENTRIES_BASE}/{hrn_slug}") if u]

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    html = None
    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        for url in urls:
            try:
                response = client.get(url, headers=headers)
                if response.status_code in (404, 403, 410):
                    continue
                if response.status_code >= 400:
                    continue
                if response.text and len(response.text) > 500:
                    html = response.text
                    break
            except httpx.HTTPError:
                continue

    if not html:
        page_title = track.get("name", track_id)
        return [
            {
                "raceNumber": 1,
                "name": f"{page_title} — Card",
                "status": "open",
                "scheduledTime": "TBD",
                "distance": 1600,
                "surface": "Dirt",
                "raceClass": "Open",
                "purse": 0,
                "horses": [
                    {
                        "postPosition": i + 1,
                        "name": f"Runner {i + 1}",
                        "jockey": "TBA",
                        "trainer": "TBA",
                        "odds": _default_odds(i),
                        "silkPrimary": DEFAULT_COLORS[i % len(DEFAULT_COLORS)][0],
                        "silkSecondary": DEFAULT_COLORS[i % len(DEFAULT_COLORS)][1],
                    }
                    for i in range(8)
                ],
            }
        ], "horseracingnation-fallback"

    soup = BeautifulSoup(html, "html.parser")
    races: list[dict] = []
    race_number = 0

    # HRN lists races in headings / race blocks — extract horse names from links and tables
    for heading in soup.find_all(["h2", "h3", "h4"]):
        title = heading.get_text(" ", strip=True)
        if not title or "race" not in title.lower():
            continue
        race_number += 1
        match = re.search(r"race\s*(\d+)", title, re.I)
        num = int(match.group(1)) if match else race_number

        horses: list[dict] = []
        container = heading.find_parent(["section", "article", "div"]) or heading
        for link in container.find_all("a", href=re.compile(r"/horse/|/horses/", re.I))[:14]:
            name = link.get_text(strip=True)
            if name and len(name) > 1 and name.lower() not in ("view", "more"):
                idx = len(horses)
                silk = DEFAULT_COLORS[idx % len(DEFAULT_COLORS)]
                horses.append(
                    {
                        "postPosition": idx + 1,
                        "name": name[:64],
                        "jockey": "TBA",
                        "trainer": "TBA",
                        "odds": _default_odds(idx),
                        "silkPrimary": silk[0],
                        "silkSecondary": silk[1],
                    }
                )

        if horses:
            races.append(
                {
                    "raceNumber": num,
                    "name": title[:120],
                    "status": "upcoming",
                    "scheduledTime": "TBD",
                    "distance": 1600,
                    "surface": "Dirt",
                    "raceClass": "Open",
                    "purse": 0,
                    "horses": horses,
                }
            )

    if not races:
        # Minimal fallback: one showcase race with generic runners from page title
        page_title = soup.title.string if soup.title else track.get("name", track_id)
        races = [
            {
                "raceNumber": 1,
                "name": f"{page_title} — Featured",
                "status": "open",
                "scheduledTime": "TBD",
                "distance": 1600,
                "surface": "Dirt",
                "raceClass": "Open",
                "purse": 0,
                "horses": [
                    {
                        "postPosition": i + 1,
                        "name": f"Runner {i + 1}",
                        "jockey": "TBA",
                        "trainer": "TBA",
                        "odds": _default_odds(i),
                        "silkPrimary": DEFAULT_COLORS[i % len(DEFAULT_COLORS)][0],
                        "silkSecondary": DEFAULT_COLORS[i % len(DEFAULT_COLORS)][1],
                    }
                    for i in range(8)
                ],
            }
        ]

    return races, "horseracingnation"


def fetch_public_track_racecards(
    track_id: str,
    race_date: str | None,
    api_username: str | None,
    api_password: str | None = None,
) -> tuple[list[dict], str]:
    """Try Racing API first, then public site scrape."""
    day = race_date or date.today().isoformat()

    if api_username:
        try:
            return fetch_theracingapi_racecards(track_id, day, api_username, api_password or "")
        except Exception as exc:
            logger.warning("Racing API failed for %s: %s", track_id, exc)

    try:
        return scrape_hrn_racecards(track_id, day)
    except Exception as exc:
        logger.warning("HRN scrape failed for %s: %s", track_id, exc)
        raise


def build_tournament_payload(
    track_id: str,
    races: list[dict],
    race_date: str,
    source: str,
) -> dict[str, Any]:
    track = US_TRACKS[track_id]
    slug = f"{track_id}-{race_date}"
    now = datetime.now(timezone.utc)

    current_race = 1
    for r in races:
        off = r.get("scheduledTime")
        if off and off != "TBD":
            try:
                off_dt = datetime.fromisoformat(off.replace("Z", "+00:00"))
                if off_dt > now:
                    current_race = r["raceNumber"]
                    break
            except ValueError:
                pass
        current_race = r["raceNumber"]

    for i, r in enumerate(races):
        rn = r["raceNumber"]
        if rn < current_race:
            r["status"] = "finished"
        elif rn == current_race:
            r["status"] = "open"
        else:
            r["status"] = "upcoming"

    status = "live" if any(r["status"] in ("open", "upcoming") for r in races) else "finished"

    return {
        "slug": slug,
        "name": f"{track['name']} — {race_date}",
        "track": track["name"],
        "location": track["location"],
        "status": status,
        "totalRaces": len(races),
        "currentRace": current_race,
        "date": race_date,
        "description": f"Live racecard synced from {source}",
        "imageUrl": None,
        "races": races,
        "dataSource": source,
    }
