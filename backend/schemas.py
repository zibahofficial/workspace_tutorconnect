"""
Pydantic schemas — request/response validation for the REST API.

All user input passes through these models first, so bad data never reaches the
database.  Friendly, human-readable error messages are produced by the global
validation handler in `main.py`.
"""
from __future__ import annotations

import re
from datetime import date, datetime, time
from typing import Any, Generic, List, Literal, Optional, TypeVar

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    field_validator,
    model_validator,
)

from models import DAYS_OF_WEEK, RequestStatus, TeachingMode, TutorStatus, UserRole

ORM = ConfigDict(from_attributes=True)

T = TypeVar("T")


# --------------------------------------------------------------------------- #
# Generic helpers
# --------------------------------------------------------------------------- #
class Paginated(BaseModel, Generic[T]):
    items: List[T]
    total: int
    page: int
    page_size: int
    pages: int


class Message(BaseModel):
    detail: str
    data: Optional[Any] = None


# --------------------------------------------------------------------------- #
# Validation helpers
# --------------------------------------------------------------------------- #
PASSWORD_LETTER = re.compile(r"[A-Za-z]")
PASSWORD_DIGIT = re.compile(r"\d")

# Rejected outright, even when they satisfy the length/character rules.
COMMON_PASSWORDS = {
    "password", "password1", "password123", "passw0rd", "12345678", "123456789",
    "1234567890", "qwerty123", "qwertyui", "abc12345", "11111111", "00000000",
    "iloveyou", "letmein1", "welcome1", "admin123", "tutorconnect", "tutorconnect123",
}


def validate_password_strength(value: str) -> str:
    if len(value) < 8:
        raise ValueError("Password must be at least 8 characters long.")
    if len(value) > 128:
        raise ValueError("Password must be at most 128 characters long.")
    if value.lower() in COMMON_PASSWORDS:
        raise ValueError("That password is too common. Please choose a stronger one.")
    if not PASSWORD_LETTER.search(value):
        raise ValueError("Password must contain at least one letter.")
    if not PASSWORD_DIGIT.search(value):
        raise ValueError("Password must contain at least one number.")
    return value


def validate_slot(day: str, start: time, end: time) -> None:
    if day not in DAYS_OF_WEEK:
        raise ValueError(f"day_of_week must be one of: {', '.join(DAYS_OF_WEEK)}")
    if end <= start:
        raise ValueError("End time must be later than start time.")
    if (end.hour * 60 + end.minute) - (start.hour * 60 + start.minute) < 30:
        raise ValueError("A session slot must be at least 30 minutes long.")


# --------------------------------------------------------------------------- #
# Auth
# --------------------------------------------------------------------------- #
class RegisterRequest(BaseModel):
    full_name: str = Field(min_length=2, max_length=120, examples=["Amaka Obi"])
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    role: Literal["tutor", "student"] = Field(description="Account type")
    phone: Optional[str] = Field(default=None, max_length=30)
    avatar_url: Optional[str] = Field(default=None, max_length=600)

    # student fields
    city: Optional[str] = Field(default=None, max_length=120)
    state: Optional[str] = Field(default=None, max_length=120)
    education_level: Optional[str] = Field(default=None, max_length=80)
    guardian_name: Optional[str] = Field(default=None, max_length=120)

    # tutor fields
    headline: Optional[str] = Field(default=None, max_length=160)
    bio: Optional[str] = Field(default=None, max_length=4000)
    years_experience: Optional[int] = Field(default=None, ge=0, le=70)
    hourly_rate: Optional[float] = Field(default=None, ge=0, le=5_000_000)
    teaching_mode: Optional[TeachingMode] = None
    subject_ids: Optional[List[int]] = None

    @field_validator("password")
    @classmethod
    def _password(cls, v: str) -> str:
        return validate_password_strength(v)

    @field_validator("full_name", "city", "state", "headline", "guardian_name")
    @classmethod
    def _strip(cls, v: Optional[str]) -> Optional[str]:
        return v.strip() if isinstance(v, str) else v

    @model_validator(mode="after")
    def _role_specific(self) -> "RegisterRequest":
        if self.role == UserRole.TUTOR.value:
            missing = [
                name
                for name, value in (
                    ("headline", self.headline),
                    ("bio", self.bio),
                    ("city", self.city),
                    ("state", self.state),
                    ("hourly_rate", self.hourly_rate),
                )
                if value in (None, "")
            ]
            if missing:
                raise ValueError(
                    "Tutor registration requires: " + ", ".join(missing)
                )
            if self.bio and len(self.bio.strip()) < 40:
                raise ValueError("Please write a bio of at least 40 characters.")
            if not self.subject_ids:
                raise ValueError("Please select at least one subject you teach.")
            if self.years_experience is None:
                raise ValueError("years_experience is required for tutor registration.")
        return self


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in_minutes: int
    user: "UserOut"


class AvatarUploadRequest(BaseModel):
    """A profile photo read from the user's own device (data URL or raw base64)."""

    image: str = Field(
        min_length=16,
        description="Base64-encoded image, optionally wrapped in a data: URL. "
        "PNG, JPG, GIF or WebP, up to 3 MB once decoded.",
    )


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)

    @field_validator("new_password")
    @classmethod
    def _password(cls, v: str) -> str:
        return validate_password_strength(v)

    @model_validator(mode="after")
    def _different(self) -> "ChangePasswordRequest":
        if self.current_password == self.new_password:
            raise ValueError("New password must be different from the current password.")
        return self


# --------------------------------------------------------------------------- #
# Users
# --------------------------------------------------------------------------- #
class UserOut(BaseModel):
    model_config = ORM

    id: int
    email: EmailStr
    full_name: str
    phone: Optional[str] = None
    avatar_url: Optional[str] = None
    role: UserRole
    is_active: bool
    last_login_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    tutor_profile_id: Optional[int] = None
    student_profile_id: Optional[int] = None


class UserUpdate(BaseModel):
    full_name: Optional[str] = Field(default=None, min_length=2, max_length=120)
    phone: Optional[str] = Field(default=None, max_length=30)
    avatar_url: Optional[str] = Field(default=None, max_length=600)


class AdminUserUpdate(BaseModel):
    full_name: Optional[str] = Field(default=None, min_length=2, max_length=120)
    phone: Optional[str] = Field(default=None, max_length=30)
    role: Optional[UserRole] = None
    is_active: Optional[bool] = None


# --------------------------------------------------------------------------- #
# Subjects
# --------------------------------------------------------------------------- #
class SubjectOut(BaseModel):
    model_config = ORM

    id: int
    name: str
    category: Optional[str] = None
    icon: Optional[str] = None
    tutor_count: int = 0


class SubjectCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    category: Optional[str] = Field(default=None, max_length=80)
    icon: Optional[str] = Field(default=None, max_length=40)


# --------------------------------------------------------------------------- #
# Tutor subjects
# --------------------------------------------------------------------------- #
class TutorSubjectOut(BaseModel):
    model_config = ORM

    id: int
    subject_id: int
    subject_name: str = ""
    proficiency: str = "Advanced"
    levels: Optional[str] = None


class TutorSubjectCreate(BaseModel):
    subject_id: int
    proficiency: str = Field(default="Advanced", max_length=40)
    levels: Optional[str] = Field(default=None, max_length=255)


# --------------------------------------------------------------------------- #
# Availability
# --------------------------------------------------------------------------- #
class AvailabilityBase(BaseModel):
    day_of_week: Literal[
        "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"
    ]
    start_time: time
    end_time: time
    mode: TeachingMode = TeachingMode.HYBRID
    is_active: bool = True


class AvailabilityCreate(AvailabilityBase):
    @model_validator(mode="after")
    def _check(self) -> "AvailabilityCreate":
        validate_slot(self.day_of_week, self.start_time, self.end_time)
        return self


class AvailabilityUpdate(BaseModel):
    day_of_week: Optional[
        Literal["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    ] = None
    start_time: Optional[time] = None
    end_time: Optional[time] = None
    mode: Optional[TeachingMode] = None
    is_active: Optional[bool] = None

    @model_validator(mode="after")
    def _check(self) -> "AvailabilityUpdate":
        if self.start_time and self.end_time:
            validate_slot(self.day_of_week or "Monday", self.start_time, self.end_time)
        return self


class AvailabilityOut(AvailabilityBase):
    model_config = ORM

    id: int
    tutor_profile_id: int
    day_index: int
    label: str = ""
    created_at: Optional[datetime] = None


class AvailabilityExceptionCreate(BaseModel):
    date: date
    is_blocked: bool = True
    reason: Optional[str] = Field(default=None, max_length=255)


class AvailabilityExceptionOut(BaseModel):
    model_config = ORM

    id: int
    date: date
    is_blocked: bool
    reason: Optional[str] = None


# --------------------------------------------------------------------------- #
# Tutor profiles
# --------------------------------------------------------------------------- #
class TutorProfileBase(BaseModel):
    headline: str = Field(min_length=5, max_length=160)
    bio: str = Field(min_length=40, max_length=4000)
    years_experience: int = Field(ge=0, le=70)
    hourly_rate: float = Field(ge=0, le=5_000_000)
    session_duration_minutes: int = Field(default=60, ge=15, le=480)
    city: str = Field(min_length=2, max_length=120)
    state: str = Field(min_length=2, max_length=120)
    country: str = Field(default="Nigeria", max_length=80)
    teaching_mode: TeachingMode = TeachingMode.HYBRID
    qualifications: Optional[str] = Field(default=None, max_length=2000)
    languages: Optional[str] = Field(default=None, max_length=255)
    cover_image_url: Optional[str] = Field(default=None, max_length=600)
    accepts_online: bool = True
    accepts_in_person: bool = True
    is_visible: bool = True


class TutorProfileCreate(TutorProfileBase):
    subject_ids: List[int] = Field(min_length=1, description="Subjects this tutor teaches")


class TutorProfileUpdate(BaseModel):
    headline: Optional[str] = Field(default=None, min_length=5, max_length=160)
    bio: Optional[str] = Field(default=None, min_length=40, max_length=4000)
    years_experience: Optional[int] = Field(default=None, ge=0, le=70)
    hourly_rate: Optional[float] = Field(default=None, ge=0, le=5_000_000)
    session_duration_minutes: Optional[int] = Field(default=None, ge=15, le=480)
    city: Optional[str] = Field(default=None, min_length=2, max_length=120)
    state: Optional[str] = Field(default=None, min_length=2, max_length=120)
    country: Optional[str] = Field(default=None, max_length=80)
    teaching_mode: Optional[TeachingMode] = None
    qualifications: Optional[str] = Field(default=None, max_length=2000)
    languages: Optional[str] = Field(default=None, max_length=255)
    cover_image_url: Optional[str] = Field(default=None, max_length=600)
    avatar_url: Optional[str] = Field(default=None, max_length=600)
    accepts_online: Optional[bool] = None
    accepts_in_person: Optional[bool] = None
    is_visible: Optional[bool] = None
    subject_ids: Optional[List[int]] = None

    @model_validator(mode="after")
    def _at_least_one_mode(self) -> "TutorProfileUpdate":
        if self.accepts_online is False and self.accepts_in_person is False:
            raise ValueError("A tutor must accept online or in-person sessions.")
        return self


class TutorApprovalUpdate(BaseModel):
    approval_status: TutorStatus
    verified: Optional[bool] = None
    reason: Optional[str] = Field(default=None, max_length=255)


class TutorSubjectLite(BaseModel):
    id: int
    name: str
    category: Optional[str] = None
    icon: Optional[str] = None
    proficiency: str = "Advanced"
    levels: Optional[str] = None


class ReviewOut(BaseModel):
    model_config = ORM

    id: int
    rating: int
    title: Optional[str] = None
    comment: Optional[str] = None
    created_at: Optional[datetime] = None
    booking_request_id: Optional[int] = None
    is_deleted: bool = False
    student_name: str = ""
    student_avatar_url: Optional[str] = None
    subject_name: Optional[str] = None


class TutorSummary(BaseModel):
    """Card-shaped payload used by search & listings."""

    id: int
    user_id: int
    full_name: str
    avatar_url: Optional[str] = None
    headline: str
    bio: str
    short_bio: str
    years_experience: int
    hourly_rate: float
    session_duration_minutes: int
    city: str
    state: str
    country: str
    teaching_mode: TeachingMode
    qualifications: Optional[str] = None
    languages: Optional[str] = None
    cover_image_url: Optional[str] = None
    accepts_online: bool
    accepts_in_person: bool
    verified: bool
    approval_status: TutorStatus
    rating: float
    review_count: int
    subjects: List[TutorSubjectLite]
    availability: List[AvailabilityOut]
    completed_sessions: int = 0
    response_time_hours: Optional[float] = None
    match_score: Optional[int] = None
    is_favorite: bool = False


class RatingBreakdown(BaseModel):
    star: int
    count: int
    percentage: float


class TutorDetail(TutorSummary):
    email: Optional[str] = None
    phone: Optional[str] = None
    reviews: List[ReviewOut] = []
    rating_breakdown: List[RatingBreakdown] = []
    exceptions: List[AvailabilityExceptionOut] = []
    total_students: int = 0
    created_at: Optional[datetime] = None
    profile_completion: int = 0


class TutorDashboardStats(BaseModel):
    profile_completion: int
    total_requests: int
    pending_requests: int
    accepted_requests: int
    rejected_requests: int
    cancelled_requests: int
    completed_sessions: int
    upcoming_sessions: int
    rating: float
    review_count: int
    weekly_slots: int
    total_earnings: float
    favorites: int


# --------------------------------------------------------------------------- #
# Student profile
# --------------------------------------------------------------------------- #
class StudentProfileUpdate(BaseModel):
    education_level: Optional[str] = Field(default=None, max_length=80)
    guardian_name: Optional[str] = Field(default=None, max_length=120)
    city: Optional[str] = Field(default=None, max_length=120)
    state: Optional[str] = Field(default=None, max_length=120)
    learning_goals: Optional[str] = Field(default=None, max_length=2000)
    preferred_mode: Optional[TeachingMode] = None
    max_budget: Optional[float] = Field(default=None, ge=0, le=5_000_000)
    avatar_url: Optional[str] = Field(default=None, max_length=600)


class StudentProfileOut(BaseModel):
    model_config = ORM

    id: int
    user_id: int
    education_level: Optional[str] = None
    guardian_name: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    learning_goals: Optional[str] = None
    preferred_mode: Optional[TeachingMode] = None
    max_budget: Optional[float] = None


# --------------------------------------------------------------------------- #
# Booking requests
# --------------------------------------------------------------------------- #
class BookingRequestCreate(BaseModel):
    tutor_id: int = Field(description="Tutor profile id")
    subject_id: int
    preferred_date: date
    preferred_time: time
    duration_minutes: int = Field(default=60, ge=15, le=480)
    mode: TeachingMode = TeachingMode.HYBRID
    budget: float = Field(ge=0, le=5_000_000)
    message: Optional[str] = Field(default=None, max_length=1500)
    location_note: Optional[str] = Field(default=None, max_length=255)
    ignore_availability: bool = Field(
        default=False, description="Allow requesting a time outside listed availability"
    )

    @model_validator(mode="after")
    def _sane(self) -> "BookingRequestCreate":
        if self.preferred_date < date.today():
            raise ValueError("preferred_date cannot be in the past.")
        if self.preferred_time.minute not in (0, 15, 30, 45):
            raise ValueError("Please choose a start time on a 15-minute mark.")
        return self


class BookingRequestUpdate(BaseModel):
    """Student edit of a still-pending request."""

    preferred_date: Optional[date] = None
    preferred_time: Optional[time] = None
    duration_minutes: Optional[int] = Field(default=None, ge=15, le=480)
    mode: Optional[TeachingMode] = None
    budget: Optional[float] = Field(default=None, ge=0, le=5_000_000)
    message: Optional[str] = Field(default=None, max_length=1500)
    location_note: Optional[str] = Field(default=None, max_length=255)
    ignore_availability: bool = False


class BookingRequestDecision(BaseModel):
    status: Literal["accepted", "rejected", "completed", "cancelled"]
    note: Optional[str] = Field(default=None, max_length=1000)


class BookingRequestCancel(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=255)


class RequestParty(BaseModel):
    id: int
    name: str
    email: Optional[str] = None
    avatar_url: Optional[str] = None


class BookingRequestOut(BaseModel):
    model_config = ORM

    id: int
    status: RequestStatus
    subject_id: int
    subject_name: str = ""
    preferred_date: date
    preferred_time: time
    duration_minutes: int
    mode: TeachingMode
    budget: float
    message: Optional[str] = None
    location_note: Optional[str] = None
    tutor_response_note: Optional[str] = None
    cancel_reason: Optional[str] = None
    responded_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    tutor: RequestParty
    student: RequestParty
    tutor_city: str = ""
    tutor_state: str = ""
    tutor_hourly_rate: float = 0
    review_id: Optional[int] = None
    has_review: bool = False
    can_review: bool = False
    session_label: str = ""


class StudentDashboardStats(BaseModel):
    total_requests: int
    pending_requests: int
    accepted_requests: int
    rejected_requests: int
    cancelled_requests: int
    completed_sessions: int
    upcoming_sessions: int
    reviews_written: int
    favorites: int
    tutors_contacted: int
    total_spent: float


# --------------------------------------------------------------------------- #
# Reviews
# --------------------------------------------------------------------------- #
class ReviewCreate(BaseModel):
    booking_request_id: int
    rating: int = Field(ge=1, le=5)
    title: Optional[str] = Field(default=None, max_length=160)
    comment: Optional[str] = Field(default=None, min_length=3, max_length=2000)


class ReviewUpdate(BaseModel):
    rating: Optional[int] = Field(default=None, ge=1, le=5)
    title: Optional[str] = Field(default=None, max_length=160)
    comment: Optional[str] = Field(default=None, min_length=3, max_length=2000)


class TutorRatingSummary(BaseModel):
    tutor_id: int
    rating: float
    review_count: int
    breakdown: List[RatingBreakdown] = []


# --------------------------------------------------------------------------- #
# Notifications & admin
# --------------------------------------------------------------------------- #
class NotificationOut(BaseModel):
    model_config = ORM

    id: int
    type: str
    title: str
    body: Optional[str] = None
    link: Optional[str] = None
    is_read: bool
    created_at: Optional[datetime] = None


class NotificationList(BaseModel):
    items: List[NotificationOut]
    unread_count: int


class AdminUserOut(BaseModel):
    model_config = ORM

    id: int
    email: EmailStr
    full_name: str
    phone: Optional[str] = None
    role: UserRole
    is_active: bool
    avatar_url: Optional[str] = None
    last_login_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    city: Optional[str] = None
    state: Optional[str] = None
    headline: Optional[str] = None
    hourly_rate: Optional[float] = None
    approval_status: Optional[TutorStatus] = None
    requests_count: int = 0


class ActivityOut(BaseModel):
    model_config = ORM

    id: int
    action: str
    description: str
    entity_type: Optional[str] = None
    entity_id: Optional[int] = None
    actor_name: Optional[str] = None
    created_at: Optional[datetime] = None


class AdminStats(BaseModel):
    total_users: int
    total_tutors: int
    total_students: int
    total_admins: int
    active_users: int
    pending_tutor_approvals: int
    approved_tutors: int
    suspended_tutors: int
    total_requests: int
    pending_requests: int
    accepted_requests: int
    rejected_requests: int
    cancelled_requests: int
    completed_requests: int
    total_reviews: int
    hidden_reviews: int
    average_rating: float
    total_subjects: int
    total_availability_slots: int
    new_users_last_7_days: int
    requests_last_7_days: int
    gross_session_value: float
    requests_by_status: List[dict]
    top_subjects: List[dict]
    tutors_by_state: List[dict]
    signups_by_day: List[dict]
    requests_by_day: List[dict]


# Forward references used by Token
Token.model_rebuild()
