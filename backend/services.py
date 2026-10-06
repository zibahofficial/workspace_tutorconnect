"""
Tutor discovery service.

Every search/filter is translated into a real SQL query (parameterised through
the ORM).  Nothing here reads hard-coded data.

Supported:
    q                 free text (name, headline, bio, city, state, subject)
    subject / subject_id
    city / state / location
    mode              in_person | online | hybrid
    min_experience / max_experience
    min_price / max_price
    day / start_after / end_before  (availability window matching)
    available_today
    min_rating
    verified_only
    sort              relevance | rating | price_asc | price_desc | experience | newest
"""
from __future__ import annotations

from datetime import date, time
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import Select, and_, distinct, func, or_, select
from sqlalchemy.orm import Session

from models import (
    DAYS_OF_WEEK,
    Availability,
    BookingRequest,
    Favorite,
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
from helpers import tutor_summary


def _time_to_minutes(value: Optional[str]) -> Optional[int]:
    if not value:
        return None
    try:
        parts = value.split(":")
        return int(parts[0]) * 60 + int(parts[1] if len(parts) > 1 else 0)
    except (ValueError, IndexError):
        return None


def _slot_minutes(session: Session, column) -> Any:
    """Portable TIME -> minutes expression (SQLite vs PostgreSQL)."""
    from sqlalchemy import Integer, extract

    if session.bind.dialect.name == "sqlite":
        cast_str = func.cast(func.strftime("%H", column), Integer) * 60 + func.cast(
            func.strftime("%M", column), Integer
        )
        return cast_str
    return extract("hour", column) * 60 + extract("minute", column)


def search_tutors(
    db: Session,
    *,
    q: Optional[str] = None,
    subject: Optional[str] = None,
    subject_id: Optional[int] = None,
    city: Optional[str] = None,
    state: Optional[str] = None,
    location: Optional[str] = None,
    mode: Optional[str] = None,
    min_experience: Optional[int] = None,
    max_experience: Optional[int] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    day: Optional[str] = None,
    start_after: Optional[str] = None,
    end_before: Optional[str] = None,
    available_today: bool = False,
    min_rating: Optional[float] = None,
    min_reviews: Optional[int] = None,
    verified_only: bool = False,
    language: Optional[str] = None,
    sort: str = "relevance",
    page: int = 1,
    page_size: int = 12,
    include_hidden: bool = False,
    current_user: Optional[User] = None,
) -> Dict[str, Any]:
    """Return a paginated dict of matching tutors plus the applied filters."""

    stmt: Select = select(TutorProfile, User).join(User, TutorProfile.user_id == User.id)

    if not include_hidden:
        stmt = stmt.where(
            TutorProfile.is_visible.is_(True),
            TutorProfile.approval_status == TutorStatus.APPROVED,
            User.is_active.is_(True),
            User.role == "tutor",
        )

    # ---- aggregates (subqueries, so filters can use them) ----------------
    rating_sq = (
        select(func.avg(Review.rating))
        .where(Review.tutor_profile_id == TutorProfile.id, Review.is_deleted.is_(False))
        .correlate(TutorProfile)
        .scalar_subquery()
    )
    review_count_sq = (
        select(func.count(Review.id))
        .where(Review.tutor_profile_id == TutorProfile.id, Review.is_deleted.is_(False))
        .correlate(TutorProfile)
        .scalar_subquery()
    )
    completed_sq = (
        select(func.count(BookingRequest.id))
        .where(
            BookingRequest.tutor_profile_id == TutorProfile.id,
            BookingRequest.status == RequestStatus.COMPLETED,
        )
        .correlate(TutorProfile)
        .scalar_subquery()
    )

    # ---- free text ------------------------------------------------------
    if q and q.strip():
        term = f"%{q.strip()}%"
        subject_match = (
            select(TutorSubject.id)
            .join(Subject, Subject.id == TutorSubject.subject_id)
            .where(
                TutorSubject.tutor_profile_id == TutorProfile.id,
                or_(Subject.name.ilike(term), Subject.category.ilike(term)),
            )
            .exists()
        )
        stmt = stmt.where(
            or_(
                User.full_name.ilike(term),
                TutorProfile.headline.ilike(term),
                TutorProfile.bio.ilike(term),
                TutorProfile.city.ilike(term),
                TutorProfile.state.ilike(term),
                TutorProfile.qualifications.ilike(term),
                TutorProfile.languages.ilike(term),
                subject_match,
            )
        )

    # ---- subject --------------------------------------------------------
    if subject_id:
        stmt = stmt.where(
            select(TutorSubject.id)
            .where(
                TutorSubject.tutor_profile_id == TutorProfile.id,
                TutorSubject.subject_id == subject_id,
            )
            .exists()
        )
    if subject and subject.strip():
        term = f"%{subject.strip()}%"
        stmt = stmt.where(
            select(TutorSubject.id)
            .join(Subject, Subject.id == TutorSubject.subject_id)
            .where(
                TutorSubject.tutor_profile_id == TutorProfile.id,
                Subject.name.ilike(term),
            )
            .exists()
        )

    # ---- location -------------------------------------------------------
    if city and city.strip():
        stmt = stmt.where(TutorProfile.city.ilike(f"%{city.strip()}%"))
    if state and state.strip():
        stmt = stmt.where(TutorProfile.state.ilike(f"%{state.strip()}%"))
    if location and location.strip():
        term = f"%{location.strip()}%"
        stmt = stmt.where(
            or_(
                TutorProfile.city.ilike(term),
                TutorProfile.state.ilike(term),
                TutorProfile.country.ilike(term),
            )
        )

    # ---- mode -----------------------------------------------------------
    if mode and mode != "any":
        wanted = mode.strip().lower()
        if wanted == TeachingMode.ONLINE.value:
            stmt = stmt.where(TutorProfile.accepts_online.is_(True))
        elif wanted == TeachingMode.IN_PERSON.value:
            stmt = stmt.where(TutorProfile.accepts_in_person.is_(True))
        else:
            stmt = stmt.where(TutorProfile.teaching_mode == TeachingMode.HYBRID)

    # ---- experience -----------------------------------------------------
    if min_experience is not None:
        stmt = stmt.where(TutorProfile.years_experience >= min_experience)
    if max_experience is not None:
        stmt = stmt.where(TutorProfile.years_experience <= max_experience)

    # ---- price ----------------------------------------------------------
    if min_price is not None:
        stmt = stmt.where(TutorProfile.hourly_rate >= min_price)
    if max_price is not None:
        stmt = stmt.where(TutorProfile.hourly_rate <= max_price)

    # ---- rating ---------------------------------------------------------
    if min_rating is not None and min_rating > 0:
        stmt = stmt.where(func.coalesce(rating_sq, 0) >= min_rating)
    if min_reviews is not None and min_reviews > 0:
        stmt = stmt.where(func.coalesce(review_count_sq, 0) >= min_reviews)

    # ---- misc -----------------------------------------------------------
    if verified_only:
        stmt = stmt.where(TutorProfile.verified.is_(True))
    if language and language.strip():
        stmt = stmt.where(TutorProfile.languages.ilike(f"%{language.strip()}%"))

    # ---- availability window -------------------------------------------
    target_day = None
    if available_today:
        target_day = DAYS_OF_WEEK[date.today().weekday()]
    elif day and day.strip():
        target_day = day.strip().title()
        if target_day not in DAYS_OF_WEEK:
            target_day = None

    if target_day or start_after or end_before:
        slot_start = _slot_minutes(db, Availability.start_time)
        slot_end = _slot_minutes(db, Availability.end_time)
        avail_conditions = [
            Availability.tutor_profile_id == TutorProfile.id,
            Availability.is_active.is_(True),
        ]
        if target_day:
            avail_conditions.append(Availability.day_of_week == target_day)
        start_minutes = _time_to_minutes(start_after)
        end_minutes = _time_to_minutes(end_before)
        if start_minutes is not None:
            avail_conditions.append(slot_end >= start_minutes)
        if end_minutes is not None:
            avail_conditions.append(slot_start <= end_minutes)
        stmt = stmt.where(select(Availability.id).where(and_(*avail_conditions)).exists())

    # ---- ordering -------------------------------------------------------
    sort_key = (sort or "relevance").lower()
    if sort_key == "rating":
        order = [
            func.coalesce(rating_sq, 0).desc(),
            func.coalesce(review_count_sq, 0).desc(),
            completed_sq.desc(),
        ]
    elif sort_key == "price_asc":
        order = [TutorProfile.hourly_rate.asc(), func.coalesce(rating_sq, 0).desc()]
    elif sort_key == "price_desc":
        order = [TutorProfile.hourly_rate.desc(), func.coalesce(rating_sq, 0).desc()]
    elif sort_key == "experience":
        order = [TutorProfile.years_experience.desc(), func.coalesce(rating_sq, 0).desc()]
    elif sort_key == "newest":
        order = [TutorProfile.created_at.desc()]
    elif sort_key == "popular":
        order = [completed_sq.desc(), func.coalesce(rating_sq, 0).desc()]
    else:  # relevance
        order = [
            (func.coalesce(rating_sq, 0) * 2 + func.coalesce(review_count_sq, 0) * 0.25
             + completed_sq * 0.5 + TutorProfile.years_experience * 0.2).desc(),
            TutorProfile.id.asc(),
        ]

    # ---- count + page of ids -------------------------------------------
    total_stmt = select(func.count()).select_from(stmt.order_by(None).subquery())
    total = int(db.scalar(total_stmt) or 0)

    page = max(1, page)
    page_size = max(1, min(page_size, 100))

    # Visibility rules are re-applied on the id query so admins can opt into
    # hidden profiles while public searches never leak them.
    id_stmt = select(
        TutorProfile.id,
        func.coalesce(rating_sq, 0).label("rating"),
        func.coalesce(review_count_sq, 0).label("review_count"),
        func.coalesce(completed_sq, 0).label("completed"),
    ).join(User, TutorProfile.user_id == User.id)
    if not include_hidden:
        id_stmt = id_stmt.where(
            TutorProfile.is_visible.is_(True),
            TutorProfile.approval_status == TutorStatus.APPROVED,
            User.is_active.is_(True),
            User.role == UserRole.TUTOR,
        )
    if stmt.whereclause is not None:
        id_stmt = id_stmt.where(stmt.whereclause)
    id_stmt = (
        id_stmt.order_by(*order).limit(page_size).offset((page - 1) * page_size)
    )
    rows = db.execute(id_stmt).all()

    if not rows:
        return {
            "items": [],
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": max(1, (total + page_size - 1) // page_size),
            "filters_applied": _applied_filters(locals()),
        }

    ordered_ids = [row[0] for row in rows]
    meta = {row[0]: row for row in rows}

    profiles = db.scalars(
        select(TutorProfile).where(TutorProfile.id.in_(ordered_ids))
    ).all()
    by_id = {p.id: p for p in profiles}

    favorite_ids: set[int] = set()
    if current_user is not None and current_user.role == "student":
        student_profile = db.scalar(
            select(StudentProfile).where(StudentProfile.user_id == current_user.id)
        )
        if student_profile:
            favorite_ids = set(
                db.scalars(
                    select(Favorite.tutor_profile_id).where(
                        Favorite.student_id == student_profile.id
                    )
                ).all()
            )

    items: List[Dict[str, Any]] = []
    for tutor_id in ordered_ids:
        profile = by_id.get(tutor_id)
        if profile is None:
            continue
        row = meta[tutor_id]
        items.append(
            tutor_summary(
                db,
                profile,
                rating=float(row[1]),
                review_count=int(row[2]),
                completed_sessions=int(row[3]),
                match_score=_match_score(profile, float(row[1]), int(row[2]), int(row[3])),
                is_favorite=tutor_id in favorite_ids,
            )
        )

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": max(1, (total + page_size - 1) // page_size),
        "filters_applied": _applied_filters(locals()),
    }


def _match_score(profile: TutorProfile, rating: float, reviews: int, completed: int) -> int:
    """0-100 relevance score used by the UI's 'best match' badge."""
    score = 40
    score += min(rating / 5.0, 1.0) * 25
    score += min(reviews / 10.0, 1.0) * 15
    score += min(completed / 20.0, 1.0) * 10
    score += min(profile.years_experience / 10.0, 1.0) * 10
    if profile.verified:
        score += 5
    if profile.tutor_subjects:
        score += 3
    if profile.availability:
        score += 2
    return int(min(score, 100))


def _applied_filters(scope: Dict[str, Any]) -> Dict[str, Any]:
    keys = (
        "q", "subject", "subject_id", "city", "state", "location", "mode",
        "min_experience", "max_experience", "min_price", "max_price", "day",
        "start_after", "end_before", "available_today", "min_rating",
        "verified_only", "sort",
    )
    return {k: scope.get(k) for k in keys if scope.get(k) not in (None, "", False)}


# --------------------------------------------------------------------------- #
# Facets used by the filter sidebar (real DISTINCT values from the DB)
# --------------------------------------------------------------------------- #
def search_facets(db: Session) -> Dict[str, Any]:
    approved = and_(
        TutorProfile.is_visible.is_(True),
        TutorProfile.approval_status == TutorStatus.APPROVED,
        User.is_active.is_(True),
    )
    base = select(TutorProfile).join(User, TutorProfile.user_id == User.id).where(approved)

    cities = db.scalars(
        select(TutorProfile.city)
        .join(User, TutorProfile.user_id == User.id)
        .where(approved)
        .distinct()
        .order_by(TutorProfile.city)
    ).all()
    states = db.scalars(
        select(TutorProfile.state)
        .join(User, TutorProfile.user_id == User.id)
        .where(approved)
        .distinct()
        .order_by(TutorProfile.state)
    ).all()

    price_row = db.execute(
        select(
            func.coalesce(func.min(TutorProfile.hourly_rate), 0),
            func.coalesce(func.max(TutorProfile.hourly_rate), 0),
            func.coalesce(func.avg(TutorProfile.hourly_rate), 0),
        )
        .select_from(TutorProfile)
        .join(User, TutorProfile.user_id == User.id)
        .where(approved)
    ).one()

    experience_row = db.execute(
        select(
            func.coalesce(func.min(TutorProfile.years_experience), 0),
            func.coalesce(func.max(TutorProfile.years_experience), 0),
        )
        .select_from(TutorProfile)
        .join(User, TutorProfile.user_id == User.id)
        .where(approved)
    ).one()

    subject_rows = db.execute(
        select(Subject.id, Subject.name, Subject.category, Subject.icon, func.count(TutorSubject.id))
        .outerjoin(TutorSubject, TutorSubject.subject_id == Subject.id)
        .outerjoin(
            TutorProfile,
            and_(TutorProfile.id == TutorSubject.tutor_profile_id),
        )
        .outerjoin(User, User.id == TutorProfile.user_id)
        .where(Subject.is_active.is_(True))
        .group_by(Subject.id, Subject.name, Subject.category, Subject.icon)
        .order_by(func.count(TutorSubject.id).desc(), Subject.name)
    ).all()

    total_tutors = int(
        db.scalar(select(func.count()).select_from(base.order_by(None).subquery())) or 0
    )

    return {
        "total_tutors": total_tutors,
        "cities": list(cities),
        "states": list(states),
        "price": {
            "min": float(price_row[0]),
            "max": float(price_row[1]),
            "average": round(float(price_row[2]), 2),
        },
        "experience": {"min": int(experience_row[0]), "max": int(experience_row[1])},
        "subjects": [
            {
                "id": row[0],
                "name": row[1],
                "category": row[2],
                "icon": row[3],
                "tutor_count": int(row[4] or 0),
            }
            for row in subject_rows
        ],
        "modes": [
            {"value": m.value, "label": label}
            for m, label in (
                (TeachingMode.IN_PERSON, "In person"),
                (TeachingMode.ONLINE, "Online"),
                (TeachingMode.HYBRID, "Online & in person"),
            )
        ],
        "days": DAYS_OF_WEEK,
    }


def featured_tutors(db: Session, limit: int = 6) -> List[Dict[str, Any]]:
    result = search_tutors(
        db, sort="rating", page=1, page_size=limit, include_hidden=False
    )
    return result["items"]
