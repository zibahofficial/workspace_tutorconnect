"""
Application configuration.

Every secret / environment-specific value is read from the environment (a `.env`
file in development, real environment variables in production).  Nothing is
hard-coded here so the repository never leaks credentials.
"""
from __future__ import annotations

import os
import sys
import secrets
from functools import lru_cache
from pathlib import Path
from typing import List

BASE_DIR = Path(__file__).resolve().parent.parent          # .../tutor-matching-platform
BACKEND_DIR = BASE_DIR / "backend"
FRONTEND_DIR = BASE_DIR / "frontend"


def _load_dotenv(path: Path | None = None) -> None:
    """
    Minimal .env loader (no external dependency required).

    Existing environment variables always win over the file, which keeps
    deployments (Render / Railway / Fly / Docker) predictable.
    """
    candidates = [p for p in (path, BASE_DIR / ".env", BACKEND_DIR / ".env") if p]
    for candidate in candidates:
        if not candidate.exists():
            continue
        try:
            for raw_line in candidate.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                os.environ.setdefault(key, value)
        except OSError:
            continue
        break


_load_dotenv()


def _as_bool(value: str | bool | None, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return value.strip().lower() in {"1", "true", "yes", "on", "y"}


def _as_list(value: str | None, default: List[str] | None = None) -> List[str]:
    if not value:
        return list(default or [])
    return [item.strip() for item in value.split(",") if item.strip()]


MIN_JWT_SECRET_BYTES = 32  # RFC 7518 minimum for HS256


def _resolve_sqlite_path(url: str) -> str:
    """Anchor relative ``sqlite:///`` URLs to the project root.

    ``sqlite:///./data/tutorconnect.db`` is resolved against the *current working
    directory*, so running the server from ``backend/`` would silently create a
    second database in ``backend/data/``. Rewriting it to an absolute path makes
    the location independent of where the process was started. Absolute URLs and
    every other backend (PostgreSQL, in-memory SQLite) are returned untouched.
    """
    prefix = "sqlite:///"
    if not url.startswith(prefix):
        return url
    raw = url[len(prefix):]
    if not raw or raw == ":memory:" or raw.startswith(("+", "?")):
        return url
    candidate = Path(raw)
    if candidate.is_absolute():
        return url
    resolved = (BASE_DIR / candidate).resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    return f"{prefix}{resolved.as_posix()}"


class Settings:
    """Runtime settings populated from the environment."""

    def __init__(self) -> None:
        self.app_name: str = os.getenv("APP_NAME", "TutorConnect")
        self.app_tagline: str = os.getenv(
            "APP_TAGLINE", "Find the right tutor. Learn with confidence."
        )
        self.environment: str = os.getenv("ENVIRONMENT", "development").lower()
        self.debug: bool = _as_bool(os.getenv("DEBUG"), self.environment == "development")

        # --- Database -----------------------------------------------------
        # Defaults to a local SQLite file so the project runs with zero setup.
        # Point DATABASE_URL at PostgreSQL for production:
        #   postgresql+psycopg2://user:pass@host:5432/tutorconnect
        default_sqlite = f"sqlite:///{(BASE_DIR / 'data' / 'tutorconnect.db').as_posix()}"
        self.database_url: str = _resolve_sqlite_path(
            os.getenv("DATABASE_URL", default_sqlite)
        )
        self.db_echo: bool = _as_bool(os.getenv("DB_ECHO"), False)

        # --- Security -----------------------------------------------------
        # A random secret is generated when none is supplied. That is safe for a
        # throw-away local run (tokens simply expire on restart) but you MUST set
        # JWT_SECRET_KEY in any real deployment.
        configured_secret = os.getenv("JWT_SECRET_KEY", "").strip()
        if configured_secret:
            self.jwt_secret_key: str = configured_secret
            self.jwt_secret_is_ephemeral = False
            self.jwt_secret_is_weak = len(configured_secret.encode()) < MIN_JWT_SECRET_BYTES
            if self.jwt_secret_is_weak:
                # PyJWT only emits a cryptic InsecureKeyLengthWarning at signing
                # time, so say it plainly here instead.
                print(
                    f"[config] WARNING: JWT_SECRET_KEY is {len(configured_secret.encode())} bytes. "
                    f"HS256 wants at least {MIN_JWT_SECRET_BYTES}. Generate one with:\n"
                    '           python -c "import secrets; print(secrets.token_urlsafe(48))"',
                    file=sys.stderr,
                )
        else:
            self.jwt_secret_key = secrets.token_urlsafe(48)
            self.jwt_secret_is_ephemeral = True
            self.jwt_secret_is_weak = False
            print(
                "[config] WARNING: JWT_SECRET_KEY is not set - using a random secret for this "
                "process only. Tokens stop working after a restart. Set one in .env.",
                file=sys.stderr,
            )

        self.jwt_algorithm: str = os.getenv("JWT_ALGORITHM", "HS256")
        self.access_token_expire_minutes: int = int(
            os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", str(60 * 24))  # 24h
        )

        # --- CORS ---------------------------------------------------------
        default_origins = [
            "http://localhost:8000",
            "http://127.0.0.1:8000",
            "http://localhost:5500",
            "http://127.0.0.1:5500",
            "http://localhost:3000",
        ]
        self.cors_origins: List[str] = _as_list(
            os.getenv("CORS_ORIGINS"), default_origins
        )
        self.cors_allow_all: bool = _as_bool(os.getenv("CORS_ALLOW_ALL"), self.debug)

        # --- Bootstrap admin ---------------------------------------------
        self.admin_email: str = os.getenv("ADMIN_EMAIL", "").strip()
        self.admin_password: str = os.getenv("ADMIN_PASSWORD", "").strip()
        self.admin_name: str = os.getenv("ADMIN_NAME", "Platform Administrator").strip()

        # --- Seeding ------------------------------------------------------
        self.seed_demo_data: bool = _as_bool(os.getenv("SEED_DEMO_DATA"), True)

        # --- Pagination ---------------------------------------------------
        self.default_page_size: int = int(os.getenv("DEFAULT_PAGE_SIZE", "12"))
        self.max_page_size: int = int(os.getenv("MAX_PAGE_SIZE", "100"))

        # --- Business rules ----------------------------------------------
        self.min_booking_lead_hours: int = int(os.getenv("MIN_BOOKING_LEAD_HOURS", "2"))
        self.currency: str = os.getenv("CURRENCY", "NGN")
        self.currency_symbol: str = os.getenv("CURRENCY_SYMBOL", "\u20a6")

    @property
    def using_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    def summary(self) -> dict:
        """Safe, non-secret summary used by GET /api/health."""
        url = self.database_url
        if "@" in url:  # strip credentials from any URL
            scheme, _, rest = url.partition("://")
            _, _, host = rest.partition("@")
            url = f"{scheme}://{host}"
        return {
            "app": self.app_name,
            "environment": self.environment,
            "debug": self.debug,
            "database": "sqlite" if self.using_sqlite else url,
            "token_expiry_minutes": self.access_token_expire_minutes,
            "ephemeral_jwt_secret": self.jwt_secret_is_ephemeral,
            "weak_jwt_secret": self.jwt_secret_is_weak,
            "currency": self.currency,
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

# Ensure the SQLite data directory exists before the engine connects.
if settings.using_sqlite:
    _db_path = settings.database_url.replace("sqlite:///", "")
    Path(_db_path).parent.mkdir(parents=True, exist_ok=True)
