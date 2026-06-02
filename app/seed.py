import json
import random
from datetime import datetime

from app.constants import RACES_PER_TOURNAMENT
from app.models import (
    Horse,
    LeaderboardEntry,
    Race,
    RaceResult,
    Ticket,
    Tournament,
    User,
    UserStats,
)
from app.scoring import score_ticket

SILK_COLORS = [
    {"primary": "#e11d48", "secondary": "#fbbf24"},
    {"primary": "#2563eb", "secondary": "#ffffff"},
    {"primary": "#16a34a", "secondary": "#000000"},
    {"primary": "#7c3aed", "secondary": "#f59e0b"},
    {"primary": "#dc2626", "secondary": "#1d4ed8"},
    {"primary": "#0891b2", "secondary": "#fde047"},
    {"primary": "#ea580c", "secondary": "#1e293b"},
    {"primary": "#4f46e5", "secondary": "#f43f5e"},
]

HORSE_NAMES = [
    "Thunder Strike", "Golden Spirit", "Midnight Runner", "Silver Blaze",
    "Iron Warrior", "Royal Command", "Storm Chaser", "Dark Phantom",
    "Blazing Star", "Noble Quest", "Wild Fortune", "Diamond Edge",
]

JOCKEY_NAMES = ["Luis Saez", "Irad Ortiz Jr", "Joel Rosario", "Flavien Prat", "John Velazquez"]
TRAINER_NAMES = ["Todd Pletcher", "Bob Baffert", "Chad Brown", "Steve Asmussen"]

FAKE_USERS = [
    "ThunderHoof", "LuckyStrike", "GoldenGallop", "SilverSpur", "IronRider",
    "RoyalFlush", "StormChaser", "DarkHorse", "BravePick", "NobleQuest",
    "WildCard", "DiamondEdge", "CrimsonBolt", "ShadowDancer", "StarPicker",
    "FastLegend", "TitanForce", "VelvetStorm", "CrystalArrow", "ScarletFury",
    "DesertWind", "CosmicFlare", "FalconRidge", "AmberBlaze", "SteelHeart",
    "NightRider", "GoldenArrow", "RebelCrown", "SilentStorm", "MidnightGold",
]

TOURNAMENTS = [
    {
        "slug": "gulfstream-park-2026",
        "name": "Gulfstream Park Championship",
        "track": "Gulfstream Park",
        "location": "Hallandale Beach, FL",
        "status": "live",
        "totalRaces": RACES_PER_TOURNAMENT,
        "currentRace": 4,
        "date": datetime(2026, 5, 26, 14, 0, 0),
        "description": "Premier South Florida racing event featuring top thoroughbreds",
    },
    {
        "slug": "churchill-downs-classic",
        "name": "Churchill Downs Classic",
        "track": "Churchill Downs",
        "location": "Louisville, KY",
        "status": "live",
        "totalRaces": RACES_PER_TOURNAMENT,
        "currentRace": 7,
        "date": datetime(2026, 5, 26, 13, 0, 0),
        "description": "Historic Kentucky racing with world-class competition",
    },
    {
        "slug": "santa-anita-stakes",
        "name": "Santa Anita Stakes",
        "track": "Santa Anita Park",
        "location": "Arcadia, CA",
        "status": "upcoming",
        "totalRaces": RACES_PER_TOURNAMENT,
        "currentRace": 0,
        "date": datetime(2026, 5, 27, 17, 0, 0),
        "description": "West Coast premier thoroughbred racing series",
    },
]


def _odds():
    ranges = [(1.5, 3.0, 15), (3.0, 6.0, 30), (6.0, 12.0, 30), (12.0, 25.0, 25)]
    total = sum(r[2] for r in ranges)
    rand = random.random() * total
    for lo, hi, weight in ranges:
        rand -= weight
        if rand <= 0:
            return round(lo + random.random() * (hi - lo), 2)
    return 5.0


def _shuffle(arr):
    a = list(arr)
    random.shuffle(a)
    return a


def ensure_seeded_if_empty(db) -> dict | None:
    """Populate demo tournaments when the database has none (e.g. fresh Render deploy)."""
    if db.query(Tournament).count() > 0:
        return None
    return run_seed(db)


def run_seed(db):
    for model in (RaceResult, Ticket, LeaderboardEntry, UserStats, Horse, Race, Tournament, User):
        db.query(model).delete()
    db.commit()

    colors = ["#7c3aed", "#e11d48", "#2563eb", "#16a34a", "#ea580c", "#0891b2", "#d946ef"]
    users = []
    for i, name in enumerate(FAKE_USERS):
        is_guest = i % 5 == 0
        user = User(
            username=name,
            avatarColor=random.choice(colors),
            isGuest=is_guest,
            gameMode=1 if is_guest else 2,
            passwordHash=None if is_guest else "$2a$10$placeholder_hash_for_seed_data",
        )
        db.add(user)
        db.flush()
        db.add(UserStats(userId=user.id))
        users.append(user)
    db.commit()

    name_idx = 0
    for t_data in TOURNAMENTS:
        tournament = Tournament(**t_data)
        db.add(tournament)
        db.flush()

        for rn in range(1, t_data["totalRaces"] + 1):
            is_finished = rn < t_data["currentRace"]
            is_open = rn == t_data["currentRace"]
            status = "finished" if is_finished else ("open" if is_open else "upcoming")
            hour = 13 + rn // 2
            minute = "30" if rn % 2 == 0 else "00"

            race = Race(
                tournamentId=tournament.id,
                raceNumber=rn,
                name=f"Race {rn}",
                status=status,
                scheduledTime=f"{hour}:{minute} PM",
                distance=random.choice([1100, 1200, 1400, 1600, 1800, 2000]),
                surface=random.choice(["Dirt", "Turf", "Synthetic"]),
                raceClass=random.choice(["Maiden", "Claiming", "Allowance", "Stakes"]),
                purse=random.choice([25000, 50000, 75000, 100000]),
            )
            db.add(race)
            db.flush()

            horses_in_race = 8 + random.randint(0, 4)
            horses = []
            for pp in range(1, horses_in_race + 1):
                silk = SILK_COLORS[(name_idx + pp) % len(SILK_COLORS)]
                horse = Horse(
                    raceId=race.id,
                    postPosition=pp,
                    name=HORSE_NAMES[name_idx % len(HORSE_NAMES)],
                    jockey=JOCKEY_NAMES[(name_idx + pp) % len(JOCKEY_NAMES)],
                    trainer=TRAINER_NAMES[(name_idx + pp) % len(TRAINER_NAMES)],
                    odds=_odds(),
                    silkPrimary=silk["primary"],
                    silkSecondary=silk["secondary"],
                )
                db.add(horse)
                horses.append(horse)
                name_idx += 1
            db.flush()

            if is_finished:
                finishing = _shuffle(horses)
                for pos in range(1, min(len(finishing), 5) + 1):
                    db.add(RaceResult(raceId=race.id, horseId=finishing[pos - 1].id, position=pos))
                db.flush()

                result_dicts = [
                    {"position": pos, "horseId": finishing[pos - 1].id}
                    for pos in range(1, min(len(finishing), 5) + 1)
                ]
                for user in _shuffle(users)[: random.randint(10, 24)]:
                    strategy = random.choice(["full_point", "dual_point", "smart_pick"])
                    picks_count = {"full_point": 1, "dual_point": 2, "smart_pick": 3}[strategy]
                    picks = [h.id for h in _shuffle(horses)[:picks_count]]
                    points = score_ticket(strategy, picks, result_dicts, horses)

                    exists = (
                        db.query(Ticket)
                        .filter(Ticket.userId == user.id, Ticket.raceId == race.id, Ticket.ticketNumber == 1)
                        .first()
                    )
                    if exists:
                        continue

                    db.add(
                        Ticket(
                            userId=user.id,
                            raceId=race.id,
                            tournamentId=tournament.id,
                            ticketNumber=1,
                            strategy=strategy,
                            picks=json.dumps(picks),
                            pointsEarned=points,
                            isScored=True,
                        )
                    )
                    entry = (
                        db.query(LeaderboardEntry)
                        .filter(
                            LeaderboardEntry.userId == user.id,
                            LeaderboardEntry.tournamentId == tournament.id,
                            LeaderboardEntry.ticketNumber == 1,
                        )
                        .first()
                    )
                    if entry:
                        entry.totalPoints += points
                        entry.racesPlayed += 1
                        if strategy == "full_point":
                            entry.fullPoints += points
                        elif strategy == "dual_point":
                            entry.dualPoints += points
                        else:
                            entry.smartPoints += points
                    else:
                        db.add(
                            LeaderboardEntry(
                                userId=user.id,
                                tournamentId=tournament.id,
                                ticketNumber=1,
                                totalPoints=points,
                                racesPlayed=1,
                                fullPoints=points if strategy == "full_point" else 0,
                                dualPoints=points if strategy == "dual_point" else 0,
                                smartPoints=points if strategy == "smart_pick" else 0,
                            )
                        )
                    stats = db.query(UserStats).filter(UserStats.userId == user.id).first()
                    if stats:
                        stats.totalPoints += points
                        stats.totalRaces += 1

    db.commit()

    return {
        "message": "Database seeded successfully",
        "stats": {
            "tournaments": db.query(Tournament).count(),
            "races": db.query(Race).count(),
            "horses": db.query(Horse).count(),
            "tickets": db.query(Ticket).count(),
            "users": db.query(User).count(),
        },
    }
