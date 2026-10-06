"""Authentication & authorisation tests."""
from __future__ import annotations

import base64
from pathlib import Path

import pytest
from conftest import auth, login

FRONTEND = Path(__file__).resolve().parents[1] / "frontend"
PNG_PIXEL_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8"
    "z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


# --------------------------------------------------------------------------- #
# Registration
# --------------------------------------------------------------------------- #
def test_register_student_returns_jwt_and_profile(client, unique_email):
    response = client.post(
        "/api/auth/register",
        json={
            "full_name": "Test Student",
            "email": unique_email,
            "password": "ValidPass123",
            "role": "student",
            "city": "Yaba",
            "state": "Lagos State",
            "education_level": "SS2",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["user"]["role"] == "student"
    assert body["user"]["email"] == unique_email
    assert body["user"]["student_profile_id"] is not None
    # password hash must never leak
    assert "password" not in body["user"]
    assert "password_hash" not in body["user"]


def test_register_tutor_creates_profile_and_subjects(client, unique_email):
    response = client.post(
        "/api/auth/register",
        json={
            "full_name": "Test Tutor",
            "email": unique_email,
            "password": "ValidPass123",
            "role": "tutor",
            "headline": "Test Mathematics tutor",
            "bio": "I have taught mathematics for many years and enjoy helping students improve quickly.",
            "years_experience": 4,
            "hourly_rate": 4500,
            "city": "Ibadan",
            "state": "Oyo State",
            "teaching_mode": "hybrid",
            "subject_ids": [1, 2],
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["user"]["role"] == "tutor"
    assert body["user"]["tutor_profile_id"] is not None

    profile = client.get(f"/api/tutors/{body['user']['tutor_profile_id']}").json()
    assert profile["hourly_rate"] == 4500
    assert {s["id"] for s in profile["subjects"]} == {1, 2}


def test_register_duplicate_email_conflict(client, unique_email):
    payload = {
        "full_name": "Duplicate User",
        "email": unique_email,
        "password": "ValidPass123",
        "role": "student",
    }
    first = client.post("/api/auth/register", json=payload)
    assert first.status_code == 201, first.text
    second = client.post("/api/auth/register", json=payload)
    assert second.status_code == 409
    assert "already exists" in second.json()["detail"].lower()


@pytest.mark.parametrize(
    "password,message_fragment",
    [
        ("short1", "at least 8"),
        ("alllettersonly", "at least one number"),
        ("12345678", "too common"),
        ("98765432", "at least one letter"),
    ],
)
def test_register_rejects_weak_passwords(client, unique_email, password, message_fragment):
    response = client.post(
        "/api/auth/register",
        json={
            "full_name": "Weak Password",
            "email": unique_email,
            "password": password,
            "role": "student",
        },
    )
    assert response.status_code == 422
    assert message_fragment in response.text.lower()


def test_register_rejects_invalid_email(client, unique_email):
    response = client.post(
        "/api/auth/register",
        json={
            "full_name": "Bad Email",
            "email": "not-an-email",
            "password": "ValidPass123",
            "role": "student",
        },
    )
    assert response.status_code == 422


def test_register_tutor_requires_profile_fields(client, unique_email):
    response = client.post(
        "/api/auth/register",
        json={
            "full_name": "Incomplete Tutor",
            "email": unique_email,
            "password": "ValidPass123",
            "role": "tutor",
        },
    )
    assert response.status_code == 422
    assert "Tutor registration requires" in response.text


def test_register_tutor_requires_subjects(client, unique_email):
    response = client.post(
        "/api/auth/register",
        json={
            "full_name": "No Subjects",
            "email": unique_email,
            "password": "ValidPass123",
            "role": "tutor",
            "headline": "Maths tutor",
            "bio": "A sufficiently long biography that passes the minimum length validation rule.",
            "years_experience": 2,
            "hourly_rate": 3000,
            "city": "Kano",
            "state": "Kano State",
        },
    )
    assert response.status_code == 422
    assert "subject" in response.text.lower()


def test_passwords_are_hashed_in_the_database(db, client, unique_email):
    client.post(
        "/api/auth/register",
        json={
            "full_name": "Hash Check",
            "email": unique_email,
            "password": "ValidPass123",
            "role": "student",
        },
    )
    from sqlalchemy import select

    from models import User

    db.expire_all()
    user = db.scalar(select(User).where(User.email == unique_email))
    assert user is not None
    assert user.password_hash != "ValidPass123"
    assert user.password_hash.startswith("$pbkdf2-sha256$")


# --------------------------------------------------------------------------- #
# Login / session
# --------------------------------------------------------------------------- #
def test_login_success_and_failure(client, unique_email):
    client.post(
        "/api/auth/register",
        json={
            "full_name": "Login Test",
            "email": unique_email,
            "password": "ValidPass123",
            "role": "student",
        },
    )

    ok = client.post("/api/auth/login", json={"email": unique_email, "password": "ValidPass123"})
    assert ok.status_code == 200
    assert ok.json()["access_token"]

    bad = client.post("/api/auth/login", json={"email": unique_email, "password": "WrongPass123"})
    assert bad.status_code == 401
    # identical message for unknown email and wrong password (no enumeration)
    unknown = client.post("/api/auth/login", json={"email": "nobody@nowhere.example.com", "password": "x" * 10})
    assert unknown.status_code == 401
    assert unknown.json()["detail"] == bad.json()["detail"]


def test_email_is_case_insensitive_on_login(client, unique_email):
    client.post(
        "/api/auth/register",
        json={
            "full_name": "Case Test",
            "email": unique_email,
            "password": "ValidPass123",
            "role": "student",
        },
    )
    response = client.post(
        "/api/auth/login", json={"email": unique_email.upper(), "password": "ValidPass123"}
    )
    assert response.status_code == 200


def test_me_requires_token(client):
    assert client.get("/api/auth/me").status_code in (401, 403)
    assert client.get("/api/auth/me", headers=auth("garbage.token.value")).status_code == 401


def test_me_returns_current_user(client, student_token):
    response = client.get("/api/auth/me", headers=auth(student_token))
    assert response.status_code == 200
    assert response.json()["role"] == "student"


def test_update_me(client, student_token):
    response = client.put(
        "/api/auth/me",
        headers=auth(student_token),
        json={"full_name": "Chiamaka Obi-Updated", "phone": "+234 802 000 0000"},
    )
    assert response.status_code == 200
    assert response.json()["full_name"] == "Chiamaka Obi-Updated"
    assert response.json()["phone"] == "+234 802 000 0000"

    # restore
    client.put("/api/auth/me", headers=auth(student_token), json={"full_name": "Chiamaka Obi"})


def test_change_password_flow(client, unique_email):
    client.post(
        "/api/auth/register",
        json={
            "full_name": "Password Change",
            "email": unique_email,
            "password": "ValidPass123",
            "role": "student",
        },
    )
    token = login(client, unique_email, "ValidPass123")

    wrong = client.post(
        "/api/auth/change-password",
        headers=auth(token),
        json={"current_password": "NotMyPassword1", "new_password": "BrandNew123"},
    )
    assert wrong.status_code == 400

    same = client.post(
        "/api/auth/change-password",
        headers=auth(token),
        json={"current_password": "ValidPass123", "new_password": "ValidPass123"},
    )
    assert same.status_code == 422

    ok = client.post(
        "/api/auth/change-password",
        headers=auth(token),
        json={"current_password": "ValidPass123", "new_password": "BrandNew123"},
    )
    assert ok.status_code == 200

    assert client.post("/api/auth/login", json={"email": unique_email, "password": "ValidPass123"}).status_code == 401
    assert client.post("/api/auth/login", json={"email": unique_email, "password": "BrandNew123"}).status_code == 200


def test_logout_endpoint(client, student_token):
    response = client.post("/api/auth/logout", headers=auth(student_token))
    assert response.status_code == 200
    assert "Signed out" in response.json()["detail"]


def test_deactivated_account_cannot_log_in(client, admin_token, unique_email):
    client.post(
        "/api/auth/register",
        json={
            "full_name": "Suspend Me",
            "email": unique_email,
            "password": "ValidPass123",
            "role": "student",
        },
    )
    token = login(client, unique_email, "ValidPass123")
    user_id = client.get("/api/auth/me", headers=auth(token)).json()["id"]

    suspended = client.post(f"/api/admin/users/{user_id}/toggle-active", headers=auth(admin_token))
    assert suspended.status_code == 200
    assert suspended.json()["is_active"] is False

    blocked = client.post("/api/auth/login", json={"email": unique_email, "password": "ValidPass123"})
    assert blocked.status_code == 403

    # existing token no longer works either
    assert client.get("/api/auth/me", headers=auth(token)).status_code == 403

    client.post(f"/api/admin/users/{user_id}/toggle-active", headers=auth(admin_token))


# --------------------------------------------------------------------------- #
# Role-based access control
# --------------------------------------------------------------------------- #
def test_role_guards(client, student_token, tutor_token, admin_token):
    assert client.get("/api/admin/stats", headers=auth(student_token)).status_code == 403
    assert client.get("/api/admin/stats", headers=auth(tutor_token)).status_code == 403
    assert client.get("/api/admin/stats", headers=auth(admin_token)).status_code == 200

    assert client.get("/api/tutors/me", headers=auth(student_token)).status_code == 403
    assert client.get("/api/tutors/me", headers=auth(tutor_token)).status_code == 200

    assert client.get("/api/favorites", headers=auth(tutor_token)).status_code == 403
    assert client.get("/api/favorites", headers=auth(student_token)).status_code == 200


def test_student_cannot_create_tutor_profile(client, student_token):
    response = client.post(
        "/api/tutors",
        headers=auth(student_token),
        json={
            "headline": "Should not work",
            "bio": "A biography that is definitely longer than forty characters for validation.",
            "years_experience": 1,
            "hourly_rate": 1000,
            "city": "Yaba",
            "state": "Lagos State",
            "subject_ids": [1],
        },
    )
    assert response.status_code == 403


# --------------------------------------------------------------------------- #
# Profile photo — upload from device, replace (edit), delete
# --------------------------------------------------------------------------- #
def _register_photo_student(client, email):
    response = client.post(
        "/api/auth/register",
        json={
            "full_name": "Photo Tester",
            "email": email,
            "password": "ValidPass123",
            "role": "student",
            "city": "Yaba",
            "state": "Lagos State",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["access_token"]


def test_avatar_upload_edit_and_delete(client, unique_email):
    headers = auth(_register_photo_student(client, unique_email))

    # upload from "device": the browser widget sends a data: URL
    r = client.post(
        "/api/auth/avatar",
        json={"image": "data:image/png;base64," + PNG_PIXEL_B64},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    first_url = r.json()["data"]["avatar_url"]
    assert first_url.startswith("/uploads/avatars/") and first_url.endswith(".png")
    first_file = FRONTEND / first_url.lstrip("/")
    assert first_file.is_file()
    assert client.get(first_url).status_code == 200          # served by the static mount
    assert client.get("/api/auth/me", headers=headers).json()["avatar_url"] == first_url

    # edit: uploading again replaces the previous file (bare base64 accepted too)
    r2 = client.post("/api/auth/avatar", json={"image": PNG_PIXEL_B64}, headers=headers)
    assert r2.status_code == 200, r2.text
    second_url = r2.json()["data"]["avatar_url"]
    assert second_url != first_url
    assert not first_file.exists()
    assert (FRONTEND / second_url.lstrip("/")).is_file()

    # rejects payloads that are not real images
    bad = base64.b64encode(b"this is definitely not an image").decode()
    r3 = client.post("/api/auth/avatar", json={"image": bad}, headers=headers)
    assert r3.status_code == 422

    # delete removes the file and clears the field
    r4 = client.delete("/api/auth/avatar", headers=headers)
    assert r4.status_code == 200
    assert not (FRONTEND / second_url.lstrip("/")).exists()
    assert client.get("/api/auth/me", headers=headers).json()["avatar_url"] is None

    client.delete("/api/auth/me", headers=headers)           # cleanup


def test_avatar_endpoints_require_auth(client):
    assert client.post("/api/auth/avatar", json={"image": PNG_PIXEL_B64}).status_code == 401
    assert client.delete("/api/auth/avatar").status_code == 401
