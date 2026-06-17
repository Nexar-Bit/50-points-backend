"""Sync public racing data into the database."""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import BACKEND_ROOT, settings
from app.constants import RACES_PER_TOURNAMENT
from app.database import SessionLocal
from app.models import Horse, Race, Ticket, Tournament
from app.services.racing_fetch import US_TRACKS, build_tournament_payload, fetch_public_track_racecards

logger = logging.getLogger(__name__)

SYNC_META_PATH = BACKEND_ROOT / "data" / "last_racing_sync.json"
SYNC_TRACKS = ("gulfstream-park", "santa-anita", "churchill-downs")
SYNC_TTL_SECONDS = 5  # fallback when background sync is off

_last_source = "database"
_sync_lock = threading.Lock()
_background_task: asyncio.Task | None = None


def get_last_data_source() -> str:
    return _last_source


def get_sync_status() -> dict:
    meta = _read_sync_meta()
    return {
        "syncedAt": meta.get("syncedAt"),
        "dataSource": meta.get("dataSource") or get_last_data_source(),
        "intervalSeconds": settings.racing_sync_interval_seconds,
        "backgroundSync": settings.racing_background_sync,
    }


def run_sync_job() -> dict:
    """One scrape cycle (thread-safe, skips if previous cycle still running)."""
    if not _sync_lock.acquire(blocking=False):
        return {"synced": False, "reason": "sync_in_progress", "dataSource": get_last_data_source()}

    db = SessionLocal()
    try:
        return sync_live_tournaments(db, force=True)
    finally:
        db.close()
        _sync_lock.release()


async def background_sync_loop() -> None:
    """Scrape racecards every few seconds while the API process is running."""
    interval = max(5, settings.racing_sync_interval_seconds)
    await asyncio.sleep(1)
    logger.info("Racing background sync started (every %ss)", interval)

    while True:
        try:
            await asyncio.to_thread(run_sync_job)
        except asyncio.CancelledError:
            logger.info("Racing background sync stopped")
            raise
        except Exception:
            logger.exception("Background racing sync failed")
        await asyncio.sleep(interval)


def start_background_sync() -> asyncio.Task:
    global _background_task
    if not settings.racing_background_sync:
        return None
    if _background_task and not _background_task.done():
        return _background_task
    _background_task = asyncio.create_task(background_sync_loop())
    return _background_task


def stop_background_sync() -> None:
    global _background_task
    if _background_task and not _background_task.done():
        _background_task.cancel()
    _background_task = None


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


def _sync_horses(db: Session, race: Race, horses_data: list[dict]) -> None:
    """Update horses in place so ticket pick horseIds stay valid after sync."""
    existing = {
        h.postPosition: h for h in db.query(Horse).filter(Horse.raceId == race.id).all()
    }
    has_tickets = (
        db.query(Ticket.id).filter(Ticket.raceId == race.id).limit(1).first() is not None
    )
    seen: set[int] = set()

    for horse_data in horses_data:
        pp = int(horse_data["postPosition"])
        seen.add(pp)
        horse = existing.get(pp)
        if horse:
            horse.name = horse_data["name"]
            horse.jockey = horse_data.get("jockey")
            horse.trainer = horse_data.get("trainer")
            horse.odds = float(horse_data.get("odds", horse.odds or 5.0))
            horse.silkPrimary = horse_data.get("silkPrimary")
            horse.silkSecondary = horse_data.get("silkSecondary")
        else:
            db.add(
                Horse(
                    raceId=race.id,
                    postPosition=pp,
                    name=horse_data["name"],
                    jockey=horse_data.get("jockey"),
                    trainer=horse_data.get("trainer"),
                    odds=float(horse_data.get("odds", 5.0)),
                    silkPrimary=horse_data.get("silkPrimary"),
                    silkSecondary=horse_data.get("silkSecondary"),
                )
            )

    if not has_tickets:
        for pp, horse in existing.items():
            if pp not in seen:
                db.delete(horse)


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

    # Upsert by raceNumber — keep race/horse IDs stable so submitted tickets still resolve.
    existing_by_number = {
        r.raceNumber: r
        for r in db.query(Race).filter(Race.tournamentId == tournament.id).all()
    }
    incoming_numbers: set[int] = set()

    for race_data in payload["races"]:
        race_number = int(race_data["raceNumber"])
        incoming_numbers.add(race_number)
        race = existing_by_number.get(race_number)
        if race:
            race.name = race_data["name"]
            race.status = race_data.get("status", "upcoming")
            race.scheduledTime = str(race_data.get("scheduledTime", "TBD"))
            race.distance = race_data.get("distance")
            race.surface = race_data.get("surface")
            race.raceClass = race_data.get("raceClass")
            race.purse = race_data.get("purse")
        else:
            race = Race(
                tournamentId=tournament.id,
                raceNumber=race_number,
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
            existing_by_number[race_number] = race

        _sync_horses(db, race, race_data.get("horses", []))

    for race_number, old_race in list(existing_by_number.items()):
        if race_number in incoming_numbers:
            continue
        has_tickets = (
            db.query(Ticket.id).filter(Ticket.raceId == old_race.id).limit(1).first() is not None
        )
        if has_tickets:
            continue
        db.query(Horse).filter(Horse.raceId == old_race.id).delete(synchronize_session=False)
        db.delete(old_race)

    ensure_seven_races_for_tournament(db, tournament)

    return tournament


def ensure_seven_races_for_tournament(db: Session, tournament: Tournament) -> bool:
    """Guarantee races 1–7 exist so each ticket can complete 7 strategies."""
    existing = {
        r.raceNumber: r
        for r in db.query(Race).filter(Race.tournamentId == tournament.id).all()
    }
    changed = False

    for race_number in range(1, RACES_PER_TOURNAMENT + 1):
        if race_number in existing:
            continue
        race = Race(
            tournamentId=tournament.id,
            raceNumber=race_number,
            name=f"Race {race_number}",
            status="upcoming",
            scheduledTime="TBD",
            distance=1600,
            surface="Dirt",
            raceClass="Open",
            purse=0,
        )
        db.add(race)
        db.flush()
        for post in range(1, 9):
            silk_idx = (race_number + post) % 6
            colors = [
                ("#e11d48", "#fbbf24"),
                ("#2563eb", "#ffffff"),
                ("#16a34a", "#000000"),
                ("#7c3aed", "#f59e0b"),
                ("#dc2626", "#1d4ed8"),
                ("#0891b2", "#fde047"),
            ]
            primary, secondary = colors[silk_idx]
            db.add(
                Horse(
                    raceId=race.id,
                    postPosition=post,
                    name=f"Runner {post}",
                    jockey="TBA",
                    trainer="TBA",
                    odds=5.0 + (post % 4),
                    silkPrimary=primary,
                    silkSecondary=secondary,
                )
            )
        changed = True

    if changed:
        tournament.totalRaces = RACES_PER_TOURNAMENT

    return changed


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
