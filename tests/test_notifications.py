"""Notifications: creation across the workflow, read state and deletion."""
from __future__ import annotations

import uuid

from conftest import auth, bookable_date


def new_student(client) -> dict:
    suffix = uuid.uuid4().hex[:8]
    body = client.post(
        "/api/auth/register",
        json={
            "full_name": f"Notify Student {suffix}",
            "email": f"notify.{suffix}@example.com",
            "password": "ValidPass123",
            "role": "student",
        },
    ).json()
    return {"token": body["access_token"], "id": body["user"]["id"]}


def new_tutor(client) -> dict:
    suffix = uuid.uuid4().hex[:8]
    body = client.post(
        "/api/auth/register",
        json={
            "full_name": f"Notify Tutor {suffix}",
            "email": f"notify.tutor.{suffix}@example.com",
            "password": "ValidPass123",
            "role": "tutor",
            "headline": f"Notification tutor {suffix}",
            "bio": "Created by the automated test-suite to exercise notifications.",
            "years_experience": 5,
            "hourly_rate": 5500,
            "city": "Wuse",
            "state": "Federal Capital Territory",
            "subject_ids": [1],
        },
    ).json()
    token = body["access_token"]
    tutor_id = body["user"]["tutor_profile_id"]
    client.post(
        "/api/availability",
        headers=auth(token),
        json={"day_of_week": "Monday", "start_time": "16:00", "end_time": "19:00"},
    )
    return {"token": token, "id": tutor_id}


def types_for(client, token) -> list[str]:
    return [n["type"] for n in client.get("/api/notifications", headers=auth(token)).json()["items"]]


def test_notifications_require_auth(client):
    assert client.get("/api/notifications").status_code in (401, 403)
    assert client.get("/api/notifications/unread-count").status_code in (401, 403)


def test_booking_lifecycle_creates_notifications(client):
    tutor = new_tutor(client)
    student = new_student(client)

    created = client.post(
        "/api/requests",
        headers=auth(student["token"]),
        json={
            "tutor_id": tutor["id"],
            "subject_id": 1,
            "preferred_date": bookable_date(0, "16:00").isoformat(),
            "preferred_time": "16:00",
            "budget": 5500,
            "message": "Notification flow test.",
        },
    )
    assert created.status_code == 201, created.text
    request_id = created.json()["data"]["id"]

    # tutor hears about the new request, student gets a confirmation
    assert "request_new" in types_for(client, tutor["token"])
    assert "request_new" in types_for(client, student["token"])

    tutor_unread = client.get("/api/notifications/unread-count", headers=auth(tutor["token"])).json()
    assert tutor_unread["unread_count"] >= 1

    client.put(
        f"/api/requests/{request_id}/status",
        headers=auth(tutor["token"]),
        json={"status": "accepted"},
    )
    assert "request_accepted" in types_for(client, student["token"])

    client.post(
        f"/api/requests/{request_id}/cancel", headers=auth(student["token"]), json={"reason": "Plans changed"}
    )
    assert "request_cancelled" in types_for(client, tutor["token"])


def test_rejection_notifies_the_student(client):
    tutor = new_tutor(client)
    student = new_student(client)
    request_id = client.post(
        "/api/requests",
        headers=auth(student["token"]),
        json={
            "tutor_id": tutor["id"],
            "subject_id": 1,
            "preferred_date": bookable_date(0, "16:00").isoformat(),
            "preferred_time": "16:00",
            "budget": 5500,
            "message": "Rejection notification test.",
        },
    ).json()["data"]["id"]

    client.put(
        f"/api/requests/{request_id}/status",
        headers=auth(tutor["token"]),
        json={"status": "rejected", "note": "Fully booked."},
    )
    notes = client.get("/api/notifications", headers=auth(student["token"])).json()["items"]
    rejected = [n for n in notes if n["type"] == "request_rejected"]
    assert rejected
    assert rejected[0]["link"]


def test_notification_payload_shape(client):
    tutor = new_tutor(client)
    student = new_student(client)
    client.post(
        "/api/requests",
        headers=auth(student["token"]),
        json={
            "tutor_id": tutor["id"],
            "subject_id": 1,
            "preferred_date": bookable_date(0, "16:00").isoformat(),
            "preferred_time": "16:00",
            "budget": 5500,
            "message": "Payload shape test.",
        },
    )

    body = client.get("/api/notifications", headers=auth(tutor["token"])).json()
    assert set(body) == {"items", "unread_count"}
    note = body["items"][0]
    assert {"id", "type", "title", "is_read", "created_at"} <= set(note)
    assert note["title"]
    assert note["is_read"] is False
    # newest first
    stamps = [n["created_at"] for n in body["items"]]
    assert stamps == sorted(stamps, reverse=True)


def test_unread_only_filter_and_limit(client):
    tutor = new_tutor(client)
    token = tutor["token"]

    all_notes = client.get("/api/notifications", headers=auth(token)).json()["items"]
    unread = client.get("/api/notifications", headers=auth(token), params={"unread_only": "true"}).json()["items"]
    assert len(unread) == len([n for n in all_notes if not n["is_read"]])

    limited = client.get("/api/notifications", headers=auth(token), params={"limit": 1}).json()
    assert len(limited["items"]) == 1


def test_mark_one_read(client):
    tutor = new_tutor(client)
    student = new_student(client)
    client.post(
        "/api/requests",
        headers=auth(student["token"]),
        json={
            "tutor_id": tutor["id"],
            "subject_id": 1,
            "preferred_date": bookable_date(0, "16:00").isoformat(),
            "preferred_time": "16:00",
            "budget": 5500,
            "message": "Read-state test.",
        },
    )

    notes = client.get("/api/notifications", headers=auth(tutor["token"])).json()
    target = [n for n in notes["items"] if n["type"] == "request_new"][0]

    response = client.post(f"/api/notifications/{target['id']}/read", headers=auth(tutor["token"]))
    assert response.status_code == 200

    refreshed = client.get("/api/notifications", headers=auth(tutor["token"])).json()
    assert [n for n in refreshed["items"] if n["id"] == target["id"]][0]["is_read"] is True
    assert refreshed["unread_count"] == notes["unread_count"] - 1


def test_mark_all_read(client):
    tutor = new_tutor(client)
    student = new_student(client)
    for hour in ("16:00", "17:00"):
        client.post(
            "/api/requests",
            headers=auth(student["token"]),
            json={
                "tutor_id": tutor["id"],
                "subject_id": 1,
                "preferred_date": bookable_date(0, "16:00").isoformat(),
                "preferred_time": hour,
                "budget": 5500,
                "message": "Bulk read test.",
            },
        )

    assert client.get("/api/notifications/unread-count", headers=auth(tutor["token"])).json()["unread_count"] >= 2
    response = client.post("/api/notifications/read-all", headers=auth(tutor["token"]))
    assert response.status_code == 200
    assert client.get("/api/notifications/unread-count", headers=auth(tutor["token"])).json()["unread_count"] == 0


def test_delete_notification(client):
    tutor = new_tutor(client)
    student = new_student(client)
    client.post(
        "/api/requests",
        headers=auth(student["token"]),
        json={
            "tutor_id": tutor["id"],
            "subject_id": 1,
            "preferred_date": bookable_date(0, "16:00").isoformat(),
            "preferred_time": "16:00",
            "budget": 5500,
            "message": "Delete test.",
        },
    )
    note_id = client.get("/api/notifications", headers=auth(tutor["token"])).json()["items"][0]["id"]

    assert client.delete(f"/api/notifications/{note_id}", headers=auth(tutor["token"])).status_code == 200
    remaining = client.get("/api/notifications", headers=auth(tutor["token"])).json()["items"]
    assert all(n["id"] != note_id for n in remaining)

    assert client.delete(f"/api/notifications/{note_id}", headers=auth(tutor["token"])).status_code == 404


def test_notifications_are_private(client):
    tutor = new_tutor(client)
    student = new_student(client)
    client.post(
        "/api/requests",
        headers=auth(student["token"]),
        json={
            "tutor_id": tutor["id"],
            "subject_id": 1,
            "preferred_date": bookable_date(0, "16:00").isoformat(),
            "preferred_time": "16:00",
            "budget": 5500,
            "message": "Privacy test.",
        },
    )
    note_id = client.get("/api/notifications", headers=auth(tutor["token"])).json()["items"][0]["id"]

    # another user cannot read or delete someone else's notification
    assert client.post(f"/api/notifications/{note_id}/read", headers=auth(student["token"])).status_code == 404
    assert client.delete(f"/api/notifications/{note_id}", headers=auth(student["token"])).status_code == 404


def test_profile_approval_notifies_the_tutor(client, admin_token):
    suffix = uuid.uuid4().hex[:8]
    body = client.post(
        "/api/auth/register",
        json={
            "full_name": f"Pending Tutor {suffix}",
            "email": f"pending.{suffix}@example.com",
            "password": "ValidPass123",
            "role": "tutor",
            "headline": f"Pending tutor {suffix}",
            "bio": "Awaiting moderation in the automated test-suite.",
            "years_experience": 2,
            "hourly_rate": 3500,
            "city": "Yaba",
            "state": "Lagos State",
            "subject_ids": [1],
        },
    ).json()
    token = body["access_token"]
    tutor_id = body["user"]["tutor_profile_id"]

    approved = client.put(
        f"/api/tutors/{tutor_id}/status",
        headers=auth(admin_token),
        json={"approval_status": "approved", "verified": True},
    )
    assert approved.status_code == 200, approved.text

    assert "profile_approved" in types_for(client, token)

    # and suspension too
    client.put(
        f"/api/tutors/{tutor_id}/status",
        headers=auth(admin_token),
        json={"approval_status": "suspended", "reason": "Duplicate profile"},
    )
    assert "profile_suspended" in types_for(client, token)
