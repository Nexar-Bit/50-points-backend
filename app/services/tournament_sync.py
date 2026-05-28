"""Sync public racing data into the database."""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import BACKEND_ROOT, settings
from app.models import Horse, Race, Tournament
from app.services.racing_fetch import US_TRACKS, build_tournament_payload, fetch_public_track_racecards

logger = logging.getLogger(__name__)

SYNC_META_PATH = BACKEND_ROOT / "data" / "last_racing_sync.json"
SYNC_TRACKS = ("gulfstream-park", "santa-anita", "churchill-downs")
SYNC_TTL_SECONDS = 120  # background auto-sync at most every 2 minutes

_last_source = "database"


def get_last_data_source() -> str:
    return _last_source


def _read_sync_meta() -> dict:
    if not SYNC_META_PATH.exists():
        return {}
    try:
        return json.loads(SYNC_META_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_sync_meta(meta: dict) -> None:
    SYNC_META_PATH.parent.mkdir(parents=True, exist_ok=True)
    SYNC_META_PATH.write_text(json.dumps(meta, indent=2), encoding="utf-8")


def should_auto_sync(db: Session) -> bool:
    meta = _read_sync_meta()
    last = meta.get("syncedAt")
    if not last:
        return db.query(Tournament).count() == 0
    try:
        last_dt = datetime.fromisoformat(last)
        age = (datetime.now(timezone.utc) - last_dt.replace(tzinfo=timezone.utc)).total_seconds()
        return age > SYNC_TTL_SECONDS
    except ValueError:
        return True


def track_id_from_slug(slug: str) -> str | None:
    for track_id in US_TRACKS:
        if slug.startswith(track_id):
            return track_id
    return None


def _fetch_track_payload(
    track_id: str,
    day: str,
    api_user: str | None,
    api_pass: str,
) -> tuple[str, dict | None, str | None]:
    """Fetch one track (runs in a worker thread). Returns (track_id, payload, error)."""
    try:
        races, source = fetch_public_track_racecards(track_id, day, api_user, api_pass)
        if not races:
            return track_id, None, f"{track_id}: no races"
        payload = build_tournament_payload(track_id, races, day, source)
        return track_id, payload, None
    except Exception as exc:
        logger.exception("Sync failed for %s", track_id)
        return track_id, None, f"{track_id}: {exc}"


def _upsert_tournament(db: Session, payload: dict) -> Tournament:
    slug = payload["slug"]
    tournament = db.query(Tournament).filter(Tournament.slug == slug).first()

    race_date = payload["date"]
    if isinstance(race_date, str):
        dt = datetime.fromisoformat(race_date.replace("Z", "+00:00"))
    else:
        dt = race_date

    if tournament:
        tournament.name = payload["name"]
        tournament.track = payload["track"]
        tournament.location = payload["location"]
        tournament.status = payload["status"]
        tournament.totalRaces = payload["totalRaces"]
        tournament.currentRace = payload["currentRace"]
        tournament.date = dt
        tournament.description = payload["description"]
    else:
        tournament = Tournament(
            slug=slug,
            name=payload["name"],
            track=payload["track"],
            location=payload["location"],
            status=payload["status"],
            totalRaces=payload["totalRaces"],
            currentRace=payload["currentRace"],
            date=dt,
            description=payload["description"],
            imageUrl=payload.get("imageUrl"),
        )
        db.add(tournament)
        db.flush()

    # Replace races/horses for fresh public data
    existing_races = db.query(Race).filter(Race.tournamentId == tournament.id).all()
    for old_race in existing_races:
        db.query(Horse).filter(Horse.raceId == old_race.id).delete(synchronize_session=False)
        db.delete(old_race)
    db.flush()

    for race_data in payload["races"]:
        race = Race(
            tournamentId=tournament.id,
            raceNumber=race_data["raceNumber"],
            name=race_data["name"],
            status=race_data.get("status", "upcoming"),
            scheduledTime=str(race_data.get("scheduledTime", "TBD")),
            distance=race_data.get("distance"),
            surface=race_data.get("surface"),
            raceClass=race_data.get("raceClass"),
            purse=race_data.get("purse"),
        )
        db.add(race)
        db.flush()

        for horse_data in race_data.get("horses", []):
            db.add(
                Horse(
                    raceId=race.id,
                    postPosition=horse_data["postPosition"],
                    name=horse_data["name"],
                    jockey=horse_data.get("jockey"),
                    trainer=horse_data.get("trainer"),
                    odds=float(horse_data.get("odds", 5.0)),
                    silkPrimary=horse_data.get("silkPrimary"),
                    silkSecondary=horse_data.get("silkSecondary"),
                )
            )

    return tournament


def sync_live_tournaments(
    db: Session,
    *,
    tracks: tuple[str, ...] | None = None,
    race_date: str | None = None,
    force: bool = False,
) -> dict:
    global _last_source

    if not force and not should_auto_sync(db):
        return {"synced": False, "reason": "skipped_ttl", "dataSource": get_last_data_source()}

    day = race_date or date.today().isoformat()
    track_ids = tracks or SYNC_TRACKS
    api_user = settings.racing_api_username
    api_pass = settings.racing_api_password or ""

    synced = []
    sources: set[str] = set()
    errors: list[str] = []
    valid_track_ids = [tid for tid in track_ids if tid in US_TRACKS]

    # Scrape tracks in parallel so page refresh stays within serverless timeouts.
    payloads: list[dict] = []
    with ThreadPoolExecutor(max_workers=min(3, len(valid_track_ids) or 1)) as pool:
        futures = {
            pool.submit(_fetch_track_payload, track_id, day, api_user, api_pass): track_id
            for track_id in valid_track_ids
        }
        for future in as_completed(futures):
            _track_id, payload, error = future.result()
            if error:
                errors.append(error)
            elif payload:
                payloads.append(payload)
                sources.add(payload.get("dataSource") or "unknown")

    for payload in payloads:
        _upsert_tournament(db, payload)
        synced.append(payload["slug"])

    db.commit()

    _last_source = ",".join(sorted(sources)) if sources else "database"
    _write_sync_meta(
        {
            "syncedAt": datetime.now(timezone.utc).isoformat(),
            "slugs": synced,
            "dataSource": _last_source,
            "errors": errors,
        }
    )

    return {
        "synced": len(synced) > 0,
        "tournaments": synced,
        "dataSource": _last_source,
        "errors": errors,
    }
