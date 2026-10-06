"""Review endpoints — ratings are always recomputed from real review rows."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from auth import get_current_user, get_owned_tutor_profile, require_roles
from database import get_db
from helpers import log_activity, notify, rating_aggregate, rating_breakdown, review_out
from models import (
    ActivityAction,
    BookingRequest,
    NotificationType,
    RequestStatus,
    Review,
    StudentProfile,
    TutorProfile,
    User,
    UserRole,
)
from schemas import Message, ReviewCreate, ReviewUpdate, TutorRatingSummary

router = APIRouter(tags=["Reviews"])


def _age_of(moment: Optional[datetime]) -> timedelta:
    """Age of a DB timestamp.

    SQLite hands back naive UTC datetimes while PostgreSQL returns aware ones,
    so both sides of the subtraction are normalised to naive UTC.
    """
    now = datetime.now(timezone.utc)
    if moment is None:
        return timedelta(0)
    if moment.tzinfo is not None:
        moment = moment.astimezone(timezone.utc).replace(tzinfo=None)
    return now.replace(tzinfo=None) - moment


def _student_profile(db: Session, user: User) -> StudentProfile:
    profile = db.scalar(select(StudentProfile).where(StudentProfile.user_id == user.id))
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Student profile not found."
        )
    return profile


def _get_review(db: Session, review_id: int) -> Review:
    review = db.get(Review, review_id)
    if review is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Review #{review_id} does not exist."
        )
    return review


def _can_manage(user: User, review: Review) -> bool:
    if user.role == UserRole.ADMIN:
        return True
    return review.student_profile is not None and review.student_profile.user_id == user.id


# --------------------------------------------------------------------------- #
# CREATE
# --------------------------------------------------------------------------- #
@router.post(
    "/reviews",
    status_code=status.HTTP_201_CREATED,
    summary="Review a completed session",
)
def create_review(
    payload: ReviewCreate,
    current_user: User = Depends(require_roles(UserRole.STUDENT)),
    db: Session = Depends(get_db),
):
    student = _student_profile(db, current_user)
    booking = db.get(BookingRequest, payload.booking_request_id)

    if booking is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Booking request #{payload.booking_request_id} does not exist.",
        )
    if booking.student_id != student.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only review sessions that belong to your account.",
        )
    if booking.status != RequestStatus.COMPLETED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Reviews are only allowed after a session is completed "
                f"(current status: {booking.status.value})."
            ),
        )
    if booking.review is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You have already reviewed this session. Edit your review instead.",
        )

    tutor_profile = booking.tutor_profile
    default_titles = {
        5: "Outstanding tutor",
        4: "Great session",
        3: "Good, with room to improve",
        2: "Below expectations",
        1: "Poor experience",
    }
    review = Review(
        tutor_profile_id=tutor_profile.id,
        student_id=student.id,
        booking_request_id=booking.id,
        rating=payload.rating,
        title=(payload.title or "").strip() or default_titles[payload.rating],
        comment=(payload.comment or "").strip() or None,
    )
    db.add(review)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This session has already been reviewed.",
        ) from exc
    db.refresh(review)

    agg = rating_aggregate(db, tutor_profile.id)
    notify(
        db,
        tutor_profile.user_id,
        NotificationType.REVIEW_NEW,
        f"New {payload.rating}-star review",
        f"{current_user.full_name.split()[0]} rated your "
        f"{booking.subject.name} session {payload.rating}/5. "
        f"Your average is now {agg['rating']:.1f} from {agg['review_count']} review(s).",
        link="dashboard.html?view=reviews",
    )
    log_activity(
        db,
        ActivityAction.REVIEW_CREATED,
        f"{current_user.full_name} rated {tutor_profile.user.full_name} "
        f"{payload.rating}/5 for {booking.subject.name}",
        actor_user_id=current_user.id,
        entity_type="review",
        entity_id=review.id,
    )
    db.commit()

    return {
        "detail": "Thanks! Your review is now visible on the tutor's profile.",
        "data": {
            "review": review_out(review),
            "tutor_rating": {
                "tutor_id": tutor_profile.id,
                "rating": agg["rating"],
                "review_count": agg["review_count"],
            },
        },
    }


# --------------------------------------------------------------------------- #
# READ
# --------------------------------------------------------------------------- #
@router.get("/reviews/mine", summary="Reviews I have written")
def my_reviews(
    current_user: User = Depends(
        require_roles(UserRole.STUDENT, UserRole.TUTOR, UserRole.ADMIN)
    ),
    db: Session = Depends(get_db),
):
    """Reviews written by the caller (student/admin) or received (tutor)."""
    condition: Any
    if current_user.role == UserRole.TUTOR:
        profile = get_owned_tutor_profile(db, current_user)
        if profile is None:
            return {"items": [], "total": 0, "average_rating": None, "review_count": 0}
        condition = Review.tutor_profile_id == profile.id
    else:
        student = _student_profile(db, current_user)
        condition = Review.student_id == student.id

    rows = db.scalars(
        select(Review)
        .where(condition, Review.is_deleted.is_(False))
        .order_by(Review.created_at.desc())
    ).all()

    average: Optional[float] = None
    if current_user.role == UserRole.TUTOR and rows:
        average = round(sum(r.rating for r in rows) / len(rows), 2)

    return {
        "items": [review_out(r) for r in rows],
        "total": len(rows),
        "review_count": len(rows),
        "average_rating": average,
    }


@router.get("/reviews/{review_id}", summary="A single review")
def get_review(review_id: int, db: Session = Depends(get_db)):
    review = _get_review(db, review_id)
    if review.is_deleted:
        raise HTTPException(
            status_code=status.HTTP_410_GONE, detail="This review was removed by a moderator."
        )
    payload = review_out(review)
    payload["tutor"] = {
        "id": review.tutor_profile.id,
        "name": review.tutor_profile.user.full_name,
    }
    return payload


@router.get(
    "/tutors/{tutor_id}/rating",
    response_model=TutorRatingSummary,
    summary="Aggregate rating for a tutor",
)
def tutor_rating(tutor_id: int, db: Session = Depends(get_db)):
    profile = db.get(TutorProfile, tutor_id)
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tutor not found.")
    agg = rating_aggregate(db, tutor_id)
    return {
        "tutor_id": tutor_id,
        "rating": agg["rating"],
        "review_count": agg["review_count"],
        "breakdown": rating_breakdown(db, tutor_id),
    }


# --------------------------------------------------------------------------- #
# UPDATE
# --------------------------------------------------------------------------- #
@router.put("/reviews/{review_id}", summary="Edit your review")
def update_review(
    review_id: int,
    payload: ReviewUpdate,
    current_user: User = Depends(require_roles(UserRole.STUDENT, UserRole.ADMIN)),
    db: Session = Depends(get_db),
):
    review = _get_review(db, review_id)
    if not _can_manage(current_user, review):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your review.")
    if review.is_deleted:
        raise HTTPException(
            status_code=status.HTTP_410_GONE, detail="This review has been removed."
        )
    if current_user.role == UserRole.STUDENT:
        if _age_of(review.created_at) > timedelta(days=60):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Reviews older than 60 days can no longer be edited.",
            )

    data = payload.model_dump(exclude_unset=True, exclude_none=True)
    if not data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Nothing to update.")
    for field, value in data.items():
        setattr(review, field, value)
    db.commit()
    db.refresh(review)

    agg = rating_aggregate(db, review.tutor_profile_id)
    return {
        "detail": "Review updated. The tutor's rating has been recalculated.",
        "data": {
            "review": review_out(review),
            "tutor_rating": {"rating": agg["rating"], "review_count": agg["review_count"]},
        },
    }


# --------------------------------------------------------------------------- #
# DELETE
# --------------------------------------------------------------------------- #
@router.delete("/reviews/{review_id}", response_model=Message, summary="Delete your own review")
def delete_review(
    review_id: int,
    current_user: User = Depends(require_roles(UserRole.STUDENT)),
    db: Session = Depends(get_db),
):
    review = _get_review(db, review_id)
    if not _can_manage(current_user, review):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your review.")

    tutor_profile = review.tutor_profile
    db.delete(review)
    log_activity(
        db,
        ActivityAction.REVIEW_DELETED,
        f"{current_user.full_name} deleted their review #{review_id}",
        actor_user_id=current_user.id,
        entity_type="review",
        entity_id=review_id,
    )
    db.commit()
    agg = rating_aggregate(db, tutor_profile.id)
    return {
        "detail": "Your review was deleted and the rating recalculated.",
        "data": {"rating": agg["rating"], "review_count": agg["review_count"]},
    }
