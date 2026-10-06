"""
Administrator endpoints: platform statistics, user management, moderation.

Every number on the admin dashboard is computed from live database rows.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from auth import get_current_user, hash_password, normalize_email, require_roles
from database import get_db
from helpers import log_activity, request_out, tutor_summary
from models import (
    ActivityAction,
    ActivityLog,
    Availability,
    BookingRequest,
    Notification,
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
from schemas import AdminStats, AdminUserOut, AdminUserUpdate, Message
from services import search_tutors

router = APIRouter(prefix="/admin", tags=["Administration"])

admin_only = require_roles(UserRole.ADMIN)


# --------------------------------------------------------------------------- #
# Statistics
# --------------------------------------------------------------------------- #
@router.get("/stats", response_model=AdminStats, summary="Live platform statistics")
def platform_stats(
    days: int = Query(14, ge=1, le=90),
    db: Session = Depends(get_db),
    _: User = Depends(admin_only),
):
    today = date.today()
    window_start = today - timedelta(days=days - 1)

    role_counts = dict(
        db.execute(select(User.role, func.count(User.id)).group_by(User.role)).all()
    )

    def role_total(role: UserRole) -> int:
        return int(role_counts.get(role, role_counts.get(role.value, 0)) or 0)

    tutor_status_counts = dict(
        db.execute(
            select(TutorProfile.approval_status, func.count(TutorProfile.id)).group_by(
                TutorProfile.approval_status
            )
        ).all()
    )

    def status_total(value: TutorStatus) -> int:
        return int(tutor_status_counts.get(value, tutor_status_counts.get(value.value, 0)) or 0)

    request_counts = dict(
        db.execute(
            select(BookingRequest.status, func.count(BookingRequest.id)).group_by(
                BookingRequest.status
            )
        ).all()
    )

    def request_total(value: RequestStatus) -> int:
        return int(request_counts.get(value, request_counts.get(value.value, 0)) or 0)

    total_reviews = int(db.scalar(select(func.count(Review.id))) or 0)
    hidden_reviews = int(
        db.scalar(select(func.count(Review.id)).where(Review.is_deleted.is_(True))) or 0
    )
    average_rating = float(
        db.scalar(select(func.avg(Review.rating)).where(Review.is_deleted.is_(False))) or 0
    )
    gross_value = float(
        db.scalar(
            select(func.coalesce(func.sum(BookingRequest.budget), 0)).where(
                BookingRequest.status.in_([RequestStatus.ACCEPTED, RequestStatus.COMPLETED])
            )
        )
        or 0
    )

    new_users_7d = int(
        db.scalar(
            select(func.count(User.id)).where(
                User.created_at >= datetime.combine(today - timedelta(days=7), datetime.min.time())
            )
        )
        or 0
    )
    requests_7d = int(
        db.scalar(
            select(func.count(BookingRequest.id)).where(
                BookingRequest.created_at
                >= datetime.combine(today - timedelta(days=7), datetime.min.time())
            )
        )
        or 0
    )

    # requests by status (for the donut chart)
    requests_by_status = [
        {"label": s.value.replace("_", " ").title(), "value": request_total(s)}
        for s in RequestStatus
    ]

    # top subjects by tutor supply
    top_subjects = [
        {
            "label": row[0],
            "value": int(row[1]),
        }
        for row in db.execute(
            select(Subject.name, func.count(TutorSubject.id))
            .join(TutorSubject, TutorSubject.subject_id == Subject.id)
            .group_by(Subject.name)
            .order_by(func.count(TutorSubject.id).desc())
            .limit(8)
        ).all()
    ]

    tutors_by_state = [
        {"label": row[0], "value": int(row[1])}
        for row in db.execute(
            select(TutorProfile.state, func.count(TutorProfile.id))
            .group_by(TutorProfile.state)
            .order_by(func.count(TutorProfile.id).desc())
            .limit(8)
        ).all()
    ]

    # time series built in Python so it works identically on SQLite & Postgres
    signups_by_day = _daily_series(
        db, select(User.created_at), window_start, days
    )
    requests_by_day = _daily_series(
        db, select(BookingRequest.created_at), window_start, days
    )

    return AdminStats(
        total_users=int(db.scalar(select(func.count(User.id))) or 0),
        total_tutors=role_total(UserRole.TUTOR),
        total_students=role_total(UserRole.STUDENT),
        total_admins=role_total(UserRole.ADMIN),
        active_users=int(db.scalar(select(func.count(User.id)).where(User.is_active.is_(True))) or 0),
        pending_tutor_approvals=status_total(TutorStatus.PENDING),
        approved_tutors=status_total(TutorStatus.APPROVED),
        suspended_tutors=status_total(TutorStatus.SUSPENDED),
        total_requests=int(db.scalar(select(func.count(BookingRequest.id))) or 0),
        pending_requests=request_total(RequestStatus.PENDING),
        accepted_requests=request_total(RequestStatus.ACCEPTED),
        rejected_requests=request_total(RequestStatus.REJECTED),
        cancelled_requests=request_total(RequestStatus.CANCELLED),
        completed_requests=request_total(RequestStatus.COMPLETED),
        total_reviews=total_reviews,
        hidden_reviews=hidden_reviews,
        average_rating=round(average_rating, 2),
        total_subjects=int(
            db.scalar(select(func.count(Subject.id)).where(Subject.is_active.is_(True))) or 0
        ),
        total_availability_slots=int(db.scalar(select(func.count(Availability.id))) or 0),
        new_users_last_7_days=new_users_7d,
        requests_last_7_days=requests_7d,
        gross_session_value=round(gross_value, 2),
        requests_by_status=requests_by_status,
        top_subjects=top_subjects,
        tutors_by_state=tutors_by_state,
        signups_by_day=signups_by_day,
        requests_by_day=requests_by_day,
    ).model_dump()


def _daily_series(db: Session, column_select, start: date, days: int) -> List[Dict[str, Any]]:
    rows = db.execute(column_select.where(column_select.selected_columns[0] >= datetime.combine(start, datetime.min.time()))).all()
    buckets: Dict[str, int] = {}
    for (created_at,) in rows:
        if created_at is None:
            continue
        if isinstance(created_at, datetime):
            key = created_at.date().isoformat()
        else:
            key = str(created_at)[:10]
        buckets[key] = buckets.get(key, 0) + 1
    return [
        {
            "label": (start + timedelta(days=i)).strftime("%d %b"),
            "date": (start + timedelta(days=i)).isoformat(),
            "value": buckets.get((start + timedelta(days=i)).isoformat(), 0),
        }
        for i in range(days)
    ]


@router.get("/activity", summary="Platform activity feed")
def activity_feed(
    limit: int = Query(30, ge=1, le=200),
    action: Optional[str] = Query(None, max_length=40),
    db: Session = Depends(get_db),
    _: User = Depends(admin_only),
):
    stmt = select(ActivityLog).order_by(ActivityLog.created_at.desc()).limit(limit)
    if action:
        stmt = stmt.where(ActivityLog.action == action)
    rows = db.scalars(stmt).all()
    actor_names = {}
    ids = {r.actor_user_id for r in rows if r.actor_user_id}
    if ids:
        for user_id, full_name in db.execute(
            select(User.id, User.full_name).where(User.id.in_(ids))
        ).all():
            actor_names[user_id] = full_name
    return [
        {
            "id": row.id,
            "action": row.action.value,
            "description": row.description,
            "entity_type": row.entity_type,
            "entity_id": row.entity_id,
            "actor_name": actor_names.get(row.actor_user_id, "System"),
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in rows
    ]


# --------------------------------------------------------------------------- #
# Users
# --------------------------------------------------------------------------- #
def _admin_user_out(db: Session, user: User) -> Dict[str, Any]:
    tutor_profile = user.tutor_profile
    student_profile = user.student_profile
    requests_count = 0
    if tutor_profile:
        requests_count = int(
            db.scalar(
                select(func.count(BookingRequest.id)).where(
                    BookingRequest.tutor_profile_id == tutor_profile.id
                )
            )
            or 0
        )
    elif student_profile:
        requests_count = int(
            db.scalar(
                select(func.count(BookingRequest.id)).where(
                    BookingRequest.student_id == student_profile.id
                )
            )
            or 0
        )
    profile = tutor_profile or student_profile
    return {
        "id": user.id,
        "email": user.email,
        "full_name": user.full_name,
        "phone": user.phone,
        "role": user.role.value,
        "is_active": user.is_active,
        "avatar_url": user.avatar_url,
        "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "city": getattr(profile, "city", None),
        "state": getattr(profile, "state", None),
        "headline": tutor_profile.headline if tutor_profile else None,
        "hourly_rate": float(tutor_profile.hourly_rate) if tutor_profile else None,
        "approval_status": tutor_profile.approval_status.value if tutor_profile else None,
        "requests_count": requests_count,
    }


@router.get("/users", response_model=List[AdminUserOut], summary="All users")
def list_users(
    role: Optional[str] = Query(None, pattern="^(tutor|student|admin)$"),
    q: Optional[str] = Query(None, max_length=120),
    is_active: Optional[bool] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    db: Session = Depends(get_db),
    _: User = Depends(admin_only),
):
    stmt = select(User)
    if role:
        stmt = stmt.where(User.role == role)
    if is_active is not None:
        stmt = stmt.where(User.is_active.is_(is_active))
    if q and q.strip():
        term = f"%{q.strip()}%"
        stmt = stmt.where(or_(User.full_name.ilike(term), User.email.ilike(term)))
    stmt = stmt.order_by(User.created_at.desc()).limit(page_size).offset((page - 1) * page_size)
    return [_admin_user_out(db, u) for u in db.scalars(stmt).all()]


@router.get("/users/{user_id}", response_model=AdminUserOut, summary="One user")
def get_user(
    user_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(admin_only),
):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    return _admin_user_out(db, user)


@router.put("/users/{user_id}", response_model=AdminUserOut, summary="Update a user")
def update_user(
    user_id: int,
    payload: AdminUserUpdate,
    current_user: User = Depends(admin_only),
    db: Session = Depends(get_db),
):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    data = payload.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Nothing to update.")

    if user.id == current_user.id and data.get("is_active") is False:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="You cannot deactivate your own account."
        )
    if user.id == current_user.id and data.get("role") in (UserRole.STUDENT, UserRole.TUTOR, "student", "tutor"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot remove your own administrator role.",
        )

    was_active = user.is_active
    for field, value in data.items():
        if field == "role":
            user.role = UserRole(value) if not isinstance(value, UserRole) else value
        else:
            setattr(user, field, value)

    if was_active and not user.is_active:
        log_activity(
            db,
            ActivityAction.USER_DEACTIVATED,
            f"{current_user.full_name} deactivated {user.full_name}",
            actor_user_id=current_user.id,
            entity_type="user",
            entity_id=user.id,
        )
    elif not was_active and user.is_active:
        log_activity(
            db,
            ActivityAction.USER_ACTIVATED,
            f"{current_user.full_name} reactivated {user.full_name}",
            actor_user_id=current_user.id,
            entity_type="user",
            entity_id=user.id,
        )
    db.commit()
    db.refresh(user)
    return _admin_user_out(db, user)


@router.post("/users/{user_id}/toggle-active", response_model=AdminUserOut, summary="Suspend / restore")
def toggle_active(
    user_id: int,
    current_user: User = Depends(admin_only),
    db: Session = Depends(get_db),
):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    if user.id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="You cannot deactivate your own account."
        )
    user.is_active = not user.is_active
    log_activity(
        db,
        ActivityAction.USER_DEACTIVATED if not user.is_active else ActivityAction.USER_ACTIVATED,
        f"{current_user.full_name} "
        f"{'deactivated' if not user.is_active else 'reactivated'} {user.full_name}",
        actor_user_id=current_user.id,
        entity_type="user",
        entity_id=user.id,
    )
    db.commit()
    db.refresh(user)
    return _admin_user_out(db, user)


@router.post(
    "/users",
    response_model=AdminUserOut,
    status_code=status.HTTP_201_CREATED,
    summary="Admin: create an account (e.g. another administrator)",
)
def create_user(
    full_name: str = Query(..., min_length=2, max_length=120),
    email: str = Query(..., max_length=255),
    password: str = Query(..., min_length=8, max_length=128),
    role: str = Query("student", pattern="^(tutor|student|admin)$"),
    current_user: User = Depends(admin_only),
    db: Session = Depends(get_db),
):
    normalized = normalize_email(email)
    if db.scalar(select(User).where(User.email == normalized)) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="That email is already registered."
        )
    user = User(
        email=normalized,
        password_hash=hash_password(password),
        full_name=full_name.strip(),
        role=UserRole(role),
        is_active=True,
    )
    db.add(user)
    db.flush()
    if role == UserRole.STUDENT.value:
        db.add(StudentProfile(user_id=user.id))
    log_activity(
        db,
        ActivityAction.USER_REGISTERED,
        f"{current_user.full_name} created a {role} account for {user.full_name}",
        actor_user_id=current_user.id,
        entity_type="user",
        entity_id=user.id,
    )
    db.commit()
    db.refresh(user)
    return _admin_user_out(db, user)


@router.delete("/users/{user_id}", response_model=Message, summary="Admin: delete a user")
def delete_user(
    user_id: int,
    current_user: User = Depends(admin_only),
    db: Session = Depends(get_db),
):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    if user.id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="You cannot delete your own account."
        )
    if user.role == UserRole.ADMIN:
        remaining = int(
            db.scalar(
                select(func.count(User.id)).where(
                    User.role == UserRole.ADMIN, User.is_active.is_(True)
                )
            )
            or 0
        )
        if remaining <= 1:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="At least one administrator must remain on the platform.",
            )

    name = user.full_name
    if user.tutor_profile is not None:
        db.delete(user.tutor_profile)
    if user.student_profile is not None:
        db.delete(user.student_profile)
    db.delete(user)
    log_activity(
        db,
        ActivityAction.USER_DEACTIVATED,
        f"{current_user.full_name} deleted the account of {name}",
        actor_user_id=current_user.id,
        entity_type="user",
        entity_id=user_id,
    )
    db.commit()
    return {"detail": f"Account for {name} has been deleted."}


# --------------------------------------------------------------------------- #
# Tutors (admin view incl. hidden / pending)
# --------------------------------------------------------------------------- #
@router.get("/tutors", summary="All tutors (including pending & suspended)")
def admin_tutors(
    approval_status: Optional[str] = Query(None, pattern="^(pending|approved|suspended)$"),
    q: Optional[str] = Query(None, max_length=120),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    _: User = Depends(admin_only),
):
    stmt = select(TutorProfile).join(User, TutorProfile.user_id == User.id)
    if approval_status:
        stmt = stmt.where(TutorProfile.approval_status == TutorStatus(approval_status))
    if q and q.strip():
        term = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                User.full_name.ilike(term),
                TutorProfile.headline.ilike(term),
                TutorProfile.city.ilike(term),
                TutorProfile.state.ilike(term),
            )
        )
    total = int(db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0)
    rows = db.scalars(
        stmt.order_by(TutorProfile.created_at.desc())
        .limit(page_size)
        .offset((page - 1) * page_size)
    ).all()
    return {
        "items": [tutor_summary(db, profile) for profile in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": max(1, (total + page_size - 1) // page_size),
    }


# --------------------------------------------------------------------------- #
# Requests & reviews moderation
# --------------------------------------------------------------------------- #
@router.get("/requests", summary="All booking requests")
def admin_requests(
    status_filter: Optional[str] = Query(
        None, alias="status", pattern="^(pending|accepted|rejected|cancelled|completed)$"
    ),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    db: Session = Depends(get_db),
    admin: User = Depends(admin_only),
):
    stmt = select(BookingRequest)
    if status_filter:
        stmt = stmt.where(BookingRequest.status == RequestStatus(status_filter))
    total = int(db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0)
    rows = db.scalars(
        stmt.order_by(BookingRequest.created_at.desc())
        .limit(page_size)
        .offset((page - 1) * page_size)
    ).all()
    return {
        "items": [request_out(db, r, viewer=admin) for r in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": max(1, (total + page_size - 1) // page_size),
    }


@router.get("/reviews", summary="All reviews")
def admin_reviews(
    include_hidden: bool = Query(False),
    min_rating: Optional[int] = Query(None, ge=1, le=5),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    db: Session = Depends(get_db),
    _: User = Depends(admin_only),
):
    stmt = select(Review)
    if not include_hidden:
        stmt = stmt.where(Review.is_deleted.is_(False))
    if min_rating:
        stmt = stmt.where(Review.rating >= min_rating)
    total = int(db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0)
    rows = db.scalars(
        stmt.order_by(Review.created_at.desc()).limit(page_size).offset((page - 1) * page_size)
    ).all()

    items = []
    for review in rows:
        items.append(
            {
                "id": review.id,
                "rating": review.rating,
                "title": review.title,
                "comment": review.comment,
                "is_deleted": review.is_deleted,
                "deleted_reason": review.deleted_reason,
                "created_at": review.created_at.isoformat() if review.created_at else None,
                "student": {
                    "id": review.student_profile.id,
                    "name": review.student_profile.user.full_name,
                },
                "tutor": {
                    "id": review.tutor_profile.id,
                    "name": review.tutor_profile.user.full_name,
                },
            }
        )
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": max(1, (total + page_size - 1) // page_size),
    }


@router.post("/reviews/{review_id}/hide", response_model=Message, summary="Hide inappropriate review")
def hide_review(
    review_id: int,
    reason: Optional[str] = Query(None, max_length=255),
    current_user: User = Depends(admin_only),
    db: Session = Depends(get_db),
):
    review = db.get(Review, review_id)
    if review is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Review not found.")
    review.is_deleted = True
    review.deleted_reason = (reason or "Removed by moderator")[:255]
    log_activity(
        db,
        ActivityAction.REVIEW_DELETED,
        f"{current_user.full_name} hid review #{review.id} ({review.deleted_reason})",
        actor_user_id=current_user.id,
        entity_type="review",
        entity_id=review.id,
    )
    db.commit()
    return {"detail": "Review hidden from the tutor profile."}


@router.post("/reviews/{review_id}/restore", response_model=Message, summary="Restore a hidden review")
def restore_review(
    review_id: int,
    current_user: User = Depends(admin_only),
    db: Session = Depends(get_db),
):
    review = db.get(Review, review_id)
    if review is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Review not found.")
    review.is_deleted = False
    review.deleted_reason = None
    log_activity(
        db,
        ActivityAction.REVIEW_CREATED,
        f"{current_user.full_name} restored review #{review.id}",
        actor_user_id=current_user.id,
        entity_type="review",
        entity_id=review.id,
    )
    db.commit()
    return {"detail": "Review restored."}


# --------------------------------------------------------------------------- #
# Bookings management
# --------------------------------------------------------------------------- #
@router.post("/requests/{request_id}/cancel", response_model=Message, summary="Admin: cancel a request")
def admin_cancel_request(
    request_id: int,
    reason: str = Query("Cancelled by the platform administrator", max_length=255),
    current_user: User = Depends(admin_only),
    db: Session = Depends(get_db),
):
    request = db.get(BookingRequest, request_id)
    if request is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found.")
    if request.status in (RequestStatus.COMPLETED, RequestStatus.CANCELLED):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A {request.status.value} request cannot be cancelled.",
        )
    request.status = RequestStatus.CANCELLED
    request.cancel_reason = reason
    request.cancelled_at = datetime.now(timezone.utc)
    for user in (request.tutor_profile.user, request.student_profile.user):
        db.add(
            Notification(
                user_id=user.id,
                type=NotificationType.REQUEST_CANCELLED,
                title="A session was cancelled by the platform",
                body=f"{request.subject.name} on "
                f"{request.preferred_date.strftime('%a, %d %b %Y')}. Reason: {reason}",
                link="dashboard.html?view=requests",
            )
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
    return {"detail": f"Request #{request.id} cancelled."}


@router.delete("/requests/{request_id}", response_model=Message, summary="Admin: delete a request")
def admin_delete_request(
    request_id: int,
    current_user: User = Depends(admin_only),
    db: Session = Depends(get_db),
):
    request = db.get(BookingRequest, request_id)
    if request is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found.")
    if request.review is not None:
        db.delete(request.review)
    db.delete(request)
    log_activity(
        db,
        ActivityAction.REQUEST_CANCELLED,
        f"{current_user.full_name} deleted request #{request_id}",
        actor_user_id=current_user.id,
        entity_type="booking_request",
        entity_id=request_id,
    )
    db.commit()
    return {"detail": f"Request #{request_id} deleted."}
