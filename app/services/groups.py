"""Group communities and hologram system (requirements v1.1 section 9)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session, joinedload

from app.models import Group, GroupHologram, GroupHologramCooldown, GroupMember, User

HOLOGRAM_COOLDOWN_MINUTES = 5
MAX_ADMINS = 5
HOLOGRAM_VERSIONS = ("purple", "aqua", "yellow", "multicolor")
HOLOGRAM_MESSAGE_MAX = 160


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _is_admin_role(role: str) -> bool:
    return role in ("founder", "admin")


def get_membership(db: Session, group_id: int, user_id: int) -> GroupMember | None:
    return (
        db.query(GroupMember)
        .filter(GroupMember.groupId == group_id, GroupMember.userId == user_id)
        .first()
    )


def admin_slots(db: Session, group_id: int, privacy_mode: bool) -> list[dict]:
    admins = (
        db.query(GroupMember, User)
        .join(User, User.id == GroupMember.userId)
        .filter(
            GroupMember.groupId == group_id,
            GroupMember.role.in_(("founder", "admin")),
            GroupMember.status == "active",
        )
        .all()
    )
    admins_sorted = sorted(
        admins,
        key=lambda pair: (0 if pair[0].role == "founder" else 1 if pair[0].role == "admin" else 2, pair[0].createdAt or _utcnow()),
    )
    slots = []
    for member, user in admins_sorted:
        slots.append(
            {
                "role": member.role,
                "userId": user.id,
                "username": user.username,
                "avatarColor": user.avatarColor,
                "filled": True,
            }
        )
    founder_count = sum(1 for s in slots if s["role"] == "founder")
    admin_count = sum(1 for s in slots if s["role"] == "admin")
    if founder_count == 0 and slots:
        slots[0]["role"] = "founder"

    if not privacy_mode:
        while admin_count < MAX_ADMINS:
            slots.append({"role": "admin", "filled": False, "available": True})
            admin_count += 1
    return slots


def hologram_status(db: Session, group_id: int) -> dict:
    row = db.query(GroupHologramCooldown).filter(GroupHologramCooldown.groupId == group_id).first()
    now = _utcnow()
    if row and row.nextAvailableAt > now:
        remaining = int((row.nextAvailableAt - now).total_seconds())
        return {"available": False, "secondsRemaining": max(0, remaining)}
    return {"available": True, "secondsRemaining": 0}


def build_hologram_previews(message: str, emoji: str | None) -> list[dict]:
    text = (message or "").strip()[:HOLOGRAM_MESSAGE_MAX]
    prefix = f"{emoji} " if emoji else ""
    return [
        {"version": v, "preview": f"{prefix}{text}", "label": v}
        for v in HOLOGRAM_VERSIONS
    ]


def group_payload(db: Session, group: Group, viewer_id: int | None) -> dict:
    membership = get_membership(db, group.id, viewer_id) if viewer_id else None
    member_rows = (
        db.query(GroupMember, User)
        .join(User, User.id == GroupMember.userId)
        .filter(GroupMember.groupId == group.id, GroupMember.status == "active")
        .all()
    )
    latest_hologram = (
        db.query(GroupHologram, User)
        .join(User, User.id == GroupHologram.authorId)
        .filter(GroupHologram.groupId == group.id)
        .order_by(GroupHologram.sentAt.desc())
        .first()
    )
    holo = None
    if latest_hologram:
        h, author = latest_hologram
        holo = {
            "message": h.message,
            "emoji": h.emoji,
            "colorVersion": h.colorVersion,
            "author": author.username,
            "sentAt": h.sentAt.isoformat() if h.sentAt else None,
        }

    can_publish = membership is not None and _is_admin_role(membership.role)
    return {
        "id": group.id,
        "name": group.name,
        "founderId": group.founderId,
        "privacyMode": group.privacyMode,
        "memberCount": len(member_rows),
        "members": [
            {
                "userId": u.id,
                "username": u.username,
                "avatarColor": u.avatarColor,
                "role": m.role,
            }
            for m, u in member_rows
        ],
        "adminSlots": admin_slots(db, group.id, group.privacyMode),
        "viewerRole": membership.role if membership else None,
        "canPublishHologram": can_publish,
        "hologramStatus": hologram_status(db, group.id),
        "activeHologram": holo,
    }
