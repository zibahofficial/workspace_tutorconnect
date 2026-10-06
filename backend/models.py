"""
ORM models — the relational data layer of TutorConnect.

Entities:
    User              - single table for every role (tutor / student / admin)
    TutorProfile      - 1:1 with a tutor User
    StudentProfile    - 1:1 with a student/parent User
    Subject           - controlled vocabulary of subjects
    TutorSubject      - N:M join (tutor <-> subject) with a proficiency level
    Availability      - recurring weekly time slots owned by a tutor
    AvailabilityException - one-off overrides (blocked/open) for a specific date
    BookingRequest    - the request/booking lifecycle between student and tutor
    Review            - 1-5 star review written after a completed booking
    Favorite          - student "saved tutors"
    Notification      - in-app notifications (request accepted, new review, ...)
    ActivityLog       - audit trail powering the admin activity feed
"""
from __future__ import annotations

import enum
from datetime import date, datetime, time, timezone
from typing import List, Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Select,
    String,
    Text,
    Time,
    UniqueConstraint,
    func,
    select,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


# --------------------------------------------------------------------------- #
# Enumerations
# --------------------------------------------------------------------------- #
class UserRole(str, enum.Enum):
    TUTOR = "tutor"
    STUDENT = "student"
    ADMIN = "admin"


class TeachingMode(str, enum.Enum):
    IN_PERSON = "in_person"
    ONLINE = "online"
    HYBRID = "hybrid"


class TutorStatus(str, enum.Enum):
    PENDING = "pending"      # awaiting admin approval
    APPROVED = "approved"    # discoverable in search
    SUSPENDED = "suspended"  # hidden by an administrator


class RequestStatus(str, enum.Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    COMPLETED = "completed"


class NotificationType(str, enum.Enum):
    REQUEST_NEW = "request_new"
    REQUEST_ACCEPTED = "request_accepted"
    REQUEST_REJECTED = "request_rejected"
    REQUEST_CANCELLED = "request_cancelled"
    REQUEST_COMPLETED = "request_completed"
    REVIEW_NEW = "review_new"
    PROFILE_APPROVED = "profile_approved"
    PROFILE_SUSPENDED = "profile_suspended"
    ACCOUNT = "account"


class ActivityAction(str, enum.Enum):
    USER_REGISTERED = "user_registered"
    TUTOR_PROFILE_CREATED = "tutor_profile_created"
    TUTOR_PROFILE_UPDATED = "tutor_profile_updated"
    TUTOR_APPROVED = "tutor_approved"
    TUTOR_SUSPENDED = "tutor_suspended"
    AVAILABILITY_ADDED = "availability_added"
    AVAILABILITY_REMOVED = "availability_removed"
    REQUEST_CREATED = "request_created"
    REQUEST_ACCEPTED = "request_accepted"
    REQUEST_REJECTED = "request_rejected"
    REQUEST_CANCELLED = "request_cancelled"
    REQUEST_COMPLETED = "request_completed"
    REVIEW_CREATED = "review_created"
    REVIEW_DELETED = "review_deleted"
    USER_DEACTIVATED = "user_deactivated"
    USER_ACTIVATED = "user_activated"


DAYS_OF_WEEK: List[str] = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
]
DAY_INDEX = {name: idx for idx, name in enumerate(DAYS_OF_WEEK)}


# --------------------------------------------------------------------------- #
# Timestamp mixin
# --------------------------------------------------------------------------- #
class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- #
# Users & profiles
# --------------------------------------------------------------------------- #
class User(Base, TimestampMixin):
    """One account table; `role` decides which dashboard & permissions apply."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    phone: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    avatar_url: Mapped[Optional[str]] = mapped_column(String(600), nullable=True)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, native_enum=False, length=20), nullable=False, index=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # relationships
    tutor_profile: Mapped[Optional["TutorProfile"]] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    student_profile: Mapped[Optional["StudentProfile"]] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    notifications: Mapped[List["Notification"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint("length(full_name) >= 2", name="ck_users_full_name_length"),
        Index("ix_users_role_active", "role", "is_active"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<User {self.id} {self.email} ({self.role.value})>"


class TutorProfile(Base, TimestampMixin):
    """Public tutor profile: everything a student sees on the tutor page."""

    __tablename__ = "tutor_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False, index=True
    )

    headline: Mapped[str] = mapped_column(String(160), nullable=False)
    bio: Mapped[str] = mapped_column(Text, nullable=False)
    years_experience: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    hourly_rate: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    session_duration_minutes: Mapped[int] = mapped_column(Integer, default=60, nullable=False)

    city: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    state: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    country: Mapped[str] = mapped_column(String(80), default="Nigeria", nullable=False)

    teaching_mode: Mapped[TeachingMode] = mapped_column(
        Enum(TeachingMode, native_enum=False, length=20), default=TeachingMode.HYBRID, nullable=False
    )
    qualifications: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    languages: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    cover_image_url: Mapped[Optional[str]] = mapped_column(String(600), nullable=True)

    accepts_online: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    accepts_in_person: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_visible: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    approval_status: Mapped[TutorStatus] = mapped_column(
        Enum(TutorStatus, native_enum=False, length=20),
        default=TutorStatus.APPROVED,
        nullable=False,
        index=True,
    )
    verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # relationships
    user: Mapped[User] = relationship(back_populates="tutor_profile")
    tutor_subjects: Mapped[List["TutorSubject"]] = relationship(
        back_populates="tutor_profile", cascade="all, delete-orphan", lazy="selectin"
    )
    availability: Mapped[List["Availability"]] = relationship(
        back_populates="tutor_profile", cascade="all, delete-orphan", lazy="selectin",
        order_by="Availability.day_index, Availability.start_time",
    )
    exceptions: Mapped[List["AvailabilityException"]] = relationship(
        back_populates="tutor_profile", cascade="all, delete-orphan"
    )
    booking_requests: Mapped[List["BookingRequest"]] = relationship(
        back_populates="tutor_profile", cascade="all, delete-orphan"
    )
    reviews: Mapped[List["Review"]] = relationship(
        back_populates="tutor_profile", cascade="all, delete-orphan"
    )
    favorites: Mapped[List["Favorite"]] = relationship(
        back_populates="tutor_profile", cascade="all, delete-orphan"
    )

    # ---- derived aggregates (always computed from real review rows) ----
    @property
    def rating_subquery(self) -> Select:
        return select(func.avg(Review.rating)).where(
            Review.tutor_profile_id == self.id, Review.is_deleted.is_(False)
        ).scalar_subquery()

    __table_args__ = (
        CheckConstraint("hourly_rate >= 0", name="ck_tutor_rate_non_negative"),
        CheckConstraint("years_experience >= 0", name="ck_tutor_experience_non_negative"),
        CheckConstraint("years_experience <= 70", name="ck_tutor_experience_max"),
        CheckConstraint("session_duration_minutes >= 15", name="ck_tutor_session_min"),
        CheckConstraint("session_duration_minutes <= 480", name="ck_tutor_session_max"),
        CheckConstraint("length(bio) >= 20", name="ck_tutor_bio_min_length"),
        Index("ix_tutor_location", "city", "state"),
    )


class StudentProfile(Base, TimestampMixin):
    """Student / parent profile."""

    __tablename__ = "student_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False, index=True
    )
    education_level: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    guardian_name: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    city: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    state: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    learning_goals: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    preferred_mode: Mapped[Optional[TeachingMode]] = mapped_column(
        Enum(TeachingMode, native_enum=False, length=20), nullable=True
    )
    max_budget: Mapped[Optional[float]] = mapped_column(Numeric(10, 2), nullable=True)

    user: Mapped[User] = relationship(back_populates="student_profile")
    booking_requests: Mapped[List["BookingRequest"]] = relationship(
        back_populates="student_profile", cascade="all, delete-orphan"
    )
    reviews: Mapped[List["Review"]] = relationship(
        back_populates="student_profile", cascade="all, delete-orphan"
    )
    favorites: Mapped[List["Favorite"]] = relationship(
        back_populates="student_profile", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint(
            "max_budget IS NULL OR max_budget >= 0", name="ck_student_budget_non_negative"
        ),
    )


# --------------------------------------------------------------------------- #
# Subjects
# --------------------------------------------------------------------------- #
class Subject(Base, TimestampMixin):
    __tablename__ = "subjects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False, index=True)
    category: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    icon: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    tutor_subjects: Mapped[List["TutorSubject"]] = relationship(
        back_populates="subject", cascade="all, delete-orphan"
    )


class TutorSubject(Base, TimestampMixin):
    __tablename__ = "tutor_subjects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tutor_profile_id: Mapped[int] = mapped_column(
        ForeignKey("tutor_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    subject_id: Mapped[int] = mapped_column(
        ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    proficiency: Mapped[str] = mapped_column(String(40), default="Advanced", nullable=False)
    levels: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    tutor_profile: Mapped[TutorProfile] = relationship(back_populates="tutor_subjects")
    subject: Mapped[Subject] = relationship(back_populates="tutor_subjects", lazy="joined")

    __table_args__ = (
        UniqueConstraint("tutor_profile_id", "subject_id", name="uq_tutor_subject"),
    )


# --------------------------------------------------------------------------- #
# Availability
# --------------------------------------------------------------------------- #
class Availability(Base, TimestampMixin):
    """A recurring weekly window, e.g. Monday 16:00-19:00."""

    __tablename__ = "availability"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tutor_profile_id: Mapped[int] = mapped_column(
        ForeignKey("tutor_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    day_of_week: Mapped[str] = mapped_column(String(10), nullable=False)
    day_index: Mapped[int] = mapped_column(Integer, nullable=False)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)
    mode: Mapped[TeachingMode] = mapped_column(
        Enum(TeachingMode, native_enum=False, length=20), default=TeachingMode.HYBRID, nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    tutor_profile: Mapped[TutorProfile] = relationship(back_populates="availability")

    __table_args__ = (
        UniqueConstraint(
            "tutor_profile_id", "day_of_week", "start_time", "end_time",
            name="uq_availability_slot",
        ),
        CheckConstraint("day_index >= 0 AND day_index <= 6", name="ck_availability_day_index"),
        CheckConstraint("end_time > start_time", name="ck_availability_time_order"),
        Index("ix_availability_day", "day_index", "is_active"),
    )

    def slot_label(self) -> str:
        return f"{self.day_of_week} {fmt_time(self.start_time)} - {fmt_time(self.end_time)}"

    def contains(self, when: datetime, duration_minutes: int = 60) -> bool:
        """True when a session of `duration_minutes` starting at `when` fits this slot."""
        if DAYS_OF_WEEK[when.weekday()] != self.day_of_week:
            return False
        start_minutes = when.hour * 60 + when.minute
        end_minutes = start_minutes + duration_minutes
        slot_start = self.start_time.hour * 60 + self.start_time.minute
        slot_end = self.end_time.hour * 60 + self.end_time.minute
        return slot_start <= start_minutes and end_minutes <= slot_end


class AvailabilityException(Base, TimestampMixin):
    """One-off override for a specific calendar date (tutor unavailable / extra open)."""

    __tablename__ = "availability_exceptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tutor_profile_id: Mapped[int] = mapped_column(
        ForeignKey("tutor_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    tutor_profile: Mapped[TutorProfile] = relationship(back_populates="exceptions")

    __table_args__ = (
        UniqueConstraint(
            "tutor_profile_id", "date", "is_blocked", name="uq_availability_exception"
        ),
    )


# --------------------------------------------------------------------------- #
# Booking requests
# --------------------------------------------------------------------------- #
class BookingRequest(Base, TimestampMixin):
    __tablename__ = "booking_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tutor_profile_id: Mapped[int] = mapped_column(
        ForeignKey("tutor_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    student_id: Mapped[int] = mapped_column(
        ForeignKey("student_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    subject_id: Mapped[int] = mapped_column(
        ForeignKey("subjects.id", ondelete="RESTRICT"), nullable=False, index=True
    )

    status: Mapped[RequestStatus] = mapped_column(
        Enum(RequestStatus, native_enum=False, length=20),
        default=RequestStatus.PENDING,
        nullable=False,
        index=True,
    )

    preferred_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    preferred_time: Mapped[time] = mapped_column(Time, nullable=False)
    duration_minutes: Mapped[int] = mapped_column(Integer, default=60, nullable=False)
    mode: Mapped[TeachingMode] = mapped_column(
        Enum(TeachingMode, native_enum=False, length=20), default=TeachingMode.HYBRID, nullable=False
    )
    budget: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    location_note: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    tutor_response_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    responded_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    cancel_reason: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    read_by_student: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    read_by_tutor: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    tutor_profile: Mapped[TutorProfile] = relationship(
        back_populates="booking_requests", lazy="joined"
    )
    student_profile: Mapped[StudentProfile] = relationship(
        back_populates="booking_requests", lazy="joined"
    )
    subject: Mapped[Subject] = relationship(lazy="joined")
    review: Mapped[Optional["Review"]] = relationship(
        back_populates="booking_request", uselist=False, cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint("budget >= 0", name="ck_request_budget_non_negative"),
        CheckConstraint("duration_minutes >= 15", name="ck_request_duration_min"),
        CheckConstraint("duration_minutes <= 480", name="ck_request_duration_max"),
        Index("ix_request_tutor_status", "tutor_profile_id", "status"),
        Index("ix_request_student_status", "student_id", "status"),
        UniqueConstraint(
            "tutor_profile_id", "student_id", "subject_id", "preferred_date", "preferred_time",
            name="uq_request_slot",
        ),
    )

    def session_start(self) -> datetime:
        return datetime.combine(self.preferred_date, self.preferred_time, tzinfo=timezone.utc)


# --------------------------------------------------------------------------- #
# Reviews
# --------------------------------------------------------------------------- #
class Review(Base, TimestampMixin):
    __tablename__ = "reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tutor_profile_id: Mapped[int] = mapped_column(
        ForeignKey("tutor_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    student_id: Mapped[int] = mapped_column(
        ForeignKey("student_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    booking_request_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("booking_requests.id", ondelete="SET NULL"), unique=True, nullable=True
    )
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[Optional[str]] = mapped_column(String(160), nullable=True)
    comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    deleted_reason: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    tutor_profile: Mapped[TutorProfile] = relationship(back_populates="reviews")
    student_profile: Mapped[StudentProfile] = relationship(
        back_populates="reviews", lazy="joined"
    )
    booking_request: Mapped[Optional[BookingRequest]] = relationship(back_populates="review")

    __table_args__ = (
        CheckConstraint("rating >= 1 AND rating <= 5", name="ck_review_rating_range"),
        CheckConstraint("length(comment) <= 2000", name="ck_review_comment_max"),
    )


# --------------------------------------------------------------------------- #
# Favorites, notifications, activity
# --------------------------------------------------------------------------- #
class Favorite(Base, TimestampMixin):
    __tablename__ = "favorites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    student_id: Mapped[int] = mapped_column(
        ForeignKey("student_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tutor_profile_id: Mapped[int] = mapped_column(
        ForeignKey("tutor_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )

    student_profile: Mapped[StudentProfile] = relationship(back_populates="favorites")
    tutor_profile: Mapped[TutorProfile] = relationship(back_populates="favorites", lazy="joined")

    __table_args__ = (UniqueConstraint("student_id", "tutor_profile_id", name="uq_favorite"),)


class Notification(Base, TimestampMixin):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    type: Mapped[NotificationType] = mapped_column(
        Enum(NotificationType, native_enum=False, length=30), nullable=False
    )
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    body: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    link: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)

    user: Mapped[User] = relationship(back_populates="notifications")


class ActivityLog(Base):
    __tablename__ = "activity_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    action: Mapped[ActivityAction] = mapped_column(
        Enum(ActivityAction, native_enum=False, length=40), nullable=False, index=True
    )
    description: Mapped[str] = mapped_column(String(400), nullable=False)
    entity_type: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    entity_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    actor: Mapped[Optional[User]] = relationship()


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #
def fmt_time(value: time) -> str:
    """16:30 -> 4:30 PM"""
    return value.strftime("%I:%M %p").lstrip("0")


def average_rating_select() -> Select:
    """Reusable aggregate used by the tutor search query."""
    return (
        select(
            func.coalesce(func.avg(Review.rating), 0).label("avg_rating"),
            func.count(Review.id).label("review_count"),
        )
        .where(Review.is_deleted.is_(False))
        .group_by(Review.tutor_profile_id)
    )
