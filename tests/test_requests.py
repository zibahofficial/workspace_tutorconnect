"""Booking request lifecycle: create → accept/reject → complete → cancel."""
from __future__ import annotations

import uuid

import pytest
from conftest import auth, bookable_date, next_weekday


@pytest.fixture()
def fresh_tutor(client):
    """A brand-new tutor with one Monday 16:00-19:00 slot teaching Mathematics."""
    suffix = uuid.uuid4().hex[:8]
    register = client.post(
        "/api/auth/register",
        json={
            "full_name": f"Booking Tutor {suffix}",
            "email": f"booking.{suffix}@example.com",
            "password": "ValidPass123",
            "role": "tutor",
            "headline": f"Booking lifecycle tutor {suffix}",
            "bio": "Created by the automated test-suite to exercise the booking workflow.",
            "years_experience": 4,
            "hourly_rate": 5000,
            "city": "Yaba",
            "state": "Lagos State",
            "subject_ids": [1],
        },
    )
    assert register.status_code == 201, register.text
    token = register.json()["access_token"]
    profile_id = register.json()["user"]["tutor_profile_id"]

    client.post(
        "/api/availability",
        headers=auth(token),
        json={"day_of_week": "Monday", "start_time": "16:00", "end_time": "19:00", "mode": "hybrid"},
    )
    return {"token": token, "profile_id": profile_id, "subject_id": 1, "rate": 5000}


@pytest.fixture()
def fresh_student(client):
    suffix = uuid.uuid4().hex[:8]
    register = client.post(
        "/api/auth/register",
        json={
            "full_name": f"Booking Student {suffix}",
            "email": f"student.{suffix}@example.com",
            "password": "ValidPass123",
            "role": "student",
            "city": "Yaba",
            "state": "Lagos State",
        },
    )
    assert register.status_code == 201, register.text
    return {"token": register.json()["access_token"], "id": register.json()["user"]["id"]}


def create_request(client, student_token, tutor, **overrides):
    payload = {
        "tutor_id": tutor["profile_id"],
        "subject_id": tutor["subject_id"],
        "preferred_date": bookable_date(0, "16:00").isoformat(),
        "preferred_time": "16:00",
        "duration_minutes": 60,
        "mode": "hybrid",
        "budget": float(tutor["rate"]),
        "message": "I would like to improve my mathematics grade before the exams.",
    }
    payload.update(overrides)
    return client.post("/api/requests", headers=auth(student_token), json=payload)


# --------------------------------------------------------------------------- #
# CREATE + validation
# --------------------------------------------------------------------------- #
def test_create_request_pending(client, fresh_tutor, fresh_student):
    response = create_request(client, fresh_student["token"], fresh_tutor)
    assert response.status_code == 201, response.text
    data = response.json()["data"]
    assert data["status"] == "pending"
    assert data["tutor"]["id"] == fresh_tutor["profile_id"]
    assert data["student"]["id"] == fresh_student["id"] or data["student"]["name"]
    assert data["subject_name"] == "Mathematics"
    assert data["budget"] == 5000
    assert data["session_label"]


def test_create_request_validation_errors(client, fresh_tutor, fresh_student):
    token = fresh_student["token"]

    unknown_tutor = create_request(client, token, fresh_tutor, tutor_id=999999)
    assert unknown_tutor.status_code == 404

    past_date = create_request(client, token, fresh_tutor, preferred_date="2020-01-06")
    assert past_date.status_code == 422

    bad_time_increment = create_request(client, token, fresh_tutor, preferred_time="16:07")
    assert bad_time_increment.status_code == 422

    subject_not_taught = create_request(client, token, fresh_tutor, subject_id=999)
    assert subject_not_taught.status_code == 404

    real_subject_not_taught = create_request(client, token, fresh_tutor, subject_id=6)
    assert real_subject_not_taught.status_code == 400
    assert "does not teach" in real_subject_not_taught.json()["detail"]

    negative_budget = create_request(client, token, fresh_tutor, budget=-100)
    assert negative_budget.status_code == 422


def test_request_outside_availability_needs_consent(client, fresh_tutor, fresh_student):
    refused = create_request(client, fresh_student["token"], fresh_tutor, preferred_time="07:00")
    assert refused.status_code == 409
    assert "not available" in refused.json()["detail"].lower()

    allowed = create_request(
        client, fresh_student["token"], fresh_tutor, preferred_time="07:00", ignore_availability=True
    )
    assert allowed.status_code == 201, allowed.text


def test_duplicate_slot_rejected(client, fresh_tutor, fresh_student):
    first = create_request(client, fresh_student["token"], fresh_tutor)
    assert first.status_code == 201

    second = create_request(client, fresh_student["token"], fresh_tutor)
    assert second.status_code == 409

    # a different time on the same day is fine
    other = create_request(client, fresh_student["token"], fresh_tutor, preferred_time="17:00")
    assert other.status_code == 201


def test_tutor_cannot_be_own_student(client, fresh_tutor):
    response = create_request(client, fresh_tutor["token"], fresh_tutor)
    assert response.status_code == 403  # role guard: tutors cannot POST /requests


def test_tutors_cannot_create_requests(client, fresh_tutor):
    response = client.post(
        "/api/requests",
        headers=auth(fresh_tutor["token"]),
        json={
            "tutor_id": fresh_tutor["profile_id"],
            "subject_id": 1,
            "preferred_date": bookable_date(0, "16:00").isoformat(),
            "preferred_time": "16:00",
            "budget": 5000,
        },
    )
    assert response.status_code == 403


# --------------------------------------------------------------------------- #
# READ
# --------------------------------------------------------------------------- #
def test_request_visibility_is_scoped(client, fresh_tutor, fresh_student):
    created = create_request(client, fresh_student["token"], fresh_tutor).json()["data"]

    mine = client.get(f"/api/requests/{created['id']}", headers=auth(fresh_student["token"]))
    assert mine.status_code == 200

    tutors = client.get(f"/api/requests/{created['id']}", headers=auth(fresh_tutor["token"]))
    assert tutors.status_code == 200

    stranger = client.post(
        "/api/auth/register",
        json={
            "full_name": "Nosy Student",
            "email": f"nosy.{uuid.uuid4().hex[:8]}@example.com",
            "password": "ValidPass123",
            "role": "student",
        },
    ).json()
    blocked = client.get(
        f"/api/requests/{created['id']}", headers=auth(stranger["access_token"])
    )
    assert blocked.status_code == 403

    anonymous = client.get(f"/api/requests/{created['id']}")
    assert anonymous.status_code in (401, 403)


def test_list_requests_by_status(client, fresh_tutor, fresh_student):
    create_request(client, fresh_student["token"], fresh_tutor)
    listing = client.get("/api/requests", headers=auth(fresh_student["token"]))
    assert listing.status_code == 200
    assert listing.json()["total"] >= 1
    assert listing.json()["counts"]["pending"] >= 1

    filtered = client.get(
        "/api/requests", headers=auth(fresh_student["token"]), params={"status": "completed"}
    )
    assert filtered.status_code == 200
    assert filtered.json()["total"] == 0


def test_missing_request_404(client, fresh_student):
    response = client.get("/api/requests/999999", headers=auth(fresh_student["token"]))
    assert response.status_code == 404


# --------------------------------------------------------------------------- #
# UPDATE — student edits
# --------------------------------------------------------------------------- #
def test_student_can_edit_pending_request(client, fresh_tutor, fresh_student):
    created = create_request(client, fresh_student["token"], fresh_tutor).json()["data"]

    updated = client.put(
        f"/api/requests/{created['id']}",
        headers=auth(fresh_student["token"]),
        json={"budget": 6500, "message": "I can pay a little more for a longer session.",
              "preferred_time": "17:00"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["data"]["budget"] == 6500
    assert updated.json()["data"]["preferred_time"] == "17:00"

    outside = client.put(
        f"/api/requests/{created['id']}",
        headers=auth(fresh_student["token"]),
        json={"preferred_time": "06:00"},
    )
    assert outside.status_code == 409

    empty = client.put(
        f"/api/requests/{created['id']}", headers=auth(fresh_student["token"]), json={}
    )
    assert empty.status_code == 400


def test_student_cannot_edit_after_acceptance(client, fresh_tutor, fresh_student):
    created = create_request(client, fresh_student["token"], fresh_tutor).json()["data"]
    client.put(
        f"/api/requests/{created['id']}/status",
        headers=auth(fresh_tutor["token"]),
        json={"status": "accepted"},
    )

    response = client.put(
        f"/api/requests/{created['id']}",
        headers=auth(fresh_student["token"]),
        json={"budget": 1},
    )
    assert response.status_code == 409


# --------------------------------------------------------------------------- #
# UPDATE — tutor decisions
# --------------------------------------------------------------------------- #
def test_accept_request_and_student_sees_status(client, fresh_tutor, fresh_student):
    created = create_request(client, fresh_student["token"], fresh_tutor).json()["data"]

    accepted = client.put(
        f"/api/requests/{created['id']}/status",
        headers=auth(fresh_tutor["token"]),
        json={"status": "accepted", "note": "Confirmed — see you Monday!"},
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["data"]["status"] == "accepted"
    assert accepted.json()["data"]["tutor_response_note"] == "Confirmed — see you Monday!"

    # the student sees the updated status immediately
    viewed = client.get(f"/api/requests/{created['id']}", headers=auth(fresh_student["token"]))
    assert viewed.json()["status"] == "accepted"

    # student received a notification
    notes = client.get("/api/notifications", headers=auth(fresh_student["token"])).json()
    assert any(n["type"] == "request_accepted" for n in notes["items"])

    # cannot accept twice
    again = client.put(
        f"/api/requests/{created['id']}/status",
        headers=auth(fresh_tutor["token"]),
        json={"status": "accepted"},
    )
    assert again.status_code == 409


def test_reject_request(client, fresh_tutor, fresh_student):
    created = create_request(client, fresh_student["token"], fresh_tutor).json()["data"]

    rejected = client.put(
        f"/api/requests/{created['id']}/status",
        headers=auth(fresh_tutor["token"]),
        json={"status": "rejected", "note": "Fully booked this term."},
    )
    assert rejected.status_code == 200
    assert rejected.json()["data"]["status"] == "rejected"

    viewed = client.get(f"/api/requests/{created['id']}", headers=auth(fresh_student["token"]))
    assert viewed.json()["status"] == "rejected"

    again = client.put(
        f"/api/requests/{created['id']}/status",
        headers=auth(fresh_tutor["token"]),
        json={"status": "accepted"},
    )
    assert again.status_code == 409


def test_students_cannot_decide(client, fresh_tutor, fresh_student):
    created = create_request(client, fresh_student["token"], fresh_tutor).json()["data"]
    response = client.put(
        f"/api/requests/{created['id']}/status",
        headers=auth(fresh_student["token"]),
        json={"status": "accepted"},
    )
    assert response.status_code == 403


def test_another_tutor_cannot_decide(client, fresh_tutor, fresh_student, tutor2_token):
    created = create_request(client, fresh_student["token"], fresh_tutor).json()["data"]
    response = client.put(
        f"/api/requests/{created['id']}/status",
        headers=auth(tutor2_token),
        json={"status": "accepted"},
    )
    assert response.status_code == 403


def test_conflicting_acceptance_blocked(client, fresh_tutor, fresh_student):
    first = create_request(client, fresh_student["token"], fresh_tutor, preferred_time="16:00").json()["data"]
    # second request overlapping the first (90 minutes from 16:30 overlaps 16:00-17:00)
    second = create_request(
        client, fresh_student["token"], fresh_tutor,
        preferred_time="16:30", duration_minutes=30, ignore_availability=True,
    )
    assert second.status_code in (201, 409)

    client.put(
        f"/api/requests/{first['id']}/status",
        headers=auth(fresh_tutor["token"]),
        json={"status": "accepted"},
    )

    if second.status_code == 201:
        clash = client.put(
            f"/api/requests/{second.json()['data']['id']}/status",
            headers=auth(fresh_tutor["token"]),
            json={"status": "accepted"},
        )
        assert clash.status_code == 409


# --------------------------------------------------------------------------- #
# COMPLETE + cancel
# --------------------------------------------------------------------------- #
def test_full_lifecycle_accept_then_complete(client, fresh_tutor, fresh_student):
    target = bookable_date(0, "16:00")
    created = create_request(
        client, fresh_student["token"], fresh_tutor, preferred_date=target.isoformat()
    ).json()["data"]

    too_early = client.put(
        f"/api/requests/{created['id']}/status",
        headers=auth(fresh_tutor["token"]),
        json={"status": "completed"},
    )
    assert too_early.status_code == 409  # not accepted yet

    client.put(
        f"/api/requests/{created['id']}/status",
        headers=auth(fresh_tutor["token"]),
        json={"status": "accepted"},
    )

    # a session that has not happened yet cannot be marked complete
    future = client.put(
        f"/api/requests/{created['id']}/status",
        headers=auth(fresh_tutor["token"]),
        json={"status": "completed"},
    )
    assert future.status_code == 400, "future sessions must not be completable"


def test_completed_session_unlocks_review(client, fresh_tutor, fresh_student, db):
    """Move the accepted booking into the past at DB level, then complete it."""
    from datetime import datetime, time as dtime, timezone

    from models import BookingRequest

    target = bookable_date(0, "16:00")
    created = create_request(
        client, fresh_student["token"], fresh_tutor, preferred_date=target.isoformat()
    ).json()["data"]
    request_id = created["id"]

    client.put(
        f"/api/requests/{request_id}/status",
        headers=auth(fresh_tutor["token"]),
        json={"status": "accepted"},
    )

    # simulate the session having already happened
    from conftest import past_weekday

    db.expire_all()
    row = db.get(BookingRequest, request_id)
    row.preferred_date = past_weekday(0)
    db.commit()

    completed = client.put(
        f"/api/requests/{request_id}/status",
        headers=auth(fresh_tutor["token"]),
        json={"status": "completed"},
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["data"]["status"] == "completed"
    assert completed.json()["data"]["completed_at"]

    student_view = client.get(f"/api/requests/{request_id}", headers=auth(fresh_student["token"]))
    assert student_view.json()["status"] == "completed"
    assert student_view.json()["can_review"] is True

    review = client.post(
        "/api/reviews",
        headers=auth(fresh_student["token"]),
        json={"booking_request_id": request_id, "rating": 5, "title": "Excellent", "comment": "Very clear explanations."},
    )
    assert review.status_code == 201, review.text
    assert review.json()["data"]["tutor_rating"]["review_count"] >= 1

    # cannot review twice
    twice = client.post(
        "/api/reviews",
        headers=auth(fresh_student["token"]),
        json={"booking_request_id": request_id, "rating": 4},
    )
    assert twice.status_code == 409

    # once reviewed, can_review flips off
    again = client.get(f"/api/requests/{request_id}", headers=auth(fresh_student["token"]))
    assert again.json()["can_review"] is False
    assert again.json()["has_review"] is True


def test_student_cancels_pending_and_accepted(client, fresh_tutor, fresh_student):
    pending = create_request(client, fresh_student["token"], fresh_tutor, preferred_time="16:00").json()["data"]
    cancelled = client.post(
        f"/api/requests/{pending['id']}/cancel",
        headers=auth(fresh_student["token"]),
        json={"reason": "Something came up at school."},
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["data"]["status"] == "cancelled"
    assert cancelled.json()["data"]["cancel_reason"] == "Something came up at school."

    again = client.post(
        f"/api/requests/{pending['id']}/cancel", headers=auth(fresh_student["token"]), json={}
    )
    assert again.status_code == 409

    accepted = create_request(client, fresh_student["token"], fresh_tutor, preferred_time="17:00").json()["data"]
    client.put(
        f"/api/requests/{accepted['id']}/status",
        headers=auth(fresh_tutor["token"]),
        json={"status": "accepted"},
    )
    student_cancel = client.post(
        f"/api/requests/{accepted['id']}/cancel",
        headers=auth(fresh_student["token"]),
        json={"reason": "Family emergency"},
    )
    assert student_cancel.status_code == 200
    assert student_cancel.json()["data"]["status"] == "cancelled"

    tutor_view = client.get(
        f"/api/requests/{accepted['id']}", headers=auth(fresh_tutor["token"])
    )
    assert tutor_view.json()["status"] == "cancelled"


def test_tutor_can_cancel_accepted_session(client, fresh_tutor, fresh_student):
    created = create_request(client, fresh_student["token"], fresh_tutor).json()["data"]
    client.put(
        f"/api/requests/{created['id']}/status",
        headers=auth(fresh_tutor["token"]),
        json={"status": "accepted"},
    )
    response = client.put(
        f"/api/requests/{created['id']}/status",
        headers=auth(fresh_tutor["token"]),
        json={"status": "cancelled", "note": "Unavoidable schedule clash."},
    )
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "cancelled"


# --------------------------------------------------------------------------- #
# DELETE
# --------------------------------------------------------------------------- #
def test_delete_rules(client, fresh_tutor, fresh_student):
    pending = create_request(client, fresh_student["token"], fresh_tutor, preferred_time="16:00").json()["data"]

    blocked = client.delete(f"/api/requests/{pending['id']}", headers=auth(fresh_student["token"]))
    assert blocked.status_code == 409  # active requests must be cancelled, not deleted

    client.post(f"/api/requests/{pending['id']}/cancel", headers=auth(fresh_student["token"]), json={})
    deleted = client.delete(f"/api/requests/{pending['id']}", headers=auth(fresh_student["token"]))
    assert deleted.status_code == 200

    gone = client.get(f"/api/requests/{pending['id']}", headers=auth(fresh_student["token"]))
    assert gone.status_code == 404


def test_tutors_cannot_delete_requests(client, fresh_tutor, fresh_student):
    created = create_request(client, fresh_student["token"], fresh_tutor).json()["data"]
    response = client.delete(f"/api/requests/{created['id']}", headers=auth(fresh_tutor["token"]))
    assert response.status_code == 403


def test_mark_request_read(client, fresh_tutor, fresh_student):
    created = create_request(client, fresh_student["token"], fresh_tutor).json()["data"]
    response = client.post(f"/api/requests/{created['id']}/read", headers=auth(fresh_tutor["token"]))
    assert response.status_code == 200


def test_upcoming_sessions_list(client, fresh_tutor, fresh_student):
    created = create_request(client, fresh_student["token"], fresh_tutor).json()["data"]
    client.put(
        f"/api/requests/{created['id']}/status",
        headers=auth(fresh_tutor["token"]),
        json={"status": "accepted"},
    )

    tutor_upcoming = client.get("/api/requests/upcoming/list", headers=auth(fresh_tutor["token"]))
    assert tutor_upcoming.status_code == 200
    assert any(r["id"] == created["id"] for r in tutor_upcoming.json())

    student_upcoming = client.get("/api/requests/upcoming/list", headers=auth(fresh_student["token"]))
    assert any(r["id"] == created["id"] for r in student_upcoming.json())


def test_student_dashboard_stats(client, fresh_tutor, fresh_student):
    create_request(client, fresh_student["token"], fresh_tutor)
    stats = client.get("/api/requests/mine/stats", headers=auth(fresh_student["token"]))
    assert stats.status_code == 200
    body = stats.json()
    assert body["total_requests"] >= 1
    assert body["pending_requests"] >= 1
    assert body["total_requests"] == (
        body["pending_requests"] + body["accepted_requests"] + body["rejected_requests"]
        + body["cancelled_requests"] + body["completed_sessions"]
    )


def test_notifications_created_for_both_parties(client, fresh_tutor, fresh_student):
    create_request(client, fresh_student["token"], fresh_tutor)

    tutor_notes = client.get("/api/notifications", headers=auth(fresh_tutor["token"])).json()
    assert any(n["type"] == "request_new" for n in tutor_notes["items"])
    assert tutor_notes["unread_count"] >= 1

    student_notes = client.get("/api/notifications", headers=auth(fresh_student["token"])).json()
    assert any(n["type"] == "request_new" for n in student_notes["items"])

    # mark all read clears the counter
    client.post("/api/notifications/read-all", headers=auth(fresh_tutor["token"]))
    assert client.get("/api/notifications/unread-count", headers=auth(fresh_tutor["token"])).json()["unread_count"] == 0
