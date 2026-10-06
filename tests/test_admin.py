"""Admin moderation: stats, users, tutor approval, requests and reviews."""
from __future__ import annotations

import uuid

import pytest
from conftest import auth, bookable_date


def new_tutor(client, **overrides) -> dict:
    suffix = uuid.uuid4().hex[:8]
    payload = {
        "full_name": f"Admin Tutor {suffix}",
        "email": f"admin.tutor.{suffix}@example.com",
        "password": "ValidPass123",
        "role": "tutor",
        "headline": f"Adminmod {suffix} tutor",
        "bio": "Created by the automated test-suite to exercise admin moderation.",
        "years_experience": 3,
        "hourly_rate": 4200,
        "city": "Ikeja",
        "state": "Lagos State",
        "subject_ids": [1],
    }
    payload.update(overrides)
    response = client.post("/api/auth/register", json=payload)
    assert response.status_code == 201, response.text
    body = response.json()
    return {
        "token": body["access_token"],
        "user_id": body["user"]["id"],
        "profile_id": body["user"]["tutor_profile_id"],
        "name": payload["full_name"],
        "suffix": suffix,
    }


def new_student(client) -> dict:
    suffix = uuid.uuid4().hex[:8]
    body = client.post(
        "/api/auth/register",
        json={
            "full_name": f"Admin Student {suffix}",
            "email": f"admin.student.{suffix}@example.com",
            "password": "ValidPass123",
            "role": "student",
        },
    ).json()
    return {"token": body["access_token"], "user_id": body["user"]["id"], "suffix": suffix}


ADMIN_PATHS = [
    "/api/admin/stats",
    "/api/admin/activity",
    "/api/admin/users",
    "/api/admin/tutors",
    "/api/admin/requests",
    "/api/admin/reviews",
]


# --------------------------------------------------------------------------- #
# Access control
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("path", ADMIN_PATHS)
def test_admin_endpoints_reject_other_roles(client, path, tutor_token, student_token):
    assert client.get(path, headers=auth(tutor_token)).status_code == 403
    assert client.get(path, headers=auth(student_token)).status_code == 403
    assert client.get(path).status_code in (401, 403)


@pytest.mark.parametrize("path", ADMIN_PATHS)
def test_admin_endpoints_allow_admins(client, path, admin_token):
    assert client.get(path, headers=auth(admin_token)).status_code == 200


# --------------------------------------------------------------------------- #
# Stats
# --------------------------------------------------------------------------- #
def test_admin_stats_shape(client, admin_token):
    stats = client.get("/api/admin/stats", headers=auth(admin_token)).json()
    required = {
        "total_users", "total_tutors", "total_students", "total_admins", "active_users",
        "pending_tutor_approvals", "approved_tutors", "suspended_tutors", "total_requests",
        "pending_requests", "accepted_requests", "rejected_requests", "cancelled_requests",
        "completed_requests", "total_reviews", "hidden_reviews", "average_rating",
        "total_subjects", "total_availability_slots", "new_users_last_7_days",
        "requests_last_7_days", "gross_session_value", "requests_by_status", "top_subjects",
        "tutors_by_state", "signups_by_day", "requests_by_day",
    }
    assert required <= set(stats), required - set(stats)

    assert stats["total_users"] == stats["total_tutors"] + stats["total_students"] + stats["total_admins"]
    assert stats["total_admins"] >= 1
    assert stats["total_subjects"] >= 30
    assert 0 <= stats["average_rating"] <= 5
    assert stats["total_requests"] == (
        stats["pending_requests"] + stats["accepted_requests"] + stats["rejected_requests"]
        + stats["cancelled_requests"] + stats["completed_requests"]
    )
    assert sum(row["value"] for row in stats["requests_by_status"]) == stats["total_requests"]
    assert {row["label"] for row in stats["requests_by_status"]} == {
        "Pending", "Accepted", "Rejected", "Cancelled", "Completed"
    }
    assert all({"label", "value"} <= set(row) for row in stats["top_subjects"])
    assert all({"label", "value"} <= set(row) for row in stats["tutors_by_state"])
    assert len(stats["signups_by_day"]) == 14
    assert len(stats["requests_by_day"]) == 14


def test_admin_stats_update_live(client, admin_token):
    """Creating a tutor moves the counters immediately - nothing is cached."""
    before = client.get("/api/admin/stats", headers=auth(admin_token)).json()
    tutor = new_tutor(client)
    after = client.get("/api/admin/stats", headers=auth(admin_token)).json()

    assert after["total_users"] == before["total_users"] + 1
    assert after["total_tutors"] == before["total_tutors"] + 1
    assert after["approved_tutors"] == before["approved_tutors"] + 1
    assert after["new_users_last_7_days"] >= before["new_users_last_7_days"] + 1
    assert after["total_availability_slots"] >= before["total_availability_slots"]

    client.delete(f"/api/admin/users/{tutor['user_id']}", headers=auth(admin_token))


# --------------------------------------------------------------------------- #
# Users
# --------------------------------------------------------------------------- #
def test_admin_lists_and_filters_users(client, admin_token):
    users = client.get("/api/admin/users", headers=auth(admin_token)).json()
    assert isinstance(users, list)
    assert len(users) >= 19  # seeded demo accounts
    first = users[0]
    assert {"id", "email", "full_name", "role", "is_active", "created_at"} <= set(first)
    assert "password_hash" not in first and "password" not in first

    tutors_only = client.get(
        "/api/admin/users", headers=auth(admin_token), params={"role": "tutor"}
    ).json()
    assert tutors_only and all(u["role"] == "tutor" for u in tutors_only)

    inactive = client.get(
        "/api/admin/users", headers=auth(admin_token), params={"is_active": "false"}
    ).json()
    assert all(u["is_active"] is False for u in inactive)

    searched = client.get(
        "/api/admin/users", headers=auth(admin_token), params={"q": "admin@example.com"}
    ).json()
    assert any(u["role"] == "admin" for u in searched)


def test_admin_gets_one_user(client, admin_token):
    listing = client.get("/api/admin/users", headers=auth(admin_token)).json()
    user_id = listing[0]["id"]
    single = client.get(f"/api/admin/users/{user_id}", headers=auth(admin_token))
    assert single.status_code == 200
    assert single.json()["id"] == user_id
    assert client.get("/api/admin/users/999999", headers=auth(admin_token)).status_code == 404


def test_admin_creates_a_user(client, admin_token):
    suffix = uuid.uuid4().hex[:8]
    email = f"created.{suffix}@example.com"
    created = client.post(
        "/api/admin/users",
        headers=auth(admin_token),
        params={
            "full_name": "Assistant Admin",
            "email": email,
            "password": "StrongPass123",
            "role": "admin",
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["email"] == email
    assert created.json()["role"] == "admin"

    # the new admin can actually sign in
    signed_in = client.post(
        "/api/auth/login", json={"email": email, "password": "StrongPass123"}
    )
    assert signed_in.status_code == 200
    assert signed_in.json()["user"]["role"] == "admin"

    duplicate = client.post(
        "/api/admin/users",
        headers=auth(admin_token),
        params={"full_name": "Dupe", "email": email, "password": "StrongPass123", "role": "admin"},
    )
    assert duplicate.status_code == 409

    weak = client.post(
        "/api/admin/users",
        headers=auth(admin_token),
        params={"full_name": "Weak", "email": f"weak.{suffix}@example.com", "password": "short", "role": "student"},
    )
    assert weak.status_code == 422

    # passwords are never returned
    assert "password" not in created.json() and "password_hash" not in created.json()


def test_admin_updates_a_user(client, admin_token):
    student = new_student(client)

    updated = client.put(
        f"/api/admin/users/{student['user_id']}",
        headers=auth(admin_token),
        json={"full_name": "Renamed By Admin", "phone": "+2348012345678"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["full_name"] == "Renamed By Admin"
    assert updated.json()["phone"] == "+2348012345678"

    # the student sees the change on their own /auth/me
    me = client.get("/api/auth/me", headers=auth(student["token"])).json()
    assert me["full_name"] == "Renamed By Admin"

    assert client.put(
        "/api/admin/users/999999", headers=auth(admin_token), json={"full_name": "Ghost"}
    ).status_code == 404


def test_admin_suspends_and_restores_a_user(client, admin_token):
    student = new_student(client)

    suspended = client.post(
        f"/api/admin/users/{student['user_id']}/toggle-active", headers=auth(admin_token)
    )
    assert suspended.status_code == 200
    assert suspended.json()["is_active"] is False

    # a suspended account can no longer log in
    blocked = client.post(
        "/api/auth/login", json={"email": f"admin.student.{student['suffix']}@example.com", "password": "ValidPass123"}
    )
    assert blocked.status_code in (401, 403)
    assert "deactivated" in blocked.json()["detail"].lower()

    restored = client.post(
        f"/api/admin/users/{student['user_id']}/toggle-active", headers=auth(admin_token)
    )
    assert restored.json()["is_active"] is True
    allowed = client.post(
        "/api/auth/login", json={"email": f"admin.student.{student['suffix']}@example.com", "password": "ValidPass123"}
    )
    assert allowed.status_code == 200


def test_admin_deletes_a_user(client, admin_token):
    student = new_student(client)
    deleted = client.delete(
        f"/api/admin/users/{student['user_id']}", headers=auth(admin_token)
    )
    assert deleted.status_code == 200
    assert client.get(
        f"/api/admin/users/{student['user_id']}", headers=auth(admin_token)
    ).status_code == 404


def test_admin_cannot_delete_themselves(client, admin_token):
    me = client.get("/api/auth/me", headers=auth(admin_token)).json()
    response = client.delete(f"/api/admin/users/{me['id']}", headers=auth(admin_token))
    assert response.status_code == 400
    assert "your own account" in response.json()["detail"].lower()

    # the admin is still able to sign in afterwards
    assert client.get("/api/auth/me", headers=auth(admin_token)).status_code == 200


# --------------------------------------------------------------------------- #
# Tutor moderation
# --------------------------------------------------------------------------- #
def test_pending_tutors_are_hidden_from_public_search(client, admin_token):
    """The demo dataset ships one unapproved tutor; it must not be discoverable."""
    pending = client.get(
        "/api/admin/tutors", headers=auth(admin_token), params={"approval_status": "pending"}
    ).json()
    assert pending["total"] >= 1
    hidden = pending["items"][0]

    assert client.get("/api/tutors", params={"q": hidden["full_name"]}).json()["total"] == 0
    assert client.get(f"/api/tutors/{hidden['id']}").status_code in (403, 404)

    # admins can still read the hidden profile for moderation
    assert client.get(
        f"/api/tutors/{hidden['id']}", headers=auth(admin_token)
    ).status_code == 200


def test_self_registered_tutors_are_visible_immediately(client, admin_token):
    """Public sign-ups are auto-approved so tutors can start receiving requests."""
    tutor = new_tutor(client)

    public = client.get("/api/tutors", params={"q": f"Adminmod {tutor['suffix']}"}).json()
    assert public["total"] == 1
    assert public["items"][0]["approval_status"] == "approved"

    client.delete(f"/api/admin/users/{tutor['user_id']}", headers=auth(admin_token))


def test_admin_approves_a_tutor(client, admin_token):
    tutor = new_tutor(client)

    approved = client.put(
        f"/api/tutors/{tutor['profile_id']}/status",
        headers=auth(admin_token),
        json={"approval_status": "approved", "verified": True},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["approval_status"] == "approved"
    assert approved.json()["verified"] is True

    # now discoverable by everyone
    public = client.get("/api/tutors", params={"q": f"Adminmod {tutor['suffix']}"}).json()
    assert public["total"] == 1
    assert public["items"][0]["verified"] is True
    assert client.get(f"/api/tutors/{tutor['profile_id']}").status_code == 200

    client.delete(f"/api/admin/users/{tutor['user_id']}", headers=auth(admin_token))


def test_admin_suspends_an_approved_tutor(client, admin_token):
    tutor = new_tutor(client)
    client.put(
        f"/api/tutors/{tutor['profile_id']}/status",
        headers=auth(admin_token),
        json={"approval_status": "approved"},
    )

    suspended = client.put(
        f"/api/tutors/{tutor['profile_id']}/status",
        headers=auth(admin_token),
        json={"approval_status": "suspended", "reason": "Unverified qualifications"},
    )
    assert suspended.status_code == 200
    assert suspended.json()["approval_status"] == "suspended"

    assert client.get("/api/tutors", params={"q": f"Adminmod {tutor['suffix']}"}).json()["total"] == 0
    assert "suspended" in [
        t["approval_status"]
        for t in client.get(
            "/api/admin/tutors", headers=auth(admin_token), params={"approval_status": "suspended"}
        ).json()["items"]
        if t["id"] == tutor["profile_id"]
    ]

    client.delete(f"/api/admin/users/{tutor['user_id']}", headers=auth(admin_token))


def test_tutor_status_requires_admin(client, tutor_token):
    assert client.put(
        "/api/tutors/1/status", headers=auth(tutor_token), json={"approval_status": "approved"}
    ).status_code == 403


def test_admin_tutor_listing_filters(client, admin_token):
    pending = client.get(
        "/api/admin/tutors", headers=auth(admin_token), params={"approval_status": "pending"}
    ).json()
    assert all(t["approval_status"] == "pending" for t in pending["items"])

    approved = client.get(
        "/api/admin/tutors", headers=auth(admin_token), params={"approval_status": "approved"}
    ).json()
    assert approved["total"] >= 11  # the seeded, approved tutors
    assert all(t["approval_status"] == "approved" for t in approved["items"])


# --------------------------------------------------------------------------- #
# Request & review moderation
# --------------------------------------------------------------------------- #
def test_admin_sees_all_requests(client, admin_token):
    listing = client.get("/api/admin/requests", headers=auth(admin_token))
    assert listing.status_code == 200
    body = listing.json()
    assert body["total"] >= 16
    assert {"items", "total", "page", "page_size", "pages"} <= set(body)

    filtered = client.get(
        "/api/admin/requests", headers=auth(admin_token), params={"status": "completed"}
    ).json()
    assert filtered["total"] >= 1
    assert all(r["status"] == "completed" for r in filtered["items"])


def test_admin_cancels_and_deletes_a_request(client, admin_token):
    tutor = new_tutor(client)
    client.put(
        f"/api/tutors/{tutor['profile_id']}/status",
        headers=auth(admin_token),
        json={"approval_status": "approved"},
    )
    client.post(
        "/api/availability",
        headers=auth(tutor["token"]),
        json={"day_of_week": "Monday", "start_time": "16:00", "end_time": "19:00"},
    )
    student = new_student(client)

    created = client.post(
        "/api/requests",
        headers=auth(student["token"]),
        json={
            "tutor_id": tutor["profile_id"],
            "subject_id": 1,
            "preferred_date": bookable_date(0, "16:00").isoformat(),
            "preferred_time": "16:00",
            "budget": 4200,
            "message": "Admin intervention test.",
        },
    )
    assert created.status_code == 201, created.text
    request_id = created.json()["data"]["id"]

    cancelled = client.post(
        f"/api/admin/requests/{request_id}/cancel",
        headers=auth(admin_token),
        params={"reason": "Disputed booking"},
    )
    assert cancelled.status_code == 200, cancelled.text
    assert "cancelled" in cancelled.json()["detail"].lower()

    # both parties see the cancellation
    assert client.get(
        f"/api/requests/{request_id}", headers=auth(student["token"])
    ).json()["status"] == "cancelled"

    deleted = client.delete(f"/api/admin/requests/{request_id}", headers=auth(admin_token))
    assert deleted.status_code == 200
    assert client.get(
        f"/api/requests/{request_id}", headers=auth(student["token"])
    ).status_code == 404

    client.delete(f"/api/admin/users/{tutor['user_id']}", headers=auth(admin_token))


def test_admin_review_listing_and_moderation(client, admin_token):
    listing = client.get("/api/admin/reviews", headers=auth(admin_token)).json()
    assert listing["total"] >= 6
    assert listing["items"][0]["rating"] >= 1

    target = listing["items"][0]["id"]
    hidden = client.post(
        f"/api/admin/reviews/{target}/hide", headers=auth(admin_token), params={"reason": "Abusive language"}
    )
    assert hidden.status_code == 200

    hidden_list = client.get(
        "/api/admin/reviews", headers=auth(admin_token), params={"include_hidden": "true"}
    ).json()
    assert any(r["id"] == target for r in hidden_list["items"])

    assert client.post(
        f"/api/admin/reviews/{target}/restore", headers=auth(admin_token)
    ).status_code == 200

    assert client.post("/api/admin/reviews/999999/hide", headers=auth(admin_token)).status_code == 404


# --------------------------------------------------------------------------- #
# Activity log
# --------------------------------------------------------------------------- #
def test_activity_feed_records_changes(client, admin_token):
    before = client.get("/api/admin/activity", headers=auth(admin_token)).json()
    tutor = new_tutor(client)
    client.put(
        f"/api/tutors/{tutor['profile_id']}/status",
        headers=auth(admin_token),
        json={"approval_status": "approved"},
    )
    after = client.get("/api/admin/activity", headers=auth(admin_token)).json()

    assert len(after) >= len(before)
    assert {"id", "action", "description", "actor_name", "created_at"} <= set(after[0])
    assert any("approved" in entry["action"] for entry in after)

    filtered = client.get(
        "/api/admin/activity", headers=auth(admin_token), params={"action": "tutor_approved"}
    ).json()
    assert all(entry["action"] == "tutor_approved" for entry in filtered)

    limited = client.get("/api/admin/activity", headers=auth(admin_token), params={"limit": 2}).json()
    assert len(limited) <= 2

    client.delete(f"/api/admin/users/{tutor['user_id']}", headers=auth(admin_token))


# --------------------------------------------------------------------------- #
# Subject administration
# --------------------------------------------------------------------------- #
def test_admin_creates_updates_and_deletes_a_subject(client, admin_token):
    suffix = uuid.uuid4().hex[:6]
    created = client.post(
        "/api/subjects",
        headers=auth(admin_token),
        json={"name": f"Quantum Weaving {suffix}", "category": "Sciences", "icon": "🧬"},
    )
    assert created.status_code == 201, created.text
    subject_id = created.json()["data"]["id"]

    public = client.get("/api/subjects", params={"q": f"Quantum Weaving {suffix}"}).json()
    assert public["total"] == 1

    renamed = client.put(
        f"/api/subjects/{subject_id}",
        headers=auth(admin_token),
        json={"name": f"Quantum Weaving II {suffix}", "category": "Sciences"},
    )
    assert renamed.status_code == 200
    assert f"Quantum Weaving II {suffix}" in renamed.json()["detail"]
    assert client.get("/api/subjects", params={"q": f"Quantum Weaving II {suffix}"}).json()["total"] == 1

    duplicate = client.post(
        "/api/subjects",
        headers=auth(admin_token),
        json={"name": f"Quantum Weaving II {suffix}", "category": "Sciences"},
    )
    assert duplicate.status_code == 409

    deleted = client.delete(f"/api/subjects/{subject_id}", headers=auth(admin_token))
    assert deleted.status_code == 200
    assert client.get("/api/subjects", params={"q": f"Quantum Weaving II {suffix}"}).json()["total"] == 0


def test_subject_writes_require_admin(client, tutor_token, student_token):
    payload = {"name": "Hacking 101", "category": "Tech"}
    for token in (tutor_token, student_token):
        assert client.post("/api/subjects", headers=auth(token), json=payload).status_code == 403
        assert client.put("/api/subjects/1", headers=auth(token), json=payload).status_code == 403
        assert client.delete("/api/subjects/1", headers=auth(token)).status_code == 403
    assert client.post("/api/subjects", json=payload).status_code in (401, 403)


def test_subject_in_use_is_soft_hidden_not_deleted(client, admin_token, db):
    """A subject attached to tutor profiles is hidden, never hard-deleted.

    Hard-deleting would orphan TutorSubject/BookingRequest rows, so the API
    deactivates it instead and keeps referential integrity intact.
    """
    from models import Subject, TutorSubject
    from sqlalchemy import func, select

    listing = client.get("/api/subjects", params={"q": "Mathematics"}).json()["items"]
    maths = [s for s in listing if s["name"] == "Mathematics"][0]
    assert maths["tutor_count"] > 0

    response = client.delete(f"/api/subjects/{maths['id']}", headers=auth(admin_token))
    assert response.status_code == 200
    assert "hidden" in response.json()["detail"].lower()

    # gone from the public picker ...
    assert all(s["name"] != "Mathematics" for s in client.get("/api/subjects").json()["items"])

    # ... but the row and its links still exist
    db.expire_all()
    row = db.get(Subject, maths["id"])
    assert row is not None
    assert row.is_active is False
    assert db.scalar(
        select(func.count(TutorSubject.id)).where(TutorSubject.subject_id == maths["id"])
    ) == maths["tutor_count"]

    # existing tutor profiles still render with the subject attached
    tutor = client.get("/api/tutors/1").json()
    assert any(s["name"] == "Mathematics" for s in tutor["subjects"])

    # restore it so the rest of the suite sees the normal dataset
    row.is_active = True
    db.commit()
    assert any(s["name"] == "Mathematics" for s in client.get("/api/subjects").json()["items"])
