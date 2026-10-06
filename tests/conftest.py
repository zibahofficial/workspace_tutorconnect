"""
Pytest fixtures for the TutorConnect API test-suite.

The suite runs against a throw-away SQLite database so it never touches the
development data in `data/tutorconnect.db`.
"""
from __future__ import annotations

import os
import sys
import tempfile
from datetime import date, time, timedelta
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND_DIR))

# Point the app at an isolated test database BEFORE importing anything else.
_TEST_DB = Path(tempfile.gettempdir()) / "tutorconnect_test.db"
if _TEST_DB.exists():
    _TEST_DB.unlink()
for suffix in ("-wal", "-shm"):
    extra = Path(str(_TEST_DB) + suffix)
    if extra.exists():
        extra.unlink()

os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB.as_posix()}"
os.environ["JWT_SECRET_KEY"] = "test-secret-key-for-pytest-only-1234567890"
os.environ["SEED_DEMO_DATA"] = "true"
os.environ["ADMIN_EMAIL"] = "admin@example.com"
os.environ["ADMIN_PASSWORD"] = "AdminTest123"
os.environ["ENVIRONMENT"] = "test"
os.environ["DEBUG"] = "false"
os.environ["MIN_BOOKING_LEAD_HOURS"] = "1"

from fastapi.testclient import TestClient  # noqa: E402

from database import Base, SessionLocal, engine  # noqa: E402
from main import app  # noqa: E402
from seed import seed_database  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _bootstrap_database():
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        seed_database(db, force=True, verbose=False)
        db.commit()
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="session")
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


# --------------------------------------------------------------------------- #
# Auth helpers
# --------------------------------------------------------------------------- #
def login(client: TestClient, email: str, password: str) -> str:
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="session")
def admin_token(client):
    return login(client, "admin@example.com", "AdminTest123")


@pytest.fixture(scope="session")
def tutor_token(client):
    return login(client, "chinedu.okafor@example.com", "TutorDemo123")


@pytest.fixture(scope="session")
def tutor2_token(client):
    return login(client, "aisha.bello@example.com", "TutorDemo123")


@pytest.fixture(scope="session")
def student_token(client):
    return login(client, "chiamaka@example.com", "StudentDemo123")


@pytest.fixture(scope="session")
def student2_token(client):
    return login(client, "tobi@example.com", "StudentDemo123")


@pytest.fixture()
def unique_email() -> str:
    import uuid

    return f"u{uuid.uuid4().hex[:10]}@example.com"


# --------------------------------------------------------------------------- #
# Date helpers
# --------------------------------------------------------------------------- #
def next_weekday(weekday: int, min_offset: int = 1) -> date:
    """First future date whose weekday() equals `weekday` (Mon=0)."""
    candidate = date.today() + timedelta(days=min_offset)
    while candidate.weekday() != weekday:
        candidate += timedelta(days=1)
    return candidate


def past_weekday(weekday: int, min_offset: int = 10) -> date:
    candidate = date.today() - timedelta(days=min_offset)
    while candidate.weekday() != weekday:
        candidate -= timedelta(days=1)
    return candidate


def bookable_date(weekday: int, start_time: str) -> date:
    """
    The next date whose weekday matches AND whose session start is far enough in
    the future to satisfy MIN_BOOKING_LEAD_HOURS. Keeps tests deterministic
    regardless of the time of day they run.
    """
    parts = str(start_time).split(":")
    hours, minutes = int(parts[0]), int(parts[1] or 0)
    for offset in range(1, 21):
        candidate = date.today() + timedelta(days=offset)
        if candidate.weekday() != weekday:
            continue
        from datetime import datetime

        start = datetime.combine(candidate, time(hours, minutes))
        if start >= datetime.now() + timedelta(hours=2):
            return candidate
    raise AssertionError(f"No bookable date found for weekday {weekday} at {start_time}")
