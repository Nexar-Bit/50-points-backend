import random

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth_utils import (
    generate_guest_token,
    generate_guest_username,
    get_bearer_user,
    hash_password,
    sign_token,
    verify_password,
)
from app.database import get_db
from app.models import User, UserStats

router = APIRouter(prefix="/auth", tags=["auth"])

COLORS = ["#7c3aed", "#e11d48", "#2563eb", "#16a34a", "#ea580c", "#0891b2", "#d946ef"]


class LoginBody(BaseModel):
    login: str | None = None
    username: str | None = None
    email: str | None = None
    password: str


class RegisterBody(BaseModel):
    username: str
    email: str | None = None
    password: str


@router.post("/login")
def login(body: LoginBody, db: Session = Depends(get_db)):
    identifier = (body.login or body.username or body.email or "").strip()
    if not identifier or not body.password:
        raise HTTPException(status_code=400, detail="Username and password are required")

    user = db.query(User).filter((User.username == identifier) | (User.email == identifier)).first()
    if not user or not user.passwordHash:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not verify_password(body.password, user.passwordHash):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = sign_token(user.id, user.username)
    return {
        "token": token,
        "user": {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "avatarColor": user.avatarColor,
            "isGuest": user.isGuest,
            "gameMode": user.gameMode,
        },
    }


@router.post("/register")
def register(body: RegisterBody, db: Session = Depends(get_db)):
    username = body.username.strip()
    if len(username) < 3 or len(username) > 20:
        raise HTTPException(status_code=400, detail="Username must be 3-20 characters")
    if len(body.password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")

    if db.query(User).filter(User.username == username).first():
        raise HTTPException(status_code=409, detail="Username already taken")
    if body.email and db.query(User).filter(User.email == body.email).first():
        raise HTTPException(status_code=409, detail="Email already registered")

    user = User(
        username=username,
        email=body.email,
        passwordHash=hash_password(body.password),
        avatarColor=random.choice(COLORS),
        gameMode=2,
        isGuest=False,
    )
    db.add(user)
    db.flush()
    db.add(UserStats(userId=user.id))
    db.commit()
    db.refresh(user)

    token = sign_token(user.id, user.username)
    return {
        "token": token,
        "user": {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "avatarColor": user.avatarColor,
            "isGuest": user.isGuest,
            "gameMode": user.gameMode,
        },
    }


@router.get("/me")
def me(payload: dict = Depends(get_bearer_user), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == payload["userId"]).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    stats = db.query(UserStats).filter(UserStats.userId == user.id).first()
    return {
        "user": {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "avatarColor": user.avatarColor,
            "isGuest": user.isGuest,
            "gameMode": user.gameMode,
            "stats": {
                "totalPoints": stats.totalPoints,
                "tournamentsPlayed": stats.tournamentsPlayed,
                "totalRaces": stats.totalRaces,
                "winRate": stats.winRate,
                "bestStreak": stats.bestStreak,
                "titles": stats.titles,
                "records": stats.records,
            }
            if stats
            else None,
        }
    }


@router.post("/guest")
def guest(db: Session = Depends(get_db)):
    for _ in range(10):
        username = generate_guest_username()
        if db.query(User).filter(User.username == username).first():
            continue
        guest_token = generate_guest_token()
        user = User(
            username=username,
            isGuest=True,
            guestToken=guest_token,
            avatarColor=random.choice(COLORS),
            gameMode=1,
        )
        db.add(user)
        db.flush()
        db.add(UserStats(userId=user.id))
        db.commit()
        db.refresh(user)
        token = sign_token(user.id, user.username)
        return {
            "token": token,
            "guestToken": guest_token,
            "user": {
                "id": user.id,
                "username": user.username,
                "avatarColor": user.avatarColor,
                "isGuest": user.isGuest,
                "gameMode": user.gameMode,
            },
        }
    raise HTTPException(status_code=500, detail="Could not create guest user")
