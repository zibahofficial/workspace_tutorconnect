"""Tutor profile endpoints: discovery, profile CRUD, subjects, dashboard stats."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import Select, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from auth import get_current_user, get_optional_user, require_roles
from config import settings
from database import get_db
from helpers import (
    availability_out,
    log_activity,
    notify,
    profile_completion,
    rating_aggregate,
    rating_breakdown,
    review_out,
    short_bio,
    subject_out,
    tutor_summary,
    upcoming_sessions,
)
from models import (
    ActivityAction,
    BookingRequest,
    Favorite,
    NotificationType,
    RequestStatus,
    Review,
    StudentProfile,
    Subject,
    TutorProfile,
    TutorStatus,
    TutorSubject,
    User,
    UserRole,
)
from schemas import (
    Message,
    TutorApprovalUpdate,
    TutorDashboardStats,
    TutorDetail,
    TutorProfileCreate,
    TutorProfileUpdate,
    TutorSummary,
)
from services import search_facets, search_tutors

router = APIRouter(prefix="/tutors", tags=["Tutors"])


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _get_profile_or_404(db: Session, tutor_id: int) -> TutorProfile:
    profile = db.get(TutorProfile, tutor_id)
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tutor profile #{tutor_id} does not exist.",
        )
    return profile


def _validate_subject_ids(db: Session, subject_ids: List[int]) -> List[Subject]:
    unique_ids = sorted({int(sid) for sid in subject_ids})
    subjects = db.scalars(
        select(Subject).where(Subject.id.in_(unique_ids), Subject.is_active.is_(True))
    ).all()
    found = {s.id for s in subjects}
    missing = [sid for sid in unique_ids if sid not in found]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown subject id(s): {', '.join(map(str, missing))}.",
        )
    if not subjects:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Please select at least one subject.",
        )
    return subjects


def _can_view(profile: TutorProfile, user: Optional[User]) -> bool:
    if user is not None and user.role == UserRole.ADMIN:
        return True
    if user is not None and user.id == profile.user_id:
        return True
    return profile.is_visible and profile.approval_status == TutorStatus.APPROVED


def _detail_payload(db: Session, profile: TutorProfile, user: Optional[User]) -> Dict[str, Any]:
    agg = rating_aggregate(db, profile.id)
    reviews = db.scalars(
        select(Review)
        .where(Review.tutor_profile_id == profile.id, Review.is_deleted.is_(False))
        .order_by(Review.created_at.desc())
        .limit(50)
    ).all()

    total_students = int(
        db.scalar(
            select(func.count(func.distinct(BookingRequest.student_id))).where(
                BookingRequest.tutor_profile_id == profile.id
            )
        )
        or 0
    )
    payload = tutor_summary(
        db,
        profile,
        rating=agg["rating"],
        review_count=agg["review_count"],
        availability=[s for s in profile.availability],
    )
    payload.update(
        {
                        "email": profile.user.email if user is not None and (
                user.role == UserRole.ADMIN or user.id == profile.user_id
            ) else None,
            "phone": profile.user.phone
            if user is not None and user.role == UserRole.ADMIN
            else None,
            "reviews": [review_out(r) for r in reviews],
            "rating_breakdown": rating_breakdown(db, profile.id),
            "exceptions": [
                {
                    "id": exc.id,
                    "date": exc.date.isoformat(),
                    "is_blocked": exc.is_blocked,
                    "reason": exc.reason,
                }
                for exc in profile.exceptions
            ],
            "total_students": total_students,
            "created_at": profile.created_at.isoformat() if profile.created_at else None,
            "profile_completion": profile_completion(profile, profile.user),
        }
    )
    return payload


# --------------------------------------------------------------------------- #
# READ - discovery
# --------------------------------------------------------------------------- #
@router.get("", summary="Search & filter tutors (paginated)")
def list_tutors(
    q: Optional[str] = Query(None, max_length=120, description="Free-text search"),
    subject: Optional[str] = Query(None, max_length=120),
    subject_id: Optional[int] = Query(None, ge=1),
    city: Optional[str] = Query(None, max_length=120),
    state: Optional[str] = Query(None, max_length=120),
    location: Optional[str] = Query(None, max_length=120),
    mode: Optional[str] = Query(None, pattern="^(in_person|online|hybrid|any)$"),
    min_experience: Optional[int] = Query(None, ge=0, le=70),
    max_experience: Optional[int] = Query(None, ge=0, le=70),
    min_price: Optional[float] = Query(None, ge=0),
    max_price: Optional[float] = Query(None, ge=0),
    day: Optional[str] = Query(None, max_length=10),
    start_after: Optional[str] = Query(None, pattern=r"^\d{1,2}:\d{2}$"),
    end_before: Optional[str] = Query(None, pattern=r"^\d{1,2}:\d{2}$"),
    available_today: bool = Query(False),
    min_rating: Optional[float] = Query(None, ge=0, le=5),
    min_reviews: Optional[int] = Query(None, ge=0),
    verified_only: bool = Query(False),
    language: Optional[str] = Query(None, max_length=60),
    sort: str = Query("relevance", pattern="^(relevance|rating|price_asc|price_desc|experience|newest|popular)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(settings.default_page_size, ge=1, le=settings.max_page_size),
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_user),
):
    if min_experience is not None and max_experience is not None and min_experience > max_experience:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Minimum experience cannot be greater than maximum experience.",
        )
    if min_price is not None and max_price is not None and min_price > max_price:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Minimum budget cannot be greater than maximum budget.",
        )

    return search_tutors(
        db,
        q=q, subject=subject, subject_id=subject_id, city=city, state=state,
        location=location, mode=mode, min_experience=min_experience,
        max_experience=max_experience, min_price=min_price, max_price=max_price,
        day=day, start_after=start_after, end_before=end_before,
        available_today=available_today, min_rating=min_rating,
        min_reviews=min_reviews, verified_only=verified_only, language=language,
        sort=sort, page=page, page_size=page_size, current_user=current_user,
    )


@router.get("/facets", summary="Filter options derived from live data")
def get_facets(db: Session = Depends(get_db)):
    return search_facets(db)


@router.get("/me", response_model=TutorDetail, summary="My own tutor profile")
def my_profile(
    current_user: User = Depends(require_roles(UserRole.TUTOR)),
    db: Session = Depends(get_db),
):
    profile = db.scalar(select(TutorProfile).where(TutorProfile.user_id == current_user.id))
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="You have not created your tutor profile yet. Submit one to get discovered.",
        )
    return _detail_payload(db, profile, current_user)


@router.get("/me/stats", response_model=TutorDashboardStats, summary="Tutor dashboard stats")
def my_stats(
    current_user: User = Depends(require_roles(UserRole.TUTOR)),
    db: Session = Depends(get_db),
):
    profile = db.scalar(select(TutorProfile).where(TutorProfile.user_id == current_user.id))
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tutor profile not found. Create it first.",
        )

    counts: Dict[str, int] = {}
    rows = db.execute(
        select(BookingRequest.status, func.count(BookingRequest.id)).where(
            BookingRequest.tutor_profile_id == profile.id
        ).group_by(BookingRequest.status)
    ).all()
    for row in rows:
        counts[row[0].value if hasattr(row[0], "value") else str(row[0])] = int(row[1])

    earnings = float(
        db.scalar(
            select(func.coalesce(func.sum(BookingRequest.budget), 0)).where(
                BookingRequest.tutor_profile_id == profile.id,
                BookingRequest.status.in_([RequestStatus.ACCEPTED, RequestStatus.COMPLETED]),
            )
        )
        or 0
    )
    agg = rating_aggregate(db, profile.id)
    favorites = int(
        db.scalar(
            select(func.count(Favorite.id)).where(Favorite.tutor_profile_id == profile.id)
        )
        or 0
    )

    return {
        "profile_completion": profile_completion(profile, current_user),
        "total_requests": sum(counts.values()),
        "pending_requests": counts.get("pending", 0),
        "accepted_requests": counts.get("accepted", 0),
        "rejected_requests": counts.get("rejected", 0),
        "cancelled_requests": counts.get("cancelled", 0),
        "completed_sessions": counts.get("completed", 0),
        "upcoming_sessions": upcoming_sessions(db, profile.id, is_tutor=True),
        "rating": agg["rating"],
        "review_count": agg["review_count"],
        "weekly_slots": len([s for s in profile.availability if s.is_active]),
        "total_earnings": round(earnings, 2),
        "favorites": favorites,
    }


@router.get("/{tutor_id}", response_model=TutorDetail, summary="Full tutor profile")
def get_tutor(
    tutor_id: int,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_user),
):
    profile = _get_profile_or_404(db, tutor_id)
    if not _can_view(profile, current_user):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="This tutor profile is not available.",
        )

    payload = _detail_payload(db, profile, current_user)

    if current_user is not None and current_user.role == UserRole.STUDENT:
        student_profile = db.scalar(
            select(StudentProfile).where(StudentProfile.user_id == current_user.id)
        )
        if student_profile:
            payload["is_favorite"] = (
                db.scalar(
                    select(Favorite.id).where(
                        Favorite.student_id == student_profile.id,
                        Favorite.tutor_profile_id == profile.id,
                    )
                )
                is not None
            )
    return payload


# --------------------------------------------------------------------------- #
# CREATE
# --------------------------------------------------------------------------- #
@router.post(
    "",
    response_model=TutorDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Create your tutor profile",
)
def create_profile(
    payload: TutorProfileCreate,
    current_user: User = Depends(require_roles(UserRole.TUTOR)),
    db: Session = Depends(get_db),
):
    existing = db.scalar(select(TutorProfile).where(TutorProfile.user_id == current_user.id))
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You already have a tutor profile. Use PUT /tutors/me to update it.",
        )
    if not payload.accepts_online and not payload.accepts_in_person:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You must accept online or in-person sessions.",
        )

    subjects = _validate_subject_ids(db, payload.subject_ids)

    data = payload.model_dump(exclude={"subject_ids"})
    profile = TutorProfile(user_id=current_user.id, **data)
    db.add(profile)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A tutor profile already exists for this account.",
        ) from exc

    for subject in subjects:
        db.add(TutorSubject(tutor_profile_id=profile.id, subject_id=subject.id))

    log_activity(
        db,
        ActivityAction.TUTOR_PROFILE_CREATED,
        f"{current_user.full_name} created a tutor profile ({profile.city}, {profile.state})",
        actor_user_id=current_user.id,
        entity_type="tutor_profile",
        entity_id=profile.id,
    )
    notify(
        db,
        current_user.id,
        NotificationType.ACCOUNT,
        "Tutor profile created",
        "Add your weekly availability so students can request sessions with you.",
        link="dashboard.html?view=availability",
    )
    db.commit()
    db.refresh(profile)
    return _detail_payload(db, profile, current_user)


# --------------------------------------------------------------------------- #
# UPDATE
# --------------------------------------------------------------------------- #
def _resolve_profile_for_write(db: Session, user: User, tutor_id: Optional[int]) -> TutorProfile:
    """Tutors act on their own profile; admins may target any profile by id."""
    if user.role == UserRole.TUTOR:
        profile = db.scalar(select(TutorProfile).where(TutorProfile.user_id == user.id))
        if profile is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="You have not created a tutor profile yet.",
            )
        return profile
    if user.role == UserRole.ADMIN:
        if tutor_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="tutor_id is required when an admin edits a profile.",
            )
        return _get_profile_or_404(db, tutor_id)
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed.")


def _apply_profile_update(
    db: Session, profile: TutorProfile, payload: TutorProfileUpdate, actor: User
) -> TutorProfile:
    data = payload.model_dump(exclude_unset=True)
    avatar_url = data.pop("avatar_url", None)
    subject_ids = data.pop("subject_ids", None)

    if "accepts_online" in data or "accepts_in_person" in data:
        online = data.get("accepts_online", profile.accepts_online)
        in_person = data.get("accepts_in_person", profile.accepts_in_person)
        if not online and not in_person:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="You must accept online or in-person sessions.",
            )

    for field, value in data.items():
        setattr(profile, field, value)

    if avatar_url is not None:
        profile.user.avatar_url = avatar_url

    if subject_ids is not None:
        subjects = _validate_subject_ids(db, subject_ids)
        existing = {ts.subject_id: ts for ts in profile.tutor_subjects}
        for subject in subjects:
            if subject.id not in existing:
                db.add(TutorSubject(tutor_profile_id=profile.id, subject_id=subject.id))
        keep = {s.id for s in subjects}
        for subject_id_value, link in list(existing.items()):
            if subject_id_value not in keep:
                db.delete(link)

    log_activity(
        db,
        ActivityAction.TUTOR_PROFILE_UPDATED,
        f"{profile.user.full_name} updated their tutor profile",
        actor_user_id=actor.id,
        entity_type="tutor_profile",
        entity_id=profile.id,
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Those changes conflict with existing data. Please review and retry.",
        ) from exc
    db.refresh(profile)
    return profile


@router.put("/me", response_model=TutorDetail, summary="Update your own tutor profile")
def update_my_profile(
    payload: TutorProfileUpdate,
    current_user: User = Depends(require_roles(UserRole.TUTOR)),
    db: Session = Depends(get_db),
):
    profile = _resolve_profile_for_write(db, current_user, None)
    profile = _apply_profile_update(db, profile, payload, current_user)
    return _detail_payload(db, profile, current_user)


@router.put("/{tutor_id}", response_model=TutorDetail, summary="Admin: update any tutor profile")
def update_profile(
    tutor_id: int,
    payload: TutorProfileUpdate,
    current_user: User = Depends(require_roles(UserRole.ADMIN)),
    db: Session = Depends(get_db),
):
    profile = _get_profile_or_404(db, tutor_id)
    profile = _apply_profile_update(db, profile, payload, current_user)
    return _detail_payload(db, profile, current_user)


@router.put("/{tutor_id}/status", response_model=TutorDetail, summary="Admin: approve/suspend a tutor")
def update_approval(
    tutor_id: int,
    payload: TutorApprovalUpdate,
    current_user: User = Depends(require_roles(UserRole.ADMIN)),
    db: Session = Depends(get_db),
):
    profile = _get_profile_or_404(db, tutor_id)
    profile.approval_status = payload.approval_status
    if payload.verified is not None:
        profile.verified = payload.verified
    profile.is_visible = payload.approval_status == TutorStatus.APPROVED

    action = (
        ActivityAction.TUTOR_APPROVED
        if payload.approval_status == TutorStatus.APPROVED
        else ActivityAction.TUTOR_SUSPENDED
    )
    log_activity(
        db,
        action,
        f"{current_user.full_name} set {profile.user.full_name}'s profile to "
        f"{payload.approval_status.value}"
        + (f" ({payload.reason})" if payload.reason else ""),
        actor_user_id=current_user.id,
        entity_type="tutor_profile",
        entity_id=profile.id,
    )
    notify(
        db,
        profile.user_id,
        NotificationType.PROFILE_APPROVED
        if payload.approval_status == TutorStatus.APPROVED
        else NotificationType.PROFILE_SUSPENDED,
        (
            "Your tutor profile is live"
            if payload.approval_status == TutorStatus.APPROVED
            else "Your tutor profile was suspended"
        ),
        payload.reason
        or (
            "Students can now find you in search results."
            if payload.approval_status == TutorStatus.APPROVED
            else "Your profile is hidden from search. Contact support for details."
        ),
        link="dashboard.html",
    )
    db.commit()
    db.refresh(profile)
    return _detail_payload(db, profile, current_user)


# --------------------------------------------------------------------------- #
# DELETE
# --------------------------------------------------------------------------- #
def _delete_profile(db: Session, profile: TutorProfile, actor: User) -> str:
    active = int(
        db.scalar(
            select(func.count(BookingRequest.id)).where(
                BookingRequest.tutor_profile_id == profile.id,
                BookingRequest.status.in_([RequestStatus.PENDING, RequestStatus.ACCEPTED]),
            )
        )
        or 0
    )
    if active and actor.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"You have {active} active request(s). Resolve or cancel them before "
                "deleting your profile."
            ),
        )

    name = profile.user.full_name
    profile_id = profile.id
    db.delete(profile)
    log_activity(
        db,
        ActivityAction.TUTOR_SUSPENDED,
        f"Tutor profile for {name} was deleted by {actor.full_name}",
        actor_user_id=actor.id,
        entity_type="tutor_profile",
        entity_id=profile_id,
    )
    db.commit()
    return name


@router.delete("/me", response_model=Message, summary="Delete your own tutor profile")
def delete_my_profile(
    current_user: User = Depends(require_roles(UserRole.TUTOR)),
    db: Session = Depends(get_db),
):
    profile = db.scalar(select(TutorProfile).where(TutorProfile.user_id == current_user.id))
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Tutor profile not found."
        )
    name = _delete_profile(db, profile, current_user)
    return {"detail": f"Your tutor profile ({name}) has been deleted."}


@router.delete("/{tutor_id}", response_model=Message, summary="Admin: remove a tutor profile")
def delete_profile(
    tutor_id: int,
    current_user: User = Depends(require_roles(UserRole.ADMIN)),
    db: Session = Depends(get_db),
):
    profile = _get_profile_or_404(db, tutor_id)
    name = _delete_profile(db, profile, current_user)
    return {"detail": f"Tutor profile for {name} has been deleted."}


# --------------------------------------------------------------------------- #
# Subjects taught (nested CRUD)
# --------------------------------------------------------------------------- #
@router.get("/{tutor_id}/subjects", summary="Subjects taught by a tutor")
def tutor_subjects(tutor_id: int, db: Session = Depends(get_db)):
    profile = _get_profile_or_404(db, tutor_id)
    return [subject_out(ts) for ts in profile.tutor_subjects]


@router.post(
    "/me/subjects",
    status_code=status.HTTP_201_CREATED,
    summary="Add a subject you teach",
)
def add_subject(
    subject_id: int = Query(..., ge=1),
    proficiency: str = Query("Advanced", max_length=40),
    levels: Optional[str] = Query(None, max_length=255),
    current_user: User = Depends(require_roles(UserRole.TUTOR)),
    db: Session = Depends(get_db),
):
    profile = db.scalar(select(TutorProfile).where(TutorProfile.user_id == current_user.id))
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tutor profile not found.")

    subject = db.get(Subject, subject_id)
    if subject is None or not subject.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subject not found.")

    exists = db.scalar(
        select(TutorSubject).where(
            TutorSubject.tutor_profile_id == profile.id, TutorSubject.subject_id == subject_id
        )
    )
    if exists is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"You already list {subject.name}.",
        )

    link = TutorSubject(
        tutor_profile_id=profile.id,
        subject_id=subject.id,
        proficiency=proficiency.strip() or "Advanced",
        levels=levels,
    )
    db.add(link)
    db.commit()
    db.refresh(link)
    return {"detail": f"{subject.name} added to your profile.", "data": subject_out(link)}


@router.delete("/me/subjects/{subject_id}", response_model=Message, summary="Remove a subject")
def remove_subject(
    subject_id: int,
    current_user: User = Depends(require_roles(UserRole.TUTOR)),
    db: Session = Depends(get_db),
):
    profile = db.scalar(select(TutorProfile).where(TutorProfile.user_id == current_user.id))
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tutor profile not found.")

    link = db.scalar(
        select(TutorSubject).where(
            TutorSubject.tutor_profile_id == profile.id, TutorSubject.subject_id == subject_id
        )
    )
    if link is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="That subject is not on your profile."
        )
    name = link.subject.name
    db.delete(link)
    db.commit()
    return {"detail": f"{name} removed from your subjects."}


# --------------------------------------------------------------------------- #
# Rating summary
# --------------------------------------------------------------------------- #
@router.get("/{tutor_id}/rating", summary="Rating summary for a tutor")
def tutor_rating_summary(tutor_id: int, db: Session = Depends(get_db)):
    """Average rating, review count and the 5->1 star breakdown.

    Always derived from real ``Review`` rows - nothing is stored redundantly, so
    editing or hiding a review immediately changes these numbers.
    """
    profile = _get_profile_or_404(db, tutor_id)
    agg = rating_aggregate(db, profile.id)
    count = agg["review_count"]
    average = agg["rating"] if count else None
    breakdown = rating_breakdown(db, profile.id)
    return {
        "tutor_id": profile.id,
        "tutor_name": profile.user.full_name,
        "average_rating": average,
        "rating": average if average is not None else 0.0,
        "review_count": count,
        "stars": int(round(average)) if count else 0,
        "has_reviews": bool(count),
        "breakdown": breakdown,
    }


# --------------------------------------------------------------------------- #
# Reviews (read-only here; writing lives in routers/reviews.py)
# --------------------------------------------------------------------------- #
@router.get("/{tutor_id}/reviews", summary="Reviews for a tutor")
def tutor_reviews(
    tutor_id: int,
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    profile = _get_profile_or_404(db, tutor_id)
    reviews = db.scalars(
        select(Review)
        .where(Review.tutor_profile_id == profile.id, Review.is_deleted.is_(False))
        .order_by(Review.created_at.desc())
        .limit(limit)
    ).all()
    agg = rating_aggregate(db, profile.id)
    return {
        "tutor_id": profile.id,
        "rating": agg["rating"],
        "review_count": agg["review_count"],
        "breakdown": rating_breakdown(db, profile.id),
        "items": [review_out(r) for r in reviews],
    }
