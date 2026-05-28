from datetime import datetime

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.types import PrismaDateTime


class User(Base):
    __tablename__ = "User"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String, unique=True)
    email: Mapped[str | None] = mapped_column(String, unique=True, nullable=True)
    passwordHash: Mapped[str | None] = mapped_column(String, nullable=True)
    isGuest: Mapped[bool] = mapped_column(Boolean, default=False)
    guestToken: Mapped[str | None] = mapped_column(String, unique=True, nullable=True)
    avatarColor: Mapped[str] = mapped_column(String, default="#7c3aed")
    gameMode: Mapped[int] = mapped_column(Integer, default=2)
    createdAt: Mapped[datetime] = mapped_column(PrismaDateTime, default=datetime.utcnow)
    updatedAt: Mapped[datetime] = mapped_column(PrismaDateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    stats: Mapped["UserStats | None"] = relationship(back_populates="user", uselist=False)
    tickets: Mapped[list["Ticket"]] = relationship(back_populates="user")


class Tournament(Base):
    __tablename__ = "Tournament"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String, unique=True)
    name: Mapped[str] = mapped_column(String)
    track: Mapped[str] = mapped_column(String)
    location: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="upcoming")
    totalRaces: Mapped[int] = mapped_column(Integer)
    currentRace: Mapped[int] = mapped_column(Integer, default=0)
    date: Mapped[datetime] = mapped_column(PrismaDateTime)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    imageUrl: Mapped[str | None] = mapped_column(String, nullable=True)
    createdAt: Mapped[datetime] = mapped_column(PrismaDateTime, default=datetime.utcnow)

    races: Mapped[list["Race"]] = relationship(back_populates="tournament")
    tickets: Mapped[list["Ticket"]] = relationship(back_populates="tournament")


class Race(Base):
    __tablename__ = "Race"
    __table_args__ = (UniqueConstraint("tournamentId", "raceNumber"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tournamentId: Mapped[int] = mapped_column(ForeignKey("Tournament.id"))
    raceNumber: Mapped[int] = mapped_column(Integer)
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="upcoming")
    scheduledTime: Mapped[str | None] = mapped_column(String, nullable=True)
    distance: Mapped[int | None] = mapped_column(Integer, nullable=True)
    surface: Mapped[str | None] = mapped_column(String, nullable=True)
    raceClass: Mapped[str | None] = mapped_column(String, nullable=True)
    purse: Mapped[int | None] = mapped_column(Integer, nullable=True)
    createdAt: Mapped[datetime] = mapped_column(PrismaDateTime, default=datetime.utcnow)

    tournament: Mapped["Tournament"] = relationship(back_populates="races")
    horses: Mapped[list["Horse"]] = relationship(back_populates="race", order_by="Horse.postPosition")
    results: Mapped[list["RaceResult"]] = relationship(back_populates="race")
    tickets: Mapped[list["Ticket"]] = relationship(back_populates="race")


class Horse(Base):
    __tablename__ = "Horse"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    raceId: Mapped[int] = mapped_column(ForeignKey("Race.id"))
    postPosition: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String)
    jockey: Mapped[str | None] = mapped_column(String, nullable=True)
    trainer: Mapped[str | None] = mapped_column(String, nullable=True)
    odds: Mapped[float] = mapped_column(Float)
    silkPrimary: Mapped[str | None] = mapped_column(String, nullable=True)
    silkSecondary: Mapped[str | None] = mapped_column(String, nullable=True)

    race: Mapped["Race"] = relationship(back_populates="horses")


class RaceResult(Base):
    __tablename__ = "RaceResult"
    __table_args__ = (
        UniqueConstraint("raceId", "position"),
        UniqueConstraint("raceId", "horseId"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    raceId: Mapped[int] = mapped_column(ForeignKey("Race.id"))
    horseId: Mapped[int] = mapped_column(ForeignKey("Horse.id"))
    position: Mapped[int] = mapped_column(Integer)

    race: Mapped["Race"] = relationship(back_populates="results")


class Ticket(Base):
    __tablename__ = "Ticket"
    __table_args__ = (UniqueConstraint("userId", "raceId", "ticketNumber"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    userId: Mapped[int] = mapped_column(ForeignKey("User.id"))
    raceId: Mapped[int] = mapped_column(ForeignKey("Race.id"))
    tournamentId: Mapped[int] = mapped_column(ForeignKey("Tournament.id"))
    ticketNumber: Mapped[int] = mapped_column(Integer, default=1)
    strategy: Mapped[str] = mapped_column(String)
    picks: Mapped[str] = mapped_column(String)
    pointsEarned: Mapped[int] = mapped_column(Integer, default=0)
    isScored: Mapped[bool] = mapped_column(Boolean, default=False)
    createdAt: Mapped[datetime] = mapped_column(PrismaDateTime, default=datetime.utcnow)

    user: Mapped["User"] = relationship(back_populates="tickets")
    race: Mapped["Race"] = relationship(back_populates="tickets")
    tournament: Mapped["Tournament"] = relationship(back_populates="tickets")


class LeaderboardEntry(Base):
    __tablename__ = "LeaderboardEntry"
    __table_args__ = (UniqueConstraint("userId", "tournamentId", "ticketNumber"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    userId: Mapped[int] = mapped_column(ForeignKey("User.id"))
    tournamentId: Mapped[int] = mapped_column(ForeignKey("Tournament.id"))
    ticketNumber: Mapped[int] = mapped_column(Integer, default=1)
    totalPoints: Mapped[int] = mapped_column(Integer, default=0)
    racesPlayed: Mapped[int] = mapped_column(Integer, default=0)
    fullPoints: Mapped[int] = mapped_column(Integer, default=0)
    dualPoints: Mapped[int] = mapped_column(Integer, default=0)
    smartPoints: Mapped[int] = mapped_column(Integer, default=0)
    winStreak: Mapped[int] = mapped_column(Integer, default=0)
    bestStreak: Mapped[int] = mapped_column(Integer, default=0)
    rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    previousRank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rankChange: Mapped[int] = mapped_column(Integer, default=0)
    lastPointsChange: Mapped[int] = mapped_column(Integer, default=0)
    updatedAt: Mapped[datetime] = mapped_column(PrismaDateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class UserStats(Base):
    __tablename__ = "UserStats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    userId: Mapped[int] = mapped_column(ForeignKey("User.id"), unique=True)
    totalPoints: Mapped[int] = mapped_column(Integer, default=0)
    tournamentsPlayed: Mapped[int] = mapped_column(Integer, default=0)
    totalRaces: Mapped[int] = mapped_column(Integer, default=0)
    winRate: Mapped[float] = mapped_column(Float, default=0)
    bestStreak: Mapped[int] = mapped_column(Integer, default=0)
    titles: Mapped[int] = mapped_column(Integer, default=0)
    records: Mapped[int] = mapped_column(Integer, default=0)
    updatedAt: Mapped[datetime] = mapped_column(PrismaDateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user: Mapped["User"] = relationship(back_populates="stats")


class AchievementCard(Base):
    __tablename__ = "AchievementCard"
    __table_args__ = (UniqueConstraint("userId", "cardId"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    userId: Mapped[int] = mapped_column(ForeignKey("User.id"))
    cardId: Mapped[str] = mapped_column(String)
    payload: Mapped[str] = mapped_column(String)
    earnedAt: Mapped[datetime] = mapped_column(PrismaDateTime, default=datetime.utcnow)
