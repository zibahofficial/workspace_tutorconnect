"""Subject vocabulary + student favourites (saved tutors)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from auth import get_current_user, require_roles
from database import get_db
from helpers import log_activity, tutor_summary
from models import (
    ActivityAction,
    Favorite,
    StudentProfile,
    Subject,
    TutorProfile,
    TutorStatus,
    TutorSubject,
    User,
    UserRole,
)
from schemas import Message, SubjectCreate

router = APIRouter(tags=["Subjects & favourites"])


# --------------------------------------------------------------------------- #
# Subjects (public read)
# --------------------------------------------------------------------------- #
@router.get("/subjects", summary="All subjects with live tutor counts")
def list_subjects(
    category: Optional[str] = Query(None, max_length=80),
    q: Optional[str] = Query(None, max_length=80),
    only_with_tutors: bool = Query(False),
    db: Session = Depends(get_db),
):
    counts = dict(
        db.execute(
            select(TutorSubject.subject_id, func.count(TutorSubject.id)).group_by(
                TutorSubject.subject_id
            )
        ).all()
    )
    stmt = select(Subject).where(Subject.is_active.is_(True))
    if category:
        stmt = stmt.where(Subject.category.ilike(f"%{category.strip()}%"))
    if q:
        stmt = stmt.where(Subject.name.ilike(f"%{q.strip()}%"))
    stmt = stmt.order_by(Subject.name)

    items: List[Dict[str, Any]] = []
    for subject in db.scalars(stmt).all():
        count = int(counts.get(subject.id, 0))
        if only_with_tutors and count == 0:
            continue
        items.append(
            {
                "id": subject.id,
                "name": subject.name,
                "category": subject.category,
                "icon": subject.icon,
                "tutor_count": count,
            }
        )
    return {"items": items, "total": len(items)}


@router.get("/subjects/categories", summary="Distinct subject categories")
def subject_categories(db: Session = Depends(get_db)):
    rows = db.scalars(
        select(Subject.category)
        .where(Subject.is_active.is_(True), Subject.category.is_not(None))
        .distinct()
        .order_by(Subject.category)
    ).all()
    return list(rows)


@router.post(
    "/subjects",
    status_code=status.HTTP_201_CREATED,
    summary="Admin: add a subject",
)
def create_subject(
    payload: SubjectCreate,
    current_user: User = Depends(require_roles(UserRole.ADMIN)),
    db: Session = Depends(get_db),
):
    name = payload.name.strip()
    existing = db.scalar(select(Subject).where(func.lower(Subject.name) == name.lower()))
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=f"'{existing.name}' already exists."
        )
    subject = Subject(name=name, category=payload.category, icon=payload.icon)
    db.add(subject)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="That subject already exists."
        ) from exc
    db.refresh(subject)
    return {
        "detail": f"Subject '{subject.name}' added.",
        "data": {
            "id": subject.id,
            "name": subject.name,
            "category": subject.category,
            "icon": subject.icon,
            "tutor_count": 0,
        },
    }


@router.put("/subjects/{subject_id}", summary="Admin: rename a subject")
def update_subject(
    subject_id: int,
    payload: SubjectCreate,
    current_user: User = Depends(require_roles(UserRole.ADMIN)),
    db: Session = Depends(get_db),
):
    subject = db.get(Subject, subject_id)
    if subject is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subject not found.")
    name = payload.name.strip()
    clash = db.scalar(
        select(Subject).where(func.lower(Subject.name) == name.lower(), Subject.id != subject_id)
    )
    if clash is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=f"'{clash.name}' already exists."
        )
    subject.name = name
    subject.category = payload.category
    subject.icon = payload.icon
    db.commit()
    db.refresh(subject)
    return {"detail": f"Subject updated to '{subject.name}'."}


@router.delete("/subjects/{subject_id}", response_model=Message, summary="Admin: remove a subject")
def delete_subject(
    subject_id: int,
    current_user: User = Depends(require_roles(UserRole.ADMIN)),
    db: Session = Depends(get_db),
):
    subject = db.get(Subject, subject_id)
    if subject is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subject not found.")

    in_use = int(
        db.scalar(
            select(func.count(TutorSubject.id)).where(TutorSubject.subject_id == subject_id)
        )
        or 0
    )
    if in_use:
        # Soft-delete instead of breaking referential integrity.
        subject.is_active = False
        db.commit()
        return {
            "detail": (
                f"'{subject.name}' is used by {in_use} tutor profile(s), so it was hidden "
                "instead of deleted."
            )
        }

    name = subject.name
    db.delete(subject)
    db.commit()
    return {"detail": f"Subject '{name}' deleted."}


# --------------------------------------------------------------------------- #
# Favourites (saved tutors)
# --------------------------------------------------------------------------- #
def _student(db: Session, user: User) -> StudentProfile:
    profile = db.scalar(select(StudentProfile).where(StudentProfile.user_id == user.id))
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Student profile not found."
        )
    return profile


@router.get("/favorites", summary="My saved tutors")
def list_favorites(
    current_user: User = Depends(require_roles(UserRole.STUDENT)),
    db: Session = Depends(get_db),
):
    student = _student(db, current_user)
    rows = db.scalars(
        select(Favorite).where(Favorite.student_id == student.id).order_by(Favorite.created_at.desc())
    ).all()
    return [tutor_summary(db, row.tutor_profile, is_favorite=True) for row in rows]


@router.post("/favorites/{tutor_id}", status_code=status.HTTP_201_CREATED, summary="Save a tutor")
def add_favorite(
    tutor_id: int,
    current_user: User = Depends(require_roles(UserRole.STUDENT)),
    db: Session = Depends(get_db),
):
    student = _student(db, current_user)
    profile = db.get(TutorProfile, tutor_id)
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tutor not found.")

    existing = db.scalar(
        select(Favorite).where(
            Favorite.student_id == student.id, Favorite.tutor_profile_id == tutor_id
        )
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="This tutor is already saved."
        )

    favorite = Favorite(student_id=student.id, tutor_profile_id=tutor_id)
    db.add(favorite)
    db.commit()
    db.refresh(favorite)
    return {
        "detail": f"{profile.user.full_name} saved to your list.",
        "data": {"id": favorite.id, "tutor_id": tutor_id, "is_favorite": True},
    }


@router.delete("/favorites/{tutor_id}", response_model=Message, summary="Remove a saved tutor")
def remove_favorite(
    tutor_id: int,
    current_user: User = Depends(require_roles(UserRole.STUDENT)),
    db: Session = Depends(get_db),
):
    student = _student(db, current_user)
    favorite = db.scalar(
        select(Favorite).where(
            Favorite.student_id == student.id, Favorite.tutor_profile_id == tutor_id
        )
    )
    if favorite is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="That tutor is not in your saved list."
        )
    db.delete(favorite)
    db.commit()
    return {"detail": "Removed from your saved tutors.", "data": {"tutor_id": tutor_id, "is_favorite": False}}


@router.post("/favorites/{tutor_id}/toggle", summary="Toggle saved state")
def toggle_favorite(
    tutor_id: int,
    current_user: User = Depends(require_roles(UserRole.STUDENT)),
    db: Session = Depends(get_db),
):
    student = _student(db, current_user)
    profile = db.get(TutorProfile, tutor_id)
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tutor not found.")

    favorite = db.scalar(
        select(Favorite).where(
            Favorite.student_id == student.id, Favorite.tutor_profile_id == tutor_id
        )
    )
    if favorite is None:
        db.add(Favorite(student_id=student.id, tutor_profile_id=tutor_id))
        db.commit()
        return {
            "detail": f"{profile.user.full_name} saved to your list.",
            "data": {"tutor_id": tutor_id, "is_favorite": True},
        }
    db.delete(favorite)
    db.commit()
    return {
        "detail": f"{profile.user.full_name} removed from your saved list.",
        "data": {"tutor_id": tutor_id, "is_favorite": False},
    }
