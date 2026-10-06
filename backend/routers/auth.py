"""Auth endpoints: registration, login, session, password management."""
from __future__ import annotations

import base64
import binascii
import re
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from auth import (
    create_access_token,
    get_current_user,
    hash_password,
    normalize_email,
    verify_password,
)
from config import FRONTEND_DIR, settings
from database import get_db
from helpers import log_activity
from models import (
    ActivityAction,
    Notification,
    NotificationType,
    StudentProfile,
    Subject,
    TeachingMode,
    TutorProfile,
    TutorSubject,
    User,
    UserRole,
)
from schemas import (
    AvatarUploadRequest,
    ChangePasswordRequest,
    LoginRequest,
    Message,
    RegisterRequest,
    Token,
    UserOut,
    UserUpdate,
)

router = APIRouter(prefix="/auth", tags=["Authentication"])


# --------------------------------------------------------------------------- #
# Serialiser
# --------------------------------------------------------------------------- #
def user_out(db: Session, user: User) -> dict:
    tutor_profile_id: Optional[int] = None
    student_profile_id: Optional[int] = None
    if user.role == UserRole.TUTOR:
        tutor_profile_id = db.scalar(
            select(TutorProfile.id).where(TutorProfile.user_id == user.id)
        )
    elif user.role == UserRole.STUDENT:
        student_profile_id = db.scalar(
            select(StudentProfile.id).where(StudentProfile.user_id == user.id)
        )
    return {
        "id": user.id,
        "email": user.email,
        "full_name": user.full_name,
        "phone": user.phone,
        "avatar_url": user.avatar_url,
        "role": user.role.value,
        "is_active": user.is_active,
        "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "tutor_profile_id": tutor_profile_id,
        "student_profile_id": student_profile_id,
    }


def issue_token(db: Session, user: User) -> dict:
    token = create_access_token(user.id, user.role.value, {"email": user.email})
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in_minutes": settings.access_token_expire_minutes,
        "user": user_out(db, user),
    }


# --------------------------------------------------------------------------- #
# POST /auth/register
# --------------------------------------------------------------------------- #
@router.post(
    "/register",
    response_model=Token,
    status_code=status.HTTP_201_CREATED,
    summary="Create a tutor or student account",
)
def register(payload: RegisterRequest, response: Response, db: Session = Depends(get_db)):
    email = normalize_email(payload.email)

    existing = db.scalar(select(User).where(User.email == email))
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "An account with this email already exists. "
                "Try signing in instead, or use a different email address."
            ),
        )

    role = UserRole(payload.role)
    user = User(
        email=email,
        password_hash=hash_password(payload.password),
        full_name=payload.full_name.strip(),
        phone=payload.phone,
        avatar_url=payload.avatar_url,
        role=role,
        is_active=True,
    )
    db.add(user)
    try:
        db.flush()  # obtain user.id
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That email address is already registered.",
        ) from exc

    if role == UserRole.TUTOR:
        profile = TutorProfile(
            user_id=user.id,
            headline=payload.headline.strip(),
            bio=payload.bio.strip(),
            years_experience=payload.years_experience or 0,
            hourly_rate=payload.hourly_rate or 0,
            session_duration_minutes=60,
            city=payload.city.strip(),
            state=payload.state.strip(),
            country="Nigeria",
            teaching_mode=payload.teaching_mode or TeachingMode.HYBRID,
            accepts_online=payload.teaching_mode in (None, TeachingMode.ONLINE, TeachingMode.HYBRID),
            accepts_in_person=payload.teaching_mode
            in (None, TeachingMode.IN_PERSON, TeachingMode.HYBRID),
            approval_status="approved",
        )
        db.add(profile)
        db.flush()

        if payload.subject_ids:
            subjects = db.scalars(
                select(Subject).where(Subject.id.in_(payload.subject_ids), Subject.is_active.is_(True))
            ).all()
            if not subjects:
                db.rollback()
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="None of the selected subjects exist. Please choose valid subjects.",
                )
            for subject in subjects:
                db.add(
                    TutorSubject(
                        tutor_profile_id=profile.id,
                        subject_id=subject.id,
                        proficiency="Advanced",
                    )
                )
        log_activity(
            db,
            ActivityAction.TUTOR_PROFILE_CREATED,
            f"{user.full_name} created a tutor profile for {profile.city}, {profile.state}",
            actor_user_id=user.id,
            entity_type="tutor_profile",
            entity_id=profile.id,
        )
    else:
        student = StudentProfile(
            user_id=user.id,
            education_level=payload.education_level,
            guardian_name=payload.guardian_name,
            city=payload.city,
            state=payload.state,
        )
        db.add(student)

    log_activity(
        db,
        ActivityAction.USER_REGISTERED,
        f"New {role.value} account: {user.full_name}",
        actor_user_id=user.id,
        entity_type="user",
        entity_id=user.id,
    )
    db.add(
        Notification(
            user_id=user.id,
            type=NotificationType.ACCOUNT,
            title=f"Welcome to {settings.app_name}, {user.full_name.split()[0]}!",
            body=(
                "Complete your profile and set your availability to start receiving requests."
                if role == UserRole.TUTOR
                else "Search tutors by subject, location and budget, then send your first request."
            ),
            link="dashboard.html" if role == UserRole.TUTOR else "tutors.html",
        )
    )

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Could not create the account. That email may already be registered.",
        ) from exc

    db.refresh(user)
    response.status_code = status.HTTP_201_CREATED
    return issue_token(db, user)


# --------------------------------------------------------------------------- #
# POST /auth/login
# --------------------------------------------------------------------------- #
@router.post("/login", response_model=Token, summary="Sign in and receive a JWT")
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    email = normalize_email(payload.email)
    user = db.scalar(select(User).where(User.email == email))

    # Same error for unknown email and wrong password (no account enumeration).
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password. Please try again.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account has been deactivated by an administrator.",
        )

    from datetime import datetime, timezone

    user.last_login_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(user)
    return issue_token(db, user)


# --------------------------------------------------------------------------- #
# Session helpers
# --------------------------------------------------------------------------- #
@router.get("/me", response_model=UserOut, summary="Current authenticated user")
def read_me(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return user_out(db, current_user)


@router.put("/me", response_model=UserOut, summary="Update your account details")
def update_me(
    payload: UserUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    data = payload.model_dump(exclude_unset=True, exclude_none=True)
    for field, value in data.items():
        if field in {"full_name", "phone", "avatar_url"}:
            setattr(current_user, field, value)
    db.commit()
    db.refresh(current_user)
    return user_out(db, current_user)


@router.post("/change-password", response_model=Message, summary="Change your password")
def change_password(
    payload: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not verify_password(payload.current_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Your current password is incorrect.",
        )
    current_user.password_hash = hash_password(payload.new_password)
    db.commit()
    return {"detail": "Password updated successfully."}


@router.post("/logout", response_model=Message, summary="Logout (client discards the JWT)")
def logout(current_user: User = Depends(get_current_user)):
    return {
        "detail": f"Signed out successfully. Goodbye, {current_user.full_name.split()[0]}!"
    }


@router.delete("/me", response_model=Message, summary="Deactivate your own account")
def deactivate_me(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    if current_user.role == UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Administrator accounts cannot be self-deactivated.",
        )
    current_user.is_active = False
    log_activity(
        db,
        ActivityAction.USER_DEACTIVATED,
        f"{current_user.full_name} deactivated their own account",
        actor_user_id=current_user.id,
        entity_type="user",
        entity_id=current_user.id,
    )
    db.commit()
    return {"detail": "Your account has been deactivated."}


# --------------------------------------------------------------------------- #
# Profile photo — upload from device, replace (edit) and delete
# --------------------------------------------------------------------------- #
AVATAR_DIR = FRONTEND_DIR / "uploads" / "avatars"
MAX_AVATAR_BYTES = 3 * 1024 * 1024
_DATA_URL_RE = re.compile(r"^data:image/[\w.+-]+;base64,(.*)$", re.DOTALL)


def _sniff_image_ext(data: bytes) -> Optional[str]:
    """Identify the real image type from magic bytes (never trust the MIME label)."""
    if data[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return ".gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    return None


def _remove_local_avatar(url: Optional[str]) -> None:
    """Delete a previously uploaded avatar file. Remote URLs are left alone."""
    if not url or not url.startswith("/uploads/avatars/"):
        return
    try:
        candidate = (AVATAR_DIR / Path(url).name).resolve()
        if candidate.is_relative_to(AVATAR_DIR.resolve()) and candidate.is_file():
            candidate.unlink()
    except OSError:
        pass


@router.post("/avatar", summary="Upload a profile photo from your device")
def upload_avatar(
    payload: AvatarUploadRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    raw = (payload.image or "").strip()
    match = _DATA_URL_RE.match(raw)
    encoded = match.group(1) if match else raw
    try:
        data = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="That file doesn't look like a valid image.",
        )
    if not data:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="The selected image is empty.",
        )
    if len(data) > MAX_AVATAR_BYTES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Image is too large — please choose one under 3 MB.",
        )
    ext = _sniff_image_ext(data)
    if ext is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Unsupported image type. Use PNG, JPG, GIF or WebP.",
        )

    AVATAR_DIR.mkdir(parents=True, exist_ok=True)
    _remove_local_avatar(current_user.avatar_url)          # replaces any earlier upload
    filename = f"{uuid.uuid4().hex}{ext}"
    (AVATAR_DIR / filename).write_bytes(data)
    current_user.avatar_url = f"/uploads/avatars/{filename}"
    db.commit()
    return {
        "detail": "Profile photo uploaded.",
        "data": {"avatar_url": current_user.avatar_url},
    }


@router.delete("/avatar", response_model=Message, summary="Remove your profile photo")
def delete_avatar(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    _remove_local_avatar(current_user.avatar_url)
    current_user.avatar_url = None
    db.commit()
    return {"detail": "Profile photo removed."}
