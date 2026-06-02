from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth_utils import get_bearer_user
from app.database import get_db
from app.models import Group, GroupHologram, GroupHologramCooldown, GroupMember, User
from app.services.groups import (
    HOLOGRAM_COOLDOWN_MINUTES,
    HOLOGRAM_MESSAGE_MAX,
    HOLOGRAM_VERSIONS,
    admin_slots,
    build_hologram_previews,
    get_membership,
    group_payload,
    hologram_status,
    _utcnow,
)

router = APIRouter(prefix="/groups", tags=["groups"])


class CreateGroupBody(BaseModel):
    name: str = Field(min_length=3, max_length=60)
    privacyMode: bool = False


class HologramPreviewBody(BaseModel):
    message: str = Field(max_length=HOLOGRAM_MESSAGE_MAX)
    emoji: str | None = Field(default=None, max_length=8)


class SendHologramBody(BaseModel):
    message: str = Field(max_length=HOLOGRAM_MESSAGE_MAX)
    emoji: str | None = Field(default=None, max_length=8)
    colorVersion: str = "purple"


class AdminActionBody(BaseModel):
    action: str  # approve | reject


@router.get("")
def list_groups(payload: dict = Depends(get_bearer_user), db: Session = Depends(get_db)):
    user_id = payload["userId"]
    rows = (
        db.query(Group, GroupMember)
        .join(GroupMember, GroupMember.groupId == Group.id)
        .filter(GroupMember.userId == user_id, GroupMember.status == "active")
        .order_by(Group.createdAt.desc())
        .all()
    )
    return {
        "groups": [
            {
                "id": g.id,
                "name": g.name,
                "role": m.role,
                "memberCount": db.query(GroupMember)
                .filter(GroupMember.groupId == g.id, GroupMember.status == "active")
                .count(),
            }
            for g, m in rows
        ]
    }


@router.post("")
def create_group(body: CreateGroupBody, payload: dict = Depends(get_bearer_user), db: Session = Depends(get_db)):
    user_id = payload["userId"]
    group = Group(name=body.name.strip(), founderId=user_id, privacyMode=body.privacyMode)
    db.add(group)
    db.flush()
    db.add(GroupMember(groupId=group.id, userId=user_id, role="founder", status="active"))
    db.commit()
    db.refresh(group)
    return {"group": group_payload(db, group, user_id)}


@router.get("/{group_id}")
def get_group(group_id: int, payload: dict = Depends(get_bearer_user), db: Session = Depends(get_db)):
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    return {"group": group_payload(db, group, payload["userId"])}


@router.post("/{group_id}/join")
def join_group(group_id: int, payload: dict = Depends(get_bearer_user), db: Session = Depends(get_db)):
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    user_id = payload["userId"]
    existing = get_membership(db, group_id, user_id)
    if existing and existing.status == "active":
        return {"message": "Already a member", "group": group_payload(db, group, user_id)}
    if existing:
        existing.status = "active"
    else:
        db.add(GroupMember(groupId=group_id, userId=user_id, role="member", status="active"))
    db.commit()
    return {"group": group_payload(db, group, user_id)}


@router.post("/{group_id}/admin/request")
def request_admin(group_id: int, payload: dict = Depends(get_bearer_user), db: Session = Depends(get_db)):
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    user_id = payload["userId"]
    membership = get_membership(db, group_id, user_id)
    if not membership or membership.status != "active":
        raise HTTPException(status_code=403, detail="Join the group first")
    if membership.role in ("founder", "admin"):
        raise HTTPException(status_code=400, detail="Already an administrator")

    slots = admin_slots(db, group_id, group.privacyMode)
    open_slots = [s for s in slots if not s.get("filled")]
    if not open_slots:
        raise HTTPException(status_code=400, detail="No admin slots available")

    membership.status = "pending"
    membership.requestedAt = _utcnow()
    db.commit()
    return {"message": "Admin request submitted", "status": "pending"}


@router.put("/{group_id}/admin/{target_user_id}")
def manage_admin_request(
    group_id: int,
    target_user_id: int,
    body: AdminActionBody,
    payload: dict = Depends(get_bearer_user),
    db: Session = Depends(get_db),
):
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    if group.founderId != payload["userId"]:
        raise HTTPException(status_code=403, detail="Only the founder can manage admin requests")

    target = get_membership(db, group_id, target_user_id)
    if not target or target.status != "pending":
        raise HTTPException(status_code=404, detail="No pending request for this user")

    if body.action == "approve":
        admin_count = (
            db.query(GroupMember)
            .filter(
                GroupMember.groupId == group_id,
                GroupMember.role == "admin",
                GroupMember.status == "active",
            )
            .count()
        )
        if admin_count >= 5:
            raise HTTPException(status_code=400, detail="Maximum administrators reached")
        target.role = "admin"
        target.status = "active"
    elif body.action == "reject":
        target.role = "member"
        target.status = "active"
    else:
        raise HTTPException(status_code=400, detail="action must be approve or reject")

    db.commit()
    return {"group": group_payload(db, group, payload["userId"])}


@router.get("/{group_id}/hologram/status")
def get_hologram_status(group_id: int, payload: dict = Depends(get_bearer_user), db: Session = Depends(get_db)):
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    return hologram_status(db, group_id)


@router.post("/{group_id}/hologram/preview")
def preview_hologram(
    group_id: int,
    body: HologramPreviewBody,
    payload: dict = Depends(get_bearer_user),
    db: Session = Depends(get_db),
):
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    membership = get_membership(db, group_id, payload["userId"])
    if not membership or membership.role not in ("founder", "admin"):
        raise HTTPException(status_code=403, detail="Only administrators can publish holograms")
    return {"versions": build_hologram_previews(body.message, body.emoji)}


@router.post("/{group_id}/hologram")
def send_hologram(
    group_id: int,
    body: SendHologramBody,
    payload: dict = Depends(get_bearer_user),
    db: Session = Depends(get_db),
):
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    user_id = payload["userId"]
    membership = get_membership(db, group_id, user_id)
    if not membership or membership.role not in ("founder", "admin"):
        raise HTTPException(status_code=403, detail="Only administrators can publish holograms")

    status = hologram_status(db, group_id)
    if not status["available"]:
        raise HTTPException(
            status_code=429,
            detail=f"Hologram on cooldown ({status['secondsRemaining']}s remaining)",
        )

    if body.colorVersion not in HOLOGRAM_VERSIONS:
        raise HTTPException(status_code=400, detail="Invalid color version")

    message = body.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="Message is required")

    db.add(
        GroupHologram(
            groupId=group_id,
            authorId=user_id,
            message=message[:HOLOGRAM_MESSAGE_MAX],
            emoji=body.emoji,
            colorVersion=body.colorVersion,
        )
    )
    cooldown = db.query(GroupHologramCooldown).filter(GroupHologramCooldown.groupId == group_id).first()
    next_at = _utcnow() + timedelta(minutes=HOLOGRAM_COOLDOWN_MINUTES)
    if cooldown:
        cooldown.nextAvailableAt = next_at
    else:
        db.add(GroupHologramCooldown(groupId=group_id, nextAvailableAt=next_at))
    db.commit()
    return {"message": "Hologram published", "group": group_payload(db, group, user_id)}
