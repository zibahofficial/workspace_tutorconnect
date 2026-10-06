"""Student/parent profile endpoints (read & update own profile)."""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from auth import get_current_user, require_roles
from database import get_db
from helpers import log_activity
from models import (
    ActivityAction,
    BookingRequest,
    Favorite,
    RequestStatus,
    Review,
    StudentProfile,
    TeachingMode,
    User,
    UserRole,
)
from schemas import StudentProfileUpdate

router = APIRouter(prefix="/students", tags=["Students"])


def _profile(db: Session, user: User) -> StudentProfile:
    profile = db.scalar(select(StudentProfile).where(StudentProfile.user_id == user.id))
    if profile is None:
        profile = StudentProfile(user_id=user.id)
        db.add(profile)
        db.commit()
        db.refresh(profile)
    return profile


def _serialize(db: Session, profile: StudentProfile) -> Dict[str, Any]:
    counts = {s.value: 0 for s in RequestStatus}
    rows = db.execute(
        select(BookingRequest.status, func.count(BookingRequest.id))
        .where(BookingRequest.student_id == profile.id)
        .group_by(BookingRequest.status)
    ).all()
    for row in rows:
        counts[row[0].value] = int(row[1])

    return {
        "id": profile.id,
        "user_id": profile.user_id,
        "education_level": profile.education_level,
        "guardian_name": profile.guardian_name,
        "city": profile.city,
        "state": profile.state,
        "learning_goals": profile.learning_goals,
        "preferred_mode": profile.preferred_mode.value if profile.preferred_mode else None,
        "max_budget": float(profile.max_budget) if profile.max_budget is not None else None,
        "counts": counts,
        "reviews_written": int(
            db.scalar(select(func.count(Review.id)).where(Review.student_id == profile.id)) or 0
        ),
        "favorites": int(
            db.scalar(select(func.count(Favorite.id)).where(Favorite.student_id == profile.id)) or 0
        ),
    }


@router.get("/me", summary="My student profile")
def read_my_profile(
    current_user: User = Depends(require_roles(UserRole.STUDENT, UserRole.ADMIN)),
    db: Session = Depends(get_db),
):
    return _serialize(db, _profile(db, current_user))


@router.put("/me", summary="Update my student profile")
def update_my_profile(
    payload: StudentProfileUpdate,
    current_user: User = Depends(require_roles(UserRole.STUDENT)),
    db: Session = Depends(get_db),
):
    profile = _profile(db, current_user)
    data = payload.model_dump(exclude_unset=True)
    avatar_url = data.pop("avatar_url", None)

    for field, value in data.items():
        if field == "preferred_mode":
            profile.preferred_mode = TeachingMode(value) if value else None
        else:
            setattr(profile, field, value)

    if avatar_url is not None:
        current_user.avatar_url = avatar_url

    log_activity(
        db,
        ActivityAction.USER_REGISTERED,
        f"{current_user.full_name} updated their student profile",
        actor_user_id=current_user.id,
        entity_type="student_profile",
        entity_id=profile.id,
    )
    db.commit()
    db.refresh(profile)
    return {"detail": "Profile updated.", "data": _serialize(db, profile)}
