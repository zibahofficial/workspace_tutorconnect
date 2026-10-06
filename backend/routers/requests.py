"""
Booking / request endpoints — the full lifecycle.

    student creates request -> pending
    tutor accepts           -> accepted   (student notified)
    tutor rejects           -> rejected   (student notified)
    either party cancels    -> cancelled
    tutor marks done        -> completed  (unlocks the student's review)

Every transition writes to the database, creates a notification for the other
party and records an entry in the admin activity log.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from auth import get_current_user, require_roles
from config import settings
from database import get_db
from helpers import (
    fmt_time,
    log_activity,
    matching_availability,
    notify,
    request_out,
)
from models import (
    ActivityAction,
    BookingRequest,
    NotificationType,
    RequestStatus,
    Review,
    StudentProfile,
    Subject,
    TeachingMode,
    TutorProfile,
    TutorStatus,
    TutorSubject,
    User,
    UserRole,
)
from routers.availability import open_slots_for_date
from schemas import (
    BookingRequestCancel,
    BookingRequestCreate,
    BookingRequestDecision,
    BookingRequestUpdate,
    Message,
    StudentDashboardStats,
)

router = APIRouter(tags=["Booking requests"])

ACTIVE_STATUSES = [RequestStatus.PENDING, RequestStatus.ACCEPTED]


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _student_profile(db: Session, user: User) -> StudentProfile:
    profile = db.scalar(select(StudentProfile).where(StudentProfile.user_id == user.id))
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Student profile not found for this account.",
        )
    return profile


def _get_request(db: Session, request_id: int) -> BookingRequest:
    request = db.get(BookingRequest, request_id)
    if request is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Booking request #{request_id} does not exist.",
        )
    return request


def _is_student_party(user: User, request: BookingRequest) -> bool:
    return (
        user.role == UserRole.STUDENT
        and request.student_profile is not None
        and request.student_profile.user_id == user.id
    )


def _is_tutor_party(user: User, request: BookingRequest) -> bool:
    return (
        user.role == UserRole.TUTOR
        and request.tutor_profile is not None
        and request.tutor_profile.user_id == user.id
    )


def _lead_time_ok(target_date: date, target_time: time) -> bool:
    start = datetime.combine(target_date, target_time)
    return start >= datetime.now() + timedelta(hours=settings.min_booking_lead_hours)


def _conflicting_booking(
    db: Session, tutor_profile_id: int, target_date: date, target_time: time,
    duration: int, exclude_id: Optional[int] = None,
) -> Optional[BookingRequest]:
    rows = db.scalars(
        select(BookingRequest).where(
            BookingRequest.tutor_profile_id == tutor_profile_id,
            BookingRequest.preferred_date == target_date,
            BookingRequest.status.in_(ACTIVE_STATUSES),
        )
    ).all()
    start = target_time.hour * 60 + target_time.minute
    end = start + duration
    for row in rows:
        if exclude_id and row.id == exclude_id:
            continue
        other_start = row.preferred_time.hour * 60 + row.preferred_time.minute
        other_end = other_start + row.duration_minutes
        if start < other_end and other_start < end:
            return row
    return None


# --------------------------------------------------------------------------- #
# CREATE
# --------------------------------------------------------------------------- #
@router.post(
    "/requests",
    status_code=status.HTTP_201_CREATED,
    summary="Submit a tutor / booking request",
)
def create_request(
    payload: BookingRequestCreate,
    current_user: User = Depends(require_roles(UserRole.STUDENT)),
    db: Session = Depends(get_db),
):
    student = _student_profile(db, current_user)

    tutor_profile = db.get(TutorProfile, payload.tutor_id)
    if tutor_profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tutor #{payload.tutor_id} does not exist.",
        )
    if tutor_profile.user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot send a booking request to yourself.",
        )
    if not tutor_profile.is_visible or tutor_profile.approval_status != TutorStatus.APPROVED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This tutor is not accepting requests right now.",
        )

    subject = db.get(Subject, payload.subject_id)
    if subject is None or not subject.is_active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="That subject does not exist."
        )
    teaches = db.scalar(
        select(TutorSubject).where(
            TutorSubject.tutor_profile_id == tutor_profile.id,
            TutorSubject.subject_id == subject.id,
        )
    )
    if teaches is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{tutor_profile.user.full_name} does not teach {subject.name}.",
        )

    mode_value = payload.mode
    if mode_value == TeachingMode.ONLINE and not tutor_profile.accepts_online:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="This tutor does not teach online."
        )
    if mode_value == TeachingMode.IN_PERSON and not tutor_profile.accepts_in_person:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This tutor does not offer in-person sessions.",
        )

    if not _lead_time_ok(payload.preferred_date, payload.preferred_time):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "That time is too soon. Please pick a slot at least "
                f"{settings.min_booking_lead_hours} hour(s) from now."
            ),
        )

    duration = payload.duration_minutes or tutor_profile.session_duration_minutes
    slot = matching_availability(
        tutor_profile.availability, payload.preferred_date, payload.preferred_time, duration, mode_value
    )
    if slot is None and not payload.ignore_availability:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"{tutor_profile.user.full_name} is not available on "
                f"{payload.preferred_date.strftime('%A')} at "
                f"{fmt_time(payload.preferred_time)}. Choose one of their listed slots "
                "or tick 'request outside availability'."
            ),
        )

    duplicate = _conflicting_booking(
        db, tutor_profile.id, payload.preferred_date, payload.preferred_time, duration
    )
    if duplicate is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "That tutor already has a pending or accepted session at this time. "
                "Please choose a different slot."
            ),
        )

    already = db.scalar(
        select(BookingRequest).where(
            BookingRequest.tutor_profile_id == tutor_profile.id,
            BookingRequest.student_id == student.id,
            BookingRequest.subject_id == subject.id,
            BookingRequest.preferred_date == payload.preferred_date,
            BookingRequest.preferred_time == payload.preferred_time,
            BookingRequest.status == RequestStatus.PENDING,
        )
    )
    if already is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "You already have a pending request with this tutor for the same subject, "
                "date and time."
            ),
        )

    open_requests = int(
        db.scalar(
            select(func.count(BookingRequest.id)).where(
                BookingRequest.student_id == student.id,
                BookingRequest.status == RequestStatus.PENDING,
            )
        )
        or 0
    )
    if open_requests >= 15:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="You have too many pending requests. Wait for responses before sending more.",
        )

    request = BookingRequest(
        tutor_profile_id=tutor_profile.id,
        student_id=student.id,
        subject_id=subject.id,
        status=RequestStatus.PENDING,
        preferred_date=payload.preferred_date,
        preferred_time=payload.preferred_time,
        duration_minutes=duration,
        mode=mode_value,
        budget=payload.budget,
        message=(payload.message or "").strip() or None,
        location_note=payload.location_note,
    )
    db.add(request)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An identical request already exists.",
        ) from exc
    db.refresh(request)

    first_name = current_user.full_name.split()[0]
    notify(
        db,
        tutor_profile.user_id,
        NotificationType.REQUEST_NEW,
        f"New {subject.name} request from {first_name}",
        (
            f"{payload.preferred_date.strftime('%a, %d %b %Y')} at "
            f"{fmt_time(payload.preferred_time)} \u2022 "
            f"{settings.currency_symbol}{payload.budget:,.0f}"
        ),
        link="dashboard.html?view=requests",
    )
    notify(
        db,
        current_user.id,
        NotificationType.REQUEST_NEW,
        "Request sent",
        f"Your request to {tutor_profile.user.full_name} is pending. "
        "We'll let you know as soon as they respond.",
        link="dashboard.html?view=requests",
    )
    log_activity(
        db,
        ActivityAction.REQUEST_CREATED,
        f"{current_user.full_name} requested {tutor_profile.user.full_name} for {subject.name} "
        f"on {payload.preferred_date.isoformat()}",
        actor_user_id=current_user.id,
        entity_type="booking_request",
        entity_id=request.id,
    )
    db.commit()

    return {
        "detail": f"Request sent to {tutor_profile.user.full_name}. Status: pending.",
        "data": request_out(db, request, viewer=current_user),
    }


# --------------------------------------------------------------------------- #
# READ
# --------------------------------------------------------------------------- #
@router.get("/requests", summary="My requests (role aware)")
def list_requests(
    status_filter: Optional[str] = Query(
        None, alias="status", pattern="^(pending|accepted|rejected|cancelled|completed)$"
    ),
    subject_id: Optional[int] = Query(None, ge=1),
    tutor_id: Optional[int] = Query(None, ge=1),
    upcoming: bool = Query(False),
    q: Optional[str] = Query(None, max_length=120),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    stmt = select(BookingRequest)

    if current_user.role == UserRole.TUTOR:
        profile = db.scalar(select(TutorProfile).where(TutorProfile.user_id == current_user.id))
        if profile is None:
            return {"items": [], "total": 0, "page": page, "page_size": page_size, "pages": 1,
                    "counts": {}}
        stmt = stmt.where(BookingRequest.tutor_profile_id == profile.id)
    elif current_user.role == UserRole.STUDENT:
        student = _student_profile(db, current_user)
        stmt = stmt.where(BookingRequest.student_id == student.id)
    # admins see everything

    if status_filter:
        stmt = stmt.where(BookingRequest.status == RequestStatus(status_filter))
    if subject_id:
        stmt = stmt.where(BookingRequest.subject_id == subject_id)
    if tutor_id:
        stmt = stmt.where(BookingRequest.tutor_profile_id == tutor_id)
    if upcoming:
        stmt = stmt.where(
            BookingRequest.preferred_date >= date.today(),
            BookingRequest.status.in_(ACTIVE_STATUSES),
        )
    if q and q.strip():
        term = f"%{q.strip()}%"
        stmt = stmt.where(
            BookingRequest.message.ilike(term)
            | BookingRequest.cancel_reason.ilike(term)
            | BookingRequest.tutor_response_note.ilike(term)
        )

    total = int(db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0)
    rows = db.scalars(
        stmt.order_by(BookingRequest.preferred_date.desc(), BookingRequest.id.desc())
        .limit(page_size)
        .offset((page - 1) * page_size)
    ).all()

    counts = {s.value: 0 for s in RequestStatus}
    id_subquery = stmt.with_only_columns(BookingRequest.id).order_by(None).subquery()
    for row in db.execute(
        select(BookingRequest.status, func.count(BookingRequest.id))
        .where(BookingRequest.id.in_(select(id_subquery.c.id)))
        .group_by(BookingRequest.status)
    ).all():
        key = row[0].value if hasattr(row[0], "value") else str(row[0])
        counts[key] = int(row[1])

    return {
        "items": [request_out(db, r, viewer=current_user) for r in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": max(1, (total + page_size - 1) // page_size),
        "counts": counts,
    }


@router.get("/requests/mine/stats", summary="Student dashboard stats")
def student_stats(
    current_user: User = Depends(require_roles(UserRole.STUDENT)),
    db: Session = Depends(get_db),
):
    student = _student_profile(db, current_user)
    counts: Dict[str, int] = {s.value: 0 for s in RequestStatus}
    rows = db.execute(
        select(BookingRequest.status, func.count(BookingRequest.id))
        .where(BookingRequest.student_id == student.id)
        .group_by(BookingRequest.status)
    ).all()
    for row in rows:
        counts[row[0].value] = int(row[1])

    spent = float(
        db.scalar(
            select(func.coalesce(func.sum(BookingRequest.budget), 0)).where(
                BookingRequest.student_id == student.id,
                BookingRequest.status == RequestStatus.COMPLETED,
            )
        )
        or 0
    )
    now = date.today()
    upcoming = int(
        db.scalar(
            select(func.count(BookingRequest.id)).where(
                BookingRequest.student_id == student.id,
                BookingRequest.status == RequestStatus.ACCEPTED,
                BookingRequest.preferred_date >= now,
            )
        )
        or 0
    )
    reviews_written = int(
        db.scalar(select(func.count(Review.id)).where(Review.student_id == student.id)) or 0
    )
    from models import Favorite

    favorites = int(
        db.scalar(select(func.count(Favorite.id)).where(Favorite.student_id == student.id)) or 0
    )
    tutors_contacted = int(
        db.scalar(
            select(func.count(func.distinct(BookingRequest.tutor_profile_id))).where(
                BookingRequest.student_id == student.id
            )
        )
        or 0
    )

    return StudentDashboardStats(
        total_requests=sum(counts.values()),
        pending_requests=counts["pending"],
        accepted_requests=counts["accepted"],
        rejected_requests=counts["rejected"],
        cancelled_requests=counts["cancelled"],
        completed_sessions=counts["completed"],
        upcoming_sessions=upcoming,
        reviews_written=reviews_written,
        favorites=favorites,
        tutors_contacted=tutors_contacted,
        total_spent=round(spent, 2),
    ).model_dump()


# --------------------------------------------------------------------------- #
# Convenience: upcoming sessions for dashboards
# --------------------------------------------------------------------------- #
@router.get("/requests/upcoming/list", summary="Upcoming accepted sessions")
def upcoming_list(
    limit: int = Query(10, ge=1, le=50),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    stmt = select(BookingRequest).where(
        BookingRequest.status == RequestStatus.ACCEPTED,
        BookingRequest.preferred_date >= date.today(),
    )
    if current_user.role == UserRole.TUTOR:
        profile = db.scalar(select(TutorProfile).where(TutorProfile.user_id == current_user.id))
        if profile is None:
            return []
        stmt = stmt.where(BookingRequest.tutor_profile_id == profile.id)
    elif current_user.role == UserRole.STUDENT:
        student = _student_profile(db, current_user)
        stmt = stmt.where(BookingRequest.student_id == student.id)

    rows = db.scalars(
        stmt.order_by(BookingRequest.preferred_date, BookingRequest.preferred_time).limit(limit)
    ).all()
    return [request_out(db, r, viewer=current_user) for r in rows]


@router.get("/requests/{request_id}", summary="A single request")
def get_request(
    request_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    request = _get_request(db, request_id)
    if not (
        current_user.role == UserRole.ADMIN
        or _is_student_party(current_user, request)
        or _is_tutor_party(current_user, request)
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to view this request.",
        )
    return request_out(db, request, viewer=current_user)


# --------------------------------------------------------------------------- #
# UPDATE — tutor decisions
# --------------------------------------------------------------------------- #
@router.put("/requests/{request_id}/status", summary="Accept / reject / complete a request")
def decide_request(
    request_id: int,
    payload: BookingRequestDecision,
    current_user: User = Depends(require_roles(UserRole.TUTOR, UserRole.ADMIN)),
    db: Session = Depends(get_db),
):
    request = _get_request(db, request_id)
    if not (current_user.role == UserRole.ADMIN or _is_tutor_party(current_user, request)):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the assigned tutor can change this request.",
        )

    tutor_profile = request.tutor_profile
    student_user = request.student_profile.user if request.student_profile else None
    new_status = RequestStatus(payload.status)
    now = datetime.now()
    subject_name = request.subject.name if request.subject else "Session"

    if new_status == RequestStatus.ACCEPTED:
        if request.status != RequestStatus.PENDING:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Only pending requests can be accepted (current: {request.status.value}).",
            )
        clash = _conflicting_booking(
            db, tutor_profile.id, request.preferred_date, request.preferred_time,
            request.duration_minutes, exclude_id=request.id,
        )
        if clash is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "You already accepted another session that overlaps this time "
                    f"(request #{clash.id})."
                ),
            )
        request.status = RequestStatus.ACCEPTED
        request.responded_at = now
        request.tutor_response_note = payload.note
        action = ActivityAction.REQUEST_ACCEPTED
        notify(
            db,
            student_user.id,
            NotificationType.REQUEST_ACCEPTED,
            f"{tutor_profile.user.full_name} accepted your request",
            f"{subject_name} on {request.session_start().strftime('%a, %d %b %Y')} at "
            f"{fmt_time(request.preferred_time)}.",
            link="dashboard.html?view=requests",
        )
        message = "Request accepted. It now appears in your upcoming sessions."

    elif new_status == RequestStatus.REJECTED:
        if request.status not in (RequestStatus.PENDING, RequestStatus.ACCEPTED):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"A {request.status.value} request cannot be rejected.",
            )
        request.status = RequestStatus.REJECTED
        request.responded_at = now
        request.tutor_response_note = payload.note
        action = ActivityAction.REQUEST_REJECTED
        notify(
            db,
            student_user.id,
            NotificationType.REQUEST_REJECTED,
            f"{tutor_profile.user.full_name} could not take your request",
            payload.note or f"{subject_name} request was declined. Try another tutor.",
            link="tutors.html",
        )
        message = "Request rejected and the student has been notified."

    elif new_status == RequestStatus.COMPLETED:
        if request.status != RequestStatus.ACCEPTED:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Only an accepted session can be marked as completed.",
            )
        if request.preferred_date > date.today():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This session is still in the future, so it cannot be completed yet.",
            )
        request.status = RequestStatus.COMPLETED
        request.completed_at = datetime.now(timezone.utc)
        action = ActivityAction.REQUEST_COMPLETED
        notify(
            db,
            student_user.id,
            NotificationType.REQUEST_COMPLETED,
            "Session completed — leave a review",
            f"How was your {subject_name} session with {tutor_profile.user.full_name}? "
            "Your review helps other families.",
            link="dashboard.html?view=requests",
        )
        message = "Session marked as completed. The student can now leave a review."

    else:  # cancelled by tutor
        if request.status in (RequestStatus.COMPLETED, RequestStatus.CANCELLED):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"A {request.status.value} request cannot be cancelled.",
            )
        request.status = RequestStatus.CANCELLED
        request.cancelled_at = datetime.now(timezone.utc)
        request.cancel_reason = payload.note or "Cancelled by the tutor"
        action = ActivityAction.REQUEST_CANCELLED
        notify(
            db,
            student_user.id,
            NotificationType.REQUEST_CANCELLED,
            f"{tutor_profile.user.full_name} cancelled your session",
            request.cancel_reason,
            link="dashboard.html?view=requests",
        )
        message = "Request cancelled and the student has been notified."

    request.read_by_student = False
    log_activity(
        db,
        action,
        f"{tutor_profile.user.full_name} set request #{request.id} ({subject_name}) to "
        f"{request.status.value}",
        actor_user_id=current_user.id,
        entity_type="booking_request",
        entity_id=request.id,
    )
    db.commit()
    db.refresh(request)
    return {"detail": message, "data": request_out(db, request, viewer=current_user)}


# --------------------------------------------------------------------------- #
# UPDATE — student edits & cancellation
# --------------------------------------------------------------------------- #
@router.put("/requests/{request_id}", summary="Edit a pending request")
def update_request(
    request_id: int,
    payload: BookingRequestUpdate,
    current_user: User = Depends(require_roles(UserRole.STUDENT)),
    db: Session = Depends(get_db),
):
    request = _get_request(db, request_id)
    if not _is_student_party(current_user, request):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="This is not your request."
        )
    if request.status != RequestStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Only pending requests can be edited (current: {request.status.value}).",
        )

    data = payload.model_dump(exclude_unset=True)
    ignore_availability = data.pop("ignore_availability", False)
    if not data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Nothing to update."
        )

    new_date = data.get("preferred_date", request.preferred_date)
    new_time = data.get("preferred_time", request.preferred_time)
    new_duration = data.get("duration_minutes", request.duration_minutes)
    new_mode = data.get("mode", request.mode)

    if not _lead_time_ok(new_date, new_time):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The new date/time is too soon or in the past.",
        )

    tutor_profile = request.tutor_profile
    if new_mode == TeachingMode.ONLINE and not tutor_profile.accepts_online:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="This tutor does not teach online."
        )
    if new_mode == TeachingMode.IN_PERSON and not tutor_profile.accepts_in_person:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This tutor does not offer in-person sessions.",
        )

    slot = matching_availability(
        tutor_profile.availability, new_date, new_time, new_duration, new_mode
    )
    if slot is None and not ignore_availability:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That time is outside the tutor's availability.",
        )

    clash = _conflicting_booking(
        db, tutor_profile.id, new_date, new_time, new_duration, exclude_id=request.id
    )
    if clash is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The tutor already has a session at that time.",
        )

    for field, value in data.items():
        if field == "mode":
            request.mode = TeachingMode(value) if not isinstance(value, TeachingMode) else value
        elif value is not None:
            setattr(request, field, value)

    db.commit()
    db.refresh(request)
    return {"detail": "Request updated.", "data": request_out(db, request, viewer=current_user)}


@router.post("/requests/{request_id}/cancel", summary="Cancel a request")
def cancel_request(
    request_id: int,
    payload: Optional[BookingRequestCancel] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    request = _get_request(db, request_id)
    allowed = (
        current_user.role == UserRole.ADMIN
        or _is_student_party(current_user, request)
        or _is_tutor_party(current_user, request)
    )
    if not allowed:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your request.")

    if request.status in (RequestStatus.COMPLETED, RequestStatus.CANCELLED, RequestStatus.REJECTED):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A {request.status.value} request cannot be cancelled.",
        )

    reason = (payload.reason if payload else None) or (
        "Cancelled by the student" if _is_student_party(current_user, request) else "Cancelled"
    )
    request.status = RequestStatus.CANCELLED
    request.cancelled_at = datetime.now(timezone.utc)
    request.cancel_reason = reason[:255]

    other_user = (
        request.tutor_profile.user
        if _is_student_party(current_user, request)
        else request.student_profile.user
    )
    notify(
        db,
        other_user.id,
        NotificationType.REQUEST_CANCELLED,
        "A session was cancelled",
        f"{request.subject.name} on "
        f"{request.preferred_date.strftime('%a, %d %b %Y')} at "
        f"{fmt_time(request.preferred_time)}. Reason: {reason}",
        link="dashboard.html?view=requests",
    )
    log_activity(
        db,
        ActivityAction.REQUEST_CANCELLED,
        f"{current_user.full_name} cancelled request #{request.id}",
        actor_user_id=current_user.id,
        entity_type="booking_request",
        entity_id=request.id,
    )
    db.commit()
    db.refresh(request)
    return {"detail": "Request cancelled.", "data": request_out(db, request, viewer=current_user)}


@router.post("/requests/{request_id}/read", response_model=Message, summary="Mark a request as read")
def mark_read(
    request_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    request = _get_request(db, request_id)
    if _is_student_party(current_user, request):
        request.read_by_student = True
    elif _is_tutor_party(current_user, request):
        request.read_by_tutor = True
    elif current_user.role == UserRole.ADMIN:
        request.read_by_student = True
        request.read_by_tutor = True
    else:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your request.")
    db.commit()
    return {"detail": "Marked as read."}


# --------------------------------------------------------------------------- #
# DELETE
# --------------------------------------------------------------------------- #
@router.delete("/requests/{request_id}", response_model=Message, summary="Delete a request")
def delete_request(
    request_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    request = _get_request(db, request_id)

    if current_user.role == UserRole.STUDENT:
        if not _is_student_party(current_user, request):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your request.")
        if request.status in ACTIVE_STATUSES or request.status == RequestStatus.COMPLETED:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Active and completed requests cannot be deleted. "
                    "Cancel the request instead."
                ),
            )
    elif current_user.role == UserRole.TUTOR:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tutors cannot delete requests. Reject or cancel them instead.",
        )
    elif current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed.")

    request_id_value = request.id
    if request.review is not None:
        db.delete(request.review)
    db.delete(request)
    log_activity(
        db,
        ActivityAction.REQUEST_CANCELLED,
        f"{current_user.full_name} deleted booking request #{request_id_value}",
        actor_user_id=current_user.id,
        entity_type="booking_request",
        entity_id=request_id_value,
    )
    db.commit()
    return {"detail": f"Booking request #{request_id_value} deleted."}
