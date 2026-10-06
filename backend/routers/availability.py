"""
Availability & scheduling endpoints.

Weekly recurring slots + one-off exceptions, with overlap protection and a
public "what is actually free on this date" computation that subtracts
already-booked sessions.
"""
from __future__ import annotations

from datetime import date, time, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from auth import get_optional_user, require_roles
from database import get_db
from helpers import (
    availability_out,
    find_overlapping_slot,
    fmt_time,
    log_activity,
    mode_label,
)
from models import (
    DAYS_OF_WEEK,
    DAY_INDEX,
    ActivityAction,
    Availability,
    AvailabilityException,
    BookingRequest,
    RequestStatus,
    TeachingMode,
    TutorProfile,
    TutorStatus,
    User,
    UserRole,
)
from schemas import (
    AvailabilityCreate,
    AvailabilityExceptionCreate,
    AvailabilityUpdate,
    Message,
)

router = APIRouter(tags=["Availability"])


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _own_profile(db: Session, user: User) -> TutorProfile:
    profile = db.scalar(select(TutorProfile).where(TutorProfile.user_id == user.id))
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Create your tutor profile before managing availability.",
        )
    return profile


def _resolve_tutor_profile(
    db: Session, user: Optional[User], tutor_id: Optional[int]
) -> TutorProfile:
    if tutor_id is None:
        if user is None or user.role != UserRole.TUTOR:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="tutor_id is required.",
            )
        return _own_profile(db, user)
    profile = db.get(TutorProfile, tutor_id)
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tutor profile #{tutor_id} does not exist.",
        )
    return profile


def _can_write(user: User, profile: TutorProfile) -> bool:
    return user.role == UserRole.ADMIN or (
        user.role == UserRole.TUTOR and profile.user_id == user.id
    )


def _sorted_slots(db: Session, profile_id: int, only_active: bool = False) -> List[Availability]:
    stmt = select(Availability).where(Availability.tutor_profile_id == profile_id)
    if only_active:
        stmt = stmt.where(Availability.is_active.is_(True))
    stmt = stmt.order_by(Availability.day_index, Availability.start_time)
    return list(db.scalars(stmt).all())


def _booked_ranges(db: Session, profile_id: int, target_date: date) -> List[tuple[int, int]]:
    """Minutes-range of accepted (not cancelled/rejected) sessions on a date."""
    rows = db.execute(
        select(BookingRequest.preferred_time, BookingRequest.duration_minutes).where(
            BookingRequest.tutor_profile_id == profile_id,
            BookingRequest.preferred_date == target_date,
            BookingRequest.status.in_([RequestStatus.ACCEPTED, RequestStatus.COMPLETED]),
        )
    ).all()
    ranges = []
    for start, duration in rows:
        start_minutes = start.hour * 60 + start.minute
        ranges.append((start_minutes, start_minutes + int(duration)))
    return sorted(ranges)


def _pending_ranges(db: Session, profile_id: int, target_date: date) -> List[tuple[int, int]]:
    """Minutes-ranges that already have a *pending* request on a date.

    These do not remove a slot from the picker - a pending request can still be
    rejected or cancelled - but they are reported so the UI can warn the student
    that somebody else has already asked for that time.
    """
    rows = db.execute(
        select(BookingRequest.preferred_time, BookingRequest.duration_minutes).where(
            BookingRequest.tutor_profile_id == profile_id,
            BookingRequest.preferred_date == target_date,
            BookingRequest.status == RequestStatus.PENDING,
        )
    ).all()
    return sorted(
        (start.hour * 60 + start.minute, start.hour * 60 + start.minute + int(duration))
        for start, duration in rows
    )


def open_slots_for_date(
    db: Session, profile: TutorProfile, target_date: date, step_minutes: int = 30
) -> List[Dict[str, Any]]:
    """Compute bookable start times for a date: weekly slots minus exceptions minus bookings."""
    day_name = DAYS_OF_WEEK[target_date.weekday()]
    blocked = db.scalar(
        select(AvailabilityException).where(
            AvailabilityException.tutor_profile_id == profile.id,
            AvailabilityException.date == target_date,
            AvailabilityException.is_blocked.is_(True),
        )
    )
    if blocked is not None:
        return []

    booked = _booked_ranges(db, profile.id, target_date)
    pending = _pending_ranges(db, profile.id, target_date)
    duration = int(profile.session_duration_minutes or 60)
    slots: List[Dict[str, Any]] = []

    for weekly in _sorted_slots(db, profile.id, only_active=True):
        if weekly.day_of_week != day_name:
            continue
        start_minutes = weekly.start_time.hour * 60 + weekly.start_time.minute
        end_minutes = weekly.end_time.hour * 60 + weekly.end_time.minute
        cursor = start_minutes
        while cursor + duration <= end_minutes:
            candidate = (cursor, cursor + duration)
            overlaps = any(
                candidate[0] < b_end and b_start < candidate[1] for b_start, b_end in booked
            )
            if not overlaps:
                start_time = time(cursor // 60, cursor % 60)
                end_time = time((cursor + duration) // 60, (cursor + duration) % 60)
                held_by_pending = any(
                    candidate[0] < p_end and p_start < candidate[1] for p_start, p_end in pending
                )
                slots.append(
                    {
                        "date": target_date.isoformat(),
                        "day_of_week": day_name,
                        "start_time": start_time.strftime("%H:%M"),
                        "end_time": end_time.strftime("%H:%M"),
                        "label": f"{fmt_time(start_time)} \u2013 {fmt_time(end_time)}",
                        "mode": weekly.mode.value,
                        "mode_label": mode_label(weekly.mode),
                        "duration_minutes": duration,
                        "availability_id": weekly.id,
                        "held": held_by_pending,
                    }
                )
            cursor += max(step_minutes, 15)

    return slots


# --------------------------------------------------------------------------- #
# READ
# --------------------------------------------------------------------------- #
@router.get("/availability/mine", summary="My weekly availability (tutor)")
def my_availability(
    current_user: User = Depends(require_roles(UserRole.TUTOR)),
    db: Session = Depends(get_db),
):
    profile = _own_profile(db, current_user)
    return {
        "tutor_id": profile.id,
        "items": [availability_out(s) for s in _sorted_slots(db, profile.id)],
        "exceptions": [
            {
                "id": exc.id,
                "date": exc.date.isoformat(),
                "is_blocked": exc.is_blocked,
                "reason": exc.reason,
            }
            for exc in db.scalars(
                select(AvailabilityException)
                .where(AvailabilityException.tutor_profile_id == profile.id)
                .order_by(AvailabilityException.date)
            ).all()
        ],
    }


@router.get("/tutors/{tutor_id}/availability", summary="A tutor's availability")
def tutor_availability(
    tutor_id: int,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_user),
):
    profile = db.get(TutorProfile, tutor_id)
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Tutor profile not found."
        )
    is_owner = current_user is not None and (
        current_user.role == UserRole.ADMIN or current_user.id == profile.user_id
    )
    if not is_owner and (
        not profile.is_visible or profile.approval_status != TutorStatus.APPROVED
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="This tutor profile is not available."
        )

    return {
        "tutor_id": profile.id,
        "tutor_name": profile.user.full_name,
        "session_duration_minutes": profile.session_duration_minutes,
        "teaching_mode": profile.teaching_mode.value,
        "items": [availability_out(s) for s in _sorted_slots(db, profile.id, only_active=not is_owner)],
        "by_day": _group_by_day(db, profile.id),
    }


def _group_by_day(db: Session, profile_id: int) -> List[Dict[str, Any]]:
    grouped: Dict[str, List[Dict[str, Any]]] = {day: [] for day in DAYS_OF_WEEK}
    for slot in _sorted_slots(db, profile_id, only_active=True):
        grouped[slot.day_of_week].append(availability_out(slot))
    return [
        {"day": day, "index": DAY_INDEX[day], "slots": grouped[day], "available": bool(grouped[day])}
        for day in DAYS_OF_WEEK
    ]


@router.get("/tutors/{tutor_id}/open-slots", summary="Real free slots for a date range")
def open_slots(
    tutor_id: int,
    from_date: Optional[date] = Query(None, description="Defaults to today"),
    days: int = Query(7, ge=1, le=21),
    db: Session = Depends(get_db),
):
    profile = db.get(TutorProfile, tutor_id)
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Tutor profile not found."
        )
    if not profile.is_visible or profile.approval_status != TutorStatus.APPROVED:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="This tutor profile is not available."
        )

    start = from_date or date.today()
    result: List[Dict[str, Any]] = []
    for offset in range(days):
        target = start + timedelta(days=offset)
        result.append(
            {
                "date": target.isoformat(),
                "day_of_week": DAYS_OF_WEEK[target.weekday()],
                "is_today": target == date.today(),
                "is_past": target < date.today(),
                "slots": open_slots_for_date(db, profile, target),
            }
        )
    return {
        "tutor_id": tutor_id,
        "tutor_name": profile.user.full_name,
        "session_duration_minutes": profile.session_duration_minutes,
        "hourly_rate": float(profile.hourly_rate),
        "range_days": days,
        "days": result,
        "total_open_slots": sum(len(day["slots"]) for day in result),
    }


# --------------------------------------------------------------------------- #
# CREATE
# --------------------------------------------------------------------------- #
@router.post(
    "/availability",
    status_code=status.HTTP_201_CREATED,
    summary="Add a weekly availability slot",
)
def create_availability(
    payload: AvailabilityCreate,
    tutor_id: Optional[int] = Query(None, description="Admin only: target tutor"),
    current_user: User = Depends(require_roles(UserRole.TUTOR, UserRole.ADMIN)),
    db: Session = Depends(get_db),
):
    profile = _resolve_tutor_profile(db, current_user, tutor_id)
    if not _can_write(current_user, profile):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your profile.")

    clash = find_overlapping_slot(
        db, profile.id, payload.day_of_week, payload.start_time, payload.end_time
    )
    if clash is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"That overlaps your existing slot: {clash.slot_label()}. "
                "Adjust the times or delete the old slot first."
            ),
        )

    slot = Availability(
        tutor_profile_id=profile.id,
        day_of_week=payload.day_of_week,
        day_index=DAY_INDEX[payload.day_of_week],
        start_time=payload.start_time,
        end_time=payload.end_time,
        mode=payload.mode,
        is_active=payload.is_active,
    )
    db.add(slot)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An identical availability slot already exists.",
        ) from exc
    db.refresh(slot)

    log_activity(
        db,
        ActivityAction.AVAILABILITY_ADDED,
        f"{profile.user.full_name} added availability: {slot.slot_label()}",
        actor_user_id=current_user.id,
        entity_type="availability",
        entity_id=slot.id,
    )
    db.commit()
    return {"detail": f"Availability added: {slot.slot_label()}.", "data": availability_out(slot)}


@router.post(
    "/availability/exceptions",
    status_code=status.HTTP_201_CREATED,
    summary="Block or open a specific date",
)
def create_exception(
    payload: AvailabilityExceptionCreate,
    tutor_id: Optional[int] = Query(None),
    current_user: User = Depends(require_roles(UserRole.TUTOR, UserRole.ADMIN)),
    db: Session = Depends(get_db),
):
    profile = _resolve_tutor_profile(db, current_user, tutor_id)
    if not _can_write(current_user, profile):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your profile.")
    if payload.date < date.today():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="That date is in the past."
        )

    existing = db.scalar(
        select(AvailabilityException).where(
            AvailabilityException.tutor_profile_id == profile.id,
            AvailabilityException.date == payload.date,
            AvailabilityException.is_blocked == payload.is_blocked,
        )
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That date is already saved with the same setting.",
        )

    exc = AvailabilityException(
        tutor_profile_id=profile.id,
        date=payload.date,
        is_blocked=payload.is_blocked,
        reason=payload.reason,
    )
    db.add(exc)
    db.commit()
    db.refresh(exc)
    return {
        "detail": (
            f"{exc.date.strftime('%a, %d %b %Y')} marked as "
            f"{'unavailable' if exc.is_blocked else 'open'}."
        ),
        "data": {
            "id": exc.id,
            "date": exc.date.isoformat(),
            "is_blocked": exc.is_blocked,
            "reason": exc.reason,
        },
    }


# --------------------------------------------------------------------------- #
# UPDATE
# --------------------------------------------------------------------------- #
@router.put("/availability/{slot_id}", summary="Update an availability slot")
def update_availability(
    slot_id: int,
    payload: AvailabilityUpdate,
    current_user: User = Depends(require_roles(UserRole.TUTOR, UserRole.ADMIN)),
    db: Session = Depends(get_db),
):
    slot = db.get(Availability, slot_id)
    if slot is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Availability slot #{slot_id} not found."
        )
    profile = db.get(TutorProfile, slot.tutor_profile_id)
    if profile is None or not _can_write(current_user, profile):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your profile.")

    data = payload.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="No fields were provided to update."
        )

    new_day = data.get("day_of_week", slot.day_of_week)
    new_start = data.get("start_time", slot.start_time)
    new_end = data.get("end_time", slot.end_time)

    if new_end <= new_start:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="End time must be later than start time."
        )

    clash = find_overlapping_slot(
        db, profile.id, new_day, new_start, new_end, exclude_id=slot.id
    )
    if clash is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"That would overlap your existing slot: {clash.slot_label()}.",
        )

    slot.day_of_week = new_day
    slot.day_index = DAY_INDEX[new_day]
    slot.start_time = new_start
    slot.end_time = new_end
    if "mode" in data and data["mode"] is not None:
        slot.mode = TeachingMode(data["mode"]) if not isinstance(data["mode"], TeachingMode) else data["mode"]
    if "is_active" in data and data["is_active"] is not None:
        slot.is_active = bool(data["is_active"])

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An identical availability slot already exists.",
        ) from exc
    db.refresh(slot)
    return {"detail": f"Availability updated: {slot.slot_label()}.", "data": availability_out(slot)}


@router.patch("/availability/{slot_id}/toggle", summary="Enable/disable a slot")
def toggle_availability(
    slot_id: int,
    current_user: User = Depends(require_roles(UserRole.TUTOR, UserRole.ADMIN)),
    db: Session = Depends(get_db),
):
    slot = db.get(Availability, slot_id)
    if slot is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Availability slot not found."
        )
    profile = db.get(TutorProfile, slot.tutor_profile_id)
    if profile is None or not _can_write(current_user, profile):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your profile.")

    slot.is_active = not slot.is_active
    db.commit()
    db.refresh(slot)
    state = "enabled" if slot.is_active else "paused"
    return {"detail": f"{slot.slot_label()} {state}.", "data": availability_out(slot)}


# --------------------------------------------------------------------------- #
# DELETE
# --------------------------------------------------------------------------- #
@router.delete("/availability/{slot_id}", response_model=Message, summary="Delete an availability slot")
def delete_availability(
    slot_id: int,
    current_user: User = Depends(require_roles(UserRole.TUTOR, UserRole.ADMIN)),
    db: Session = Depends(get_db),
):
    slot = db.get(Availability, slot_id)
    if slot is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Availability slot #{slot_id} not found."
        )
    profile = db.get(TutorProfile, slot.tutor_profile_id)
    if profile is None or not _can_write(current_user, profile):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your profile.")

    upcoming = (
        db.execute(
            select(BookingRequest.id).where(
                BookingRequest.tutor_profile_id == profile.id,
                BookingRequest.status == RequestStatus.ACCEPTED,
                BookingRequest.preferred_date >= date.today(),
            )
        ).first()
        is not None
    )
    label = slot.slot_label()
    log_activity(
        db,
        ActivityAction.AVAILABILITY_REMOVED,
        f"{profile.user.full_name} removed availability: {label}",
        actor_user_id=current_user.id,
        entity_type="availability",
        entity_id=slot.id,
    )
    db.delete(slot)
    db.commit()
    detail = f"Availability deleted: {label}."
    if upcoming:
        detail += " Existing accepted bookings were left untouched."
    return {"detail": detail}


@router.delete("/availability/exceptions/{exception_id}", response_model=Message)
def delete_exception(
    exception_id: int,
    current_user: User = Depends(require_roles(UserRole.TUTOR, UserRole.ADMIN)),
    db: Session = Depends(get_db),
):
    exc = db.get(AvailabilityException, exception_id)
    if exc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Date override not found.")
    profile = db.get(TutorProfile, exc.tutor_profile_id)
    if profile is None or not _can_write(current_user, profile):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your profile.")

    when = exc.date.strftime("%a, %d %b %Y")
    db.delete(exc)
    db.commit()
    return {"detail": f"Override for {when} removed."}
