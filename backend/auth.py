"""
Authentication & authorisation.

* Password hashing  -> passlib PBKDF2-SHA256 (no plaintext ever stored)
* Tokens            -> JWT (HS256) signed with JWT_SECRET_KEY from the environment
* Authorisation     -> FastAPI dependencies that enforce role-based access

Passwords are never returned by any endpoint and never appear in logs.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.orm import Session

from config import settings
from database import get_db
from models import User, UserRole

# --------------------------------------------------------------------------- #
# Password hashing
# --------------------------------------------------------------------------- #
pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")


def hash_password(password: str) -> str:
    """Return a salted, iterated hash of the given password."""
    return pwd_context.hash(password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    """Constant-time comparison of a candidate password against a stored hash."""
    try:
        return pwd_context.verify(plain_password, password_hash)
    except (ValueError, TypeError):
        return False


# --------------------------------------------------------------------------- #
# JWT
# --------------------------------------------------------------------------- #
def create_access_token(
    subject: str | int,
    role: str,
    extra: Optional[Dict[str, Any]] = None,
    expires_minutes: Optional[int] = None,
) -> str:
    expires_minutes = expires_minutes or settings.access_token_expire_minutes
    now = datetime.now(timezone.utc)
    payload: Dict[str, Any] = {
        "sub": str(subject),
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=expires_minutes)).timestamp()),
        "iss": settings.app_name,
        "type": "access",
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> Dict[str, Any]:
    try:
        return jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
            issuer=settings.app_name,
            options={"require": ["exp", "sub"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Your session has expired. Please sign in again.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except jwt.InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


# --------------------------------------------------------------------------- #
# FastAPI dependencies
# --------------------------------------------------------------------------- #
bearer_scheme = HTTPBearer(auto_error=False, description="JWT access token")

CREDENTIALS_EXCEPTION = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials. Please sign in again.",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Resolve the bearer token to an active User row."""
    if credentials is None or not credentials.credentials:
        raise CREDENTIALS_EXCEPTION

    payload = decode_access_token(credentials.credentials)
    user_id = payload.get("sub")
    if not user_id:
        raise CREDENTIALS_EXCEPTION

    user = db.get(User, int(user_id))
    if user is None:
        raise CREDENTIALS_EXCEPTION
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account has been deactivated. Contact support for assistance.",
        )
    return user


def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> Optional[User]:
    """Same as get_current_user but returns None instead of raising (public routes)."""
    if credentials is None or not credentials.credentials:
        return None
    try:
        payload = decode_access_token(credentials.credentials)
        user = db.get(User, int(payload.get("sub", 0)))
    except (HTTPException, ValueError, TypeError):
        return None
    if user is None or not user.is_active:
        return None
    return user


def require_roles(*roles: UserRole | str):
    """Dependency factory enforcing role-based access control."""
    allowed: List[str] = {r.value if isinstance(r, UserRole) else r for r in roles}

    def _dependency(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role.value not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"This action requires one of the following roles: "
                    f"{', '.join(sorted(allowed))}."
                ),
            )
        return current_user

    return _dependency


require_admin = require_roles(UserRole.ADMIN)
require_tutor = require_roles(UserRole.TUTOR)
require_student = require_roles(UserRole.STUDENT)
require_tutor_or_admin = require_roles(UserRole.TUTOR, UserRole.ADMIN)
require_student_or_admin = require_roles(UserRole.STUDENT, UserRole.ADMIN)


def get_owned_tutor_profile(db: Session, user: User) -> Optional["TutorProfile"]:
    """Return the tutor profile owned by ``user``.

    Plain helper (not a FastAPI dependency) so routers can call it directly.
    Admins have no profile of their own, so ``None`` is returned for them;
    tutors/students without a profile also get ``None`` and the caller decides
    whether that is a 404 or simply an empty payload.
    """
    from models import TutorProfile

    if user.role == UserRole.ADMIN:
        return None
    return db.scalar(select(TutorProfile).where(TutorProfile.user_id == user.id))


def require_owned_tutor_profile(db: Session, user: User) -> "TutorProfile":
    """Like :func:`get_owned_tutor_profile` but raises 404 when there is none."""
    profile = get_owned_tutor_profile(db, user)
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="You have not created a tutor profile yet.",
        )
    return profile


def get_owned_student_profile(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    from models import StudentProfile

    profile = db.scalar(
        select(StudentProfile).where(StudentProfile.user_id == current_user.id)
    )
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Student profile not found for this account.",
        )
    return profile


# --------------------------------------------------------------------------- #
# Utility
# --------------------------------------------------------------------------- #
def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def ensure_roles(user: User, roles: Iterable[str]) -> None:  # pragma: no cover
    """Small helper kept for readability in routers."""
    if user.role.value not in {r.value if isinstance(r, UserRole) else r for r in roles}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
