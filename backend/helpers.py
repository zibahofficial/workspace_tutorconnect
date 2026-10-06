"""
Shared helpers: notifications, activity log, rating aggregation, serialisers.

Keeping these in one module means every router produces identical, predictable
payload shapes — and ratings are ALWAYS derived from real review rows.
"""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from models import (
    DAYS_OF_WEEK,
    DAY_INDEX,
    ActivityAction,
    ActivityLog,
    Availability,
    AvailabilityException,
    BookingRequest,
    Notification,
    NotificationType,
    RequestStatus,
    Review,
    StudentProfile,
    Subject,
    TeachingMode,
    TutorProfile,
    TutorStatus,
    User,
    UserRole,
    fmt_time,
)


# --------------------------------------------------------------------------- #
# Notifications
# --------------------------------------------------------------------------- #
def notify(
    db: Session,
    user_id: int,
    type_: NotificationType,
    title: str,
    body: Optional[str] = None,
    link: Optional[str] = None,
) -> Notification:
    note = Notification(
        user_id=user_id,
        type=type_,
        title=title[:160],
        body=(body or "")[:2000] or None,
        link=link,
    )
    db.add(note)
    return note


def log_activity(
    db: Session,
    action: ActivityAction,
    description: str,
    actor_user_id: Optional[int] = None,
    entity_type: Optional[str] = None,
    entity_id: Optional[int] = None,
) -> ActivityLog:
    entry = ActivityLog(
        actor_user_id=actor_user_id,
        action=action,
        description=description[:400],
        entity_type=entity_type,
        entity_id=entity_id,
    )
    db.add(entry)
    return entry


# --------------------------------------------------------------------------- #
# Ratings (always computed from the reviews table)
# --------------------------------------------------------------------------- #
def rating_aggregate(db: Session, tutor_profile_id: int) -> Dict[str, Any]:
    row = db.execute(
        select(
            func.coalesce(func.avg(Review.rating), 0.0),
            func.count(Review.id),
        ).where(
            Review.tutor_profile_id == tutor_profile_id,
            Review.is_deleted.is_(False),
        )
    ).one()
    return {"rating": round(float(row[0]), 2), "review_count": int(row[1])}


def rating_breakdown(db: Session, tutor_profile_id: int) -> List[Dict[str, Any]]:
    rows = db.execute(
        select(Review.rating, func.count(Review.id))
        .where(
            Review.tutor_profile_id == tutor_profile_id,
            Review.is_deleted.is_(False),
        )
        .group_by(Review.rating)
    ).all()
    counts = {int(star): int(count) for star, count in rows}
    total = sum(counts.values())
    return [
        {
            "star": star,
            "count": counts.get(star, 0),
            "percentage": round((counts.get(star, 0) / total) * 100, 1) if total else 0.0,
        }
        for star in (5, 4, 3, 2, 1)
    ]


# --------------------------------------------------------------------------- #
# Profile completion
# --------------------------------------------------------------------------- #
def profile_completion(profile: TutorProfile, user: User) -> int:
    checks = [
        bool(user.avatar_url),
        bool(profile.headline),
        len(profile.bio.strip()) >= 120,
        bool(profile.qualifications and profile.qualifications.strip()),
        profile.years_experience > 0,
        float(profile.hourly_rate) > 0,
        bool(profile.city and profile.state),
        bool(profile.languages),
        len(profile.tutor_subjects) > 0,
        len(profile.availability) > 0,
        bool(profile.cover_image_url),
    ]
    return int(round(sum(1 for ok in checks if ok) / len(checks) * 100))


# --------------------------------------------------------------------------- #
# Serialisers
# --------------------------------------------------------------------------- #
def short_bio(bio: str, limit: int = 170) -> str:
    text = " ".join((bio or "").split())
    return text if len(text) <= limit else text[: limit - 1].rsplit(" ", 1)[0] + "\u2026"


def availability_out(slot: Availability) -> Dict[str, Any]:
    return {
        "id": slot.id,
        "tutor_profile_id": slot.tutor_profile_id,
        "day_of_week": slot.day_of_week,
        "day_index": slot.day_index,
        "start_time": slot.start_time.strftime("%H:%M"),
        "end_time": slot.end_time.strftime("%H:%M"),
        "mode": slot.mode.value,
        "is_active": slot.is_active,
        "label": f"{slot.day_of_week} {fmt_time(slot.start_time)} \u2013 {fmt_time(slot.end_time)}",
        "created_at": slot.created_at.isoformat() if slot.created_at else None,
    }


def subject_out(row) -> Dict[str, Any]:
    subject: Subject = row.subject
    return {
        "id": subject.id,
        "name": subject.name,
        "category": subject.category,
        "icon": subject.icon,
        "proficiency": row.proficiency,
        "levels": row.levels,
    }


def party(profile: TutorProfile | StudentProfile) -> Dict[str, Any]:
    user: User = profile.user
    return {
        "id": profile.id,
        "name": user.full_name,
        "email": None,
        "avatar_url": user.avatar_url,
    }

def review_out(review: Review) -> Dict[str, Any]:
    student = review.student_profile
    user = student.user if student else None
    subject_name = None
    if review.booking_request and review.booking_request.subject:
        subject_name = review.booking_request.subject.name
    return {
        "id": review.id,
        "rating": review.rating,
        "title": review.title,
        "comment": review.comment,
        "created_at": review.created_at.isoformat() if review.created_at else None,
        "booking_request_id": review.booking_request_id,
        "is_deleted": review.is_deleted,
        "student_name": user.full_name if user else "Student",
        "student_avatar_url": user.avatar_url if user else None,
        "subject_name": subject_name,
    }


def tutor_summary(
    db: Session,
    profile: TutorProfile,
    *,
    rating: Optional[float] = None,
    review_count: Optional[int] = None,
    availability: Optional[Sequence[Availability]] = None,
    completed_sessions: Optional[int] = None,
    match_score: Optional[int] = None,
    is_favorite: bool = False,
) -> Dict[str, Any]:
    """Serialise a tutor profile into the card payload used across the app."""
    user = profile.user
    if rating is None or review_count is None:
        agg = rating_aggregate(db, profile.id)
        rating = agg["rating"] if rating is None else rating
        review_count = agg["review_count"] if review_count is None else review_count

    slots = availability if availability is not None else profile.availability
    if completed_sessions is None:
        completed_sessions = int(
            db.scalar(
                select(func.count(BookingRequest.id)).where(
                    BookingRequest.tutor_profile_id == profile.id,
                    BookingRequest.status == RequestStatus.COMPLETED,
                )
            )
            or 0
        )

    return {
        "id": profile.id,
        "user_id": user.id,
        "full_name": user.full_name,
        "avatar_url": user.avatar_url,
        "headline": profile.headline,
        "bio": profile.bio,
        "short_bio": short_bio(profile.bio),
        "years_experience": profile.years_experience,
        "hourly_rate": float(profile.hourly_rate),
        "session_duration_minutes": profile.session_duration_minutes,
        "city": profile.city,
        "state": profile.state,
        "country": profile.country,
        "teaching_mode": profile.teaching_mode.value,
        "qualifications": profile.qualifications,
        "languages": profile.languages,
        "cover_image_url": profile.cover_image_url,
        "accepts_online": profile.accepts_online,
        "accepts_in_person": profile.accepts_in_person,
        "verified": profile.verified,
        "approval_status": profile.approval_status.value,
        "rating": round(float(rating), 2),
        "review_count": int(review_count),
        "subjects": [subject_out(ts) for ts in profile.tutor_subjects],
        "availability": [availability_out(slot) for slot in slots],
        "completed_sessions": completed_sessions,
        "response_time_hours": None,
        "match_score": match_score,
        "is_favorite": is_favorite,
    }


def request_out(db: Session, request: BookingRequest, *, viewer: Optional[User] = None) -> Dict[str, Any]:
    tutor_profile = request.tutor_profile
    student_profile = request.student_profile
    subject_name = request.subject.name if request.subject else ""
    review = request.review

    session_dt = datetime.combine(request.preferred_date, request.preferred_time)
    can_review = (
        request.status == RequestStatus.COMPLETED
        and review is None
        and viewer is not None
        and viewer.role == UserRole.STUDENT
        and student_profile is not None
        and viewer.id == student_profile.user_id
    )

    return {
        "id": request.id,
        "status": request.status.value,
        "subject_id": request.subject_id,
        "subject_name": subject_name,
        "preferred_date": request.preferred_date.isoformat(),
        "preferred_time": request.preferred_time.strftime("%H:%M"),
        "duration_minutes": request.duration_minutes,
        "mode": request.mode.value,
        "budget": float(request.budget),
        "message": request.message,
        "location_note": request.location_note,
        "tutor_response_note": request.tutor_response_note,
        "cancel_reason": request.cancel_reason,
        "responded_at": request.responded_at.isoformat() if request.responded_at else None,
        "completed_at": request.completed_at.isoformat() if request.completed_at else None,
        "cancelled_at": request.cancelled_at.isoformat() if request.cancelled_at else None,
        "created_at": request.created_at.isoformat() if request.created_at else None,
        "tutor": party(tutor_profile),
        "student": party(student_profile),
        "tutor_city": tutor_profile.city,
        "tutor_state": tutor_profile.state,
        "tutor_hourly_rate": float(tutor_profile.hourly_rate),
        "review_id": review.id if review else None,
        "has_review": review is not None,
        "can_review": can_review,
        "session_label": (
            f"{session_dt.strftime('%a, %d %b %Y')} at "
            f"{fmt_time(request.preferred_time)} ({request.duration_minutes} min)"
        ),
    }


# --------------------------------------------------------------------------- #
# Availability helpers
# --------------------------------------------------------------------------- #
def slots_overlap(a_start: time, a_end: time, b_start: time, b_end: time) -> bool:
    return a_start < b_end and b_start < a_end


def find_overlapping_slot(
    db: Session,
    tutor_profile_id: int,
    day_of_week: str,
    start_time: time,
    end_time: time,
    exclude_id: Optional[int] = None,
) -> Optional[Availability]:
    query = select(Availability).where(
        Availability.tutor_profile_id == tutor_profile_id,
        Availability.day_of_week == day_of_week,
    )
    if exclude_id:
        query = query.where(Availability.id != exclude_id)
    for slot in db.scalars(query).all():
        if slots_overlap(start_time, end_time, slot.start_time, slot.end_time):
            return slot
    return None


def matching_availability(
    slots: Sequence[Availability],
    when_date: date,
    when_time: time,
    duration_minutes: int,
    mode: Optional[TeachingMode] = None,
) -> Optional[Availability]:
    """Return the weekly slot that covers the requested session, if any."""
    day_name = DAYS_OF_WEEK[when_date.weekday()]
    start_minutes = when_time.hour * 60 + when_time.minute
    end_minutes = start_minutes + duration_minutes

    for slot in slots:
        if not slot.is_active or slot.day_of_week != day_name:
            continue
        slot_start = slot.start_time.hour * 60 + slot.start_time.minute
        slot_end = slot.end_time.hour * 60 + slot.end_time.minute
        if slot_start <= start_minutes and end_minutes <= slot_end:
            if mode is None or slot.mode in (mode, TeachingMode.HYBRID):
                return slot
    return None


def upcoming_sessions(db: Session, profile_id: int, is_tutor: bool) -> int:
    now = datetime.now(timezone.utc).date()
    column = (
        BookingRequest.tutor_profile_id if is_tutor else BookingRequest.student_id
    )
    return int(
        db.scalar(
            select(func.count(BookingRequest.id)).where(
                column == profile_id,
                BookingRequest.status == RequestStatus.ACCEPTED,
                BookingRequest.preferred_date >= now,
            )
        )
        or 0
    )


# --------------------------------------------------------------------------- #
# Misc formatting
# --------------------------------------------------------------------------- #
def mode_label(mode: str | TeachingMode) -> str:
    value = mode.value if isinstance(mode, TeachingMode) else mode
    return {
        "in_person": "In person",
        "online": "Online",
        "hybrid": "Online & in person",
    }.get(value, value.replace("_", " ").title())


def status_label(status_value: str | RequestStatus) -> str:
    value = status_value.value if isinstance(status_value, RequestStatus) else status_value
    return value.replace("_", " ").title()


def days_until(target: date) -> int:
    return (target - date.today()).days
