import random
import string
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Header, HTTPException

from app.config import settings

STRATEGIES = ("full_point", "dual_point", "smart_pick")


def sign_token(user_id: int, username: str, *, is_guest: bool = False) -> str:
    """
    Registered users: 30-day JWT session.
    Guest users: long-lived token — the guest profile in DB does not expire;
    access is lost only if the client loses token/guestToken without registering.
    """
    payload = {
        "userId": user_id,
        "username": username,
        "isGuest": is_guest,
    }
    if is_guest:
        payload["exp"] = datetime.now(timezone.utc) + timedelta(days=3650)
    else:
        payload["exp"] = datetime.now(timezone.utc) + timedelta(days=30)
    token = jwt.encode(payload, settings.jwt_secret, algorithm="HS256")
    return token if isinstance(token, str) else token.decode()


def verify_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode(), password_hash.encode())


def get_bearer_user(authorization: str | None = Header(default=None)) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    payload = verify_token(authorization[7:])
    if not payload or "userId" not in payload:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return payload


def require_admin(x_admin_secret: str | None = Header(default=None, alias="x-admin-secret")):
    expected = settings.admin_secret
    if not expected:
        if settings.environment == "development":
            return
        raise HTTPException(status_code=503, detail="Admin not configured")
    if x_admin_secret != expected:
        raise HTTPException(status_code=403, detail="Forbidden")


def generate_guest_token() -> str:
    return "guest_" + "".join(random.choices(string.ascii_lowercase + string.digits, k=12))


def generate_guest_username() -> str:
    adjectives = ["Swift", "Lucky", "Bold", "Wild", "Royal", "Golden", "Silver", "Iron", "Dark", "Brave"]
    nouns = ["Rider", "Runner", "Phantom", "Storm", "Spirit", "Arrow", "Crown", "Knight", "Star", "Blaze"]
    return f"{random.choice(adjectives)}{random.choice(nouns)}{random.randint(0, 9999)}"
