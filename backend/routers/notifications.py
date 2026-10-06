"""In-app notification endpoints (the navbar bell)."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db
from models import Notification, User
from schemas import Message, NotificationList, NotificationOut

router = APIRouter(prefix="/notifications", tags=["Notifications"])


def _serialize(note: Notification) -> dict:
    return {
        "id": note.id,
        "type": note.type.value if hasattr(note.type, "value") else str(note.type),
        "title": note.title,
        "body": note.body,
        "link": note.link,
        "is_read": note.is_read,
        "created_at": note.created_at.isoformat() if note.created_at else None,
    }


@router.get("", response_model=NotificationList, summary="My notifications")
def list_notifications(
    unread_only: bool = Query(False),
    limit: int = Query(25, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    stmt = select(Notification).where(Notification.user_id == current_user.id)
    if unread_only:
        stmt = stmt.where(Notification.is_read.is_(False))
    rows = db.scalars(stmt.order_by(Notification.created_at.desc()).limit(limit)).all()
    unread = int(
        db.scalar(
            select(func.count(Notification.id)).where(
                Notification.user_id == current_user.id, Notification.is_read.is_(False)
            )
        )
        or 0
    )
    return {"items": [_serialize(n) for n in rows], "unread_count": unread}


@router.get("/unread-count", summary="Unread notification count")
def unread_count(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    count = int(
        db.scalar(
            select(func.count(Notification.id)).where(
                Notification.user_id == current_user.id, Notification.is_read.is_(False)
            )
        )
        or 0
    )
    return {"unread_count": count}


@router.post("/{notification_id}/read", response_model=Message, summary="Mark one as read")
def mark_read(
    notification_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    note = db.get(Notification, notification_id)
    if note is None or note.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found.")
    note.is_read = True
    db.commit()
    return {"detail": "Notification marked as read."}


@router.post("/read-all", response_model=Message, summary="Mark everything as read")
def mark_all_read(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    result = db.execute(
        update(Notification)
        .where(Notification.user_id == current_user.id, Notification.is_read.is_(False))
        .values(is_read=True)
    )
    db.commit()
    return {"detail": f"{result.rowcount} notification(s) marked as read."}


@router.delete("/{notification_id}", response_model=Message, summary="Delete a notification")
def delete_notification(
    notification_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    note = db.get(Notification, notification_id)
    if note is None or note.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found.")
    db.delete(note)
    db.commit()
    return {"detail": "Notification deleted."}
