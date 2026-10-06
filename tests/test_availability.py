"""Availability CRUD, overlap protection and open-slot computation."""
from __future__ import annotations

import uuid

from conftest import auth, bookable_date


def make_tutor(client) -> dict:
    suffix = uuid.uuid4().hex[:8]
    response = client.post(
        "/api/auth/register",
        json={
            "full_name": f"Avail Tutor {suffix}",
            "email": f"avail.{suffix}@example.com",
            "password": "ValidPass123",
            "role": "tutor",
            "headline": f"Availability test tutor {suffix}",
            "bio": "Tutor created by the automated test-suite for availability coverage.",
            "years_experience": 3,
            "hourly_rate": 4000,
            "city": "Yaba",
            "state": "Lagos State",
            "subject_ids": [1],
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    return {"token": body["access_token"], "profile_id": body["user"]["tutor_profile_id"]}


def test_tutor_starts_with_no_availability(client):
    tutor = make_tutor(client)
    response = client.get("/api/availability/mine", headers=auth(tutor["token"]))
    assert response.status_code == 200
    assert response.json()["items"] == []


def test_create_availability_slot(client):
    tutor = make_tutor(client)
    response = client.post(
        "/api/availability",
        headers=auth(tutor["token"]),
        json={"day_of_week": "Monday", "start_time": "16:00", "end_time": "19:00", "mode": "hybrid"},
    )
    assert response.status_code == 201, response.text
    slot = response.json()["data"]
    assert slot["day_of_week"] == "Monday"
    assert slot["start_time"] == "16:00"
    assert slot["end_time"] == "19:00"
    assert slot["day_index"] == 0
    assert "Monday" in slot["label"]

    listing = client.get("/api/availability/mine", headers=auth(tutor["token"])).json()
    assert len(listing["items"]) == 1


def test_availability_rejects_bad_times(client):
    tutor = make_tutor(client)

    end_before_start = client.post(
        "/api/availability",
        headers=auth(tutor["token"]),
        json={"day_of_week": "Monday", "start_time": "19:00", "end_time": "16:00"},
    )
    assert end_before_start.status_code == 422

    too_short = client.post(
        "/api/availability",
        headers=auth(tutor["token"]),
        json={"day_of_week": "Monday", "start_time": "16:00", "end_time": "16:15"},
    )
    assert too_short.status_code == 422

    bad_day = client.post(
        "/api/availability",
        headers=auth(tutor["token"]),
        json={"day_of_week": "Funday", "start_time": "16:00", "end_time": "18:00"},
    )
    assert bad_day.status_code == 422


def test_overlapping_slots_are_rejected(client):
    tutor = make_tutor(client)
    client.post(
        "/api/availability",
        headers=auth(tutor["token"]),
        json={"day_of_week": "Wednesday", "start_time": "16:00", "end_time": "19:00"},
    )

    overlap = client.post(
        "/api/availability",
        headers=auth(tutor["token"]),
        json={"day_of_week": "Wednesday", "start_time": "17:00", "end_time": "20:00"},
    )
    assert overlap.status_code == 409
    assert "overlaps" in overlap.json()["detail"].lower()

    contained = client.post(
        "/api/availability",
        headers=auth(tutor["token"]),
        json={"day_of_week": "Wednesday", "start_time": "17:00", "end_time": "18:00"},
    )
    assert contained.status_code == 409

    # adjacent (touching) slots are allowed
    adjacent = client.post(
        "/api/availability",
        headers=auth(tutor["token"]),
        json={"day_of_week": "Wednesday", "start_time": "19:00", "end_time": "21:00"},
    )
    assert adjacent.status_code == 201, adjacent.text

    # different day never overlaps
    other_day = client.post(
        "/api/availability",
        headers=auth(tutor["token"]),
        json={"day_of_week": "Thursday", "start_time": "16:00", "end_time": "19:00"},
    )
    assert other_day.status_code == 201


def test_duplicate_identical_slot_rejected(client):
    tutor = make_tutor(client)
    payload = {"day_of_week": "Friday", "start_time": "10:00", "end_time": "12:00"}
    assert client.post("/api/availability", headers=auth(tutor["token"]), json=payload).status_code == 201
    second = client.post("/api/availability", headers=auth(tutor["token"]), json=payload)
    assert second.status_code == 409


def test_update_availability_slot(client):
    tutor = make_tutor(client)
    created = client.post(
        "/api/availability",
        headers=auth(tutor["token"]),
        json={"day_of_week": "Monday", "start_time": "16:00", "end_time": "19:00"},
    ).json()["data"]

    updated = client.put(
        f"/api/availability/{created['id']}",
        headers=auth(tutor["token"]),
        json={"start_time": "15:00", "end_time": "18:00", "day_of_week": "Tuesday"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["data"]["start_time"] == "15:00"
    assert updated.json()["data"]["day_of_week"] == "Tuesday"
    assert updated.json()["data"]["day_index"] == 1

    empty = client.put(f"/api/availability/{created['id']}", headers=auth(tutor["token"]), json={})
    assert empty.status_code == 400

    bad = client.put(
        f"/api/availability/{created['id']}",
        headers=auth(tutor["token"]),
        json={"start_time": "20:00", "end_time": "19:00"},
    )
    assert bad.status_code in (400, 422)


def test_update_conflict_with_other_slot(client):
    tutor = make_tutor(client)
    first = client.post(
        "/api/availability",
        headers=auth(tutor["token"]),
        json={"day_of_week": "Monday", "start_time": "09:00", "end_time": "11:00"},
    ).json()["data"]
    client.post(
        "/api/availability",
        headers=auth(tutor["token"]),
        json={"day_of_week": "Monday", "start_time": "14:00", "end_time": "16:00"},
    )

    clash = client.put(
        f"/api/availability/{first['id']}",
        headers=auth(tutor["token"]),
        json={"start_time": "15:00", "end_time": "17:00"},
    )
    assert clash.status_code == 409


def test_toggle_pause_and_resume(client):
    tutor = make_tutor(client)
    slot = client.post(
        "/api/availability",
        headers=auth(tutor["token"]),
        json={"day_of_week": "Saturday", "start_time": "10:00", "end_time": "13:00"},
    ).json()["data"]

    paused = client.patch(f"/api/availability/{slot['id']}/toggle", headers=auth(tutor["token"]))
    assert paused.status_code == 200
    assert paused.json()["data"]["is_active"] is False

    public = client.get(f"/api/tutors/{tutor['profile_id']}/availability").json()
    assert all(s["id"] != slot["id"] for s in public["items"]), "paused slots must not be public"

    resumed = client.patch(f"/api/availability/{slot['id']}/toggle", headers=auth(tutor["token"]))
    assert resumed.json()["data"]["is_active"] is True


def test_delete_availability_slot(client):
    tutor = make_tutor(client)
    slot = client.post(
        "/api/availability",
        headers=auth(tutor["token"]),
        json={"day_of_week": "Sunday", "start_time": "14:00", "end_time": "18:00"},
    ).json()["data"]

    deleted = client.delete(f"/api/availability/{slot['id']}", headers=auth(tutor["token"]))
    assert deleted.status_code == 200
    assert "deleted" in deleted.json()["detail"].lower()

    again = client.delete(f"/api/availability/{slot['id']}", headers=auth(tutor["token"]))
    assert again.status_code == 404

    listing = client.get("/api/availability/mine", headers=auth(tutor["token"])).json()
    assert listing["items"] == []


def test_missing_slot_404(client):
    tutor = make_tutor(client)
    assert client.put("/api/availability/999999", headers=auth(tutor["token"]), json={"start_time": "09:00", "end_time": "10:00"}).status_code == 404
    assert client.delete("/api/availability/999999", headers=auth(tutor["token"])).status_code == 404
    assert client.patch("/api/availability/999999/toggle", headers=auth(tutor["token"])).status_code == 404


def test_cannot_touch_another_tutors_slots(client, tutor_token):
    tutor = make_tutor(client)
    slot = client.post(
        "/api/availability",
        headers=auth(tutor["token"]),
        json={"day_of_week": "Monday", "start_time": "16:00", "end_time": "18:00"},
    ).json()["data"]

    assert client.put(f"/api/availability/{slot['id']}", headers=auth(tutor_token), json={"start_time": "07:00", "end_time": "08:00"}).status_code == 403
    assert client.delete(f"/api/availability/{slot['id']}", headers=auth(tutor_token)).status_code == 403
    assert client.patch(f"/api/availability/{slot['id']}/toggle", headers=auth(tutor_token)).status_code == 403


def test_availability_requires_a_profile(client, student_token):
    response = client.get("/api/availability/mine", headers=auth(student_token))
    assert response.status_code == 403  # role guard fires first


def test_public_availability_grouped_by_day(client):
    response = client.get("/api/tutors/1/availability")
    assert response.status_code == 200
    body = response.json()
    assert body["tutor_id"] == 1
    assert len(body["by_day"]) == 7
    assert body["by_day"][0]["day"] == "Monday"
    assert any(day["available"] for day in body["by_day"])


def open_day(client, tutor_id, target):
    """The open-slot payload for a single date."""
    body = client.get(
        f"/api/tutors/{tutor_id}/open-slots", params={"from_date": target.isoformat(), "days": 1}
    ).json()
    return body["days"][0]


def test_open_slots_exclude_booked_times(client):
    """A start time disappears from open-slots once a session is accepted there."""
    import uuid as _uuid

    suffix = _uuid.uuid4().hex[:8]
    tutor = client.post(
        "/api/auth/register",
        json={
            "full_name": f"Slot Tutor {suffix}",
            "email": f"slot.tutor.{suffix}@example.com",
            "password": "ValidPass123",
            "role": "tutor",
            "headline": f"Open-slot test tutor {suffix}",
            "bio": "Created by the automated test-suite to verify open-slot computation.",
            "years_experience": 2,
            "hourly_rate": 4500,
            "city": "Ikeja",
            "state": "Lagos State",
            "subject_ids": [1],
        },
    ).json()
    tutor_token, tutor_id = tutor["access_token"], tutor["user"]["tutor_profile_id"]

    student = client.post(
        "/api/auth/register",
        json={
            "full_name": f"Slot Student {suffix}",
            "email": f"slot.student.{suffix}@example.com",
            "password": "ValidPass123",
            "role": "student",
        },
    ).json()
    student_token = student["access_token"]

    slot = client.post(
        "/api/availability",
        headers=auth(tutor_token),
        json={"day_of_week": "Wednesday", "start_time": "17:00", "end_time": "20:00", "mode": "online"},
    ).json()["data"]
    target = bookable_date(2, "17:00")

    def times_on(date_iso: str) -> list[str]:
        body = client.get(
            f"/api/tutors/{tutor_id}/open-slots", params={"from_date": date_iso, "days": 1}
        ).json()
        # normalise "HH:MM:SS" -> "HH:MM" for readable assertions
        return [s["start_time"][:5] for s in body["days"][0]["slots"]]

    assert "17:00" in times_on(target.isoformat()), "slot should be bookable before accepting"
    assert all(s["held"] is False for s in open_day(client, tutor_id, target)["slots"])

    created = client.post(
        "/api/requests",
        headers=auth(student_token),
        json={
            "tutor_id": tutor_id,
            "subject_id": 1,
            "preferred_date": target.isoformat(),
            "preferred_time": "17:00",
            "duration_minutes": 60,
            "mode": "online",
            "budget": 4500,
            "message": "Open-slot availability test.",
        },
    )
    assert created.status_code == 201, created.text
    request_id = created.json()["data"]["id"]

    # a *pending* request keeps the slot bookable but flags it as already asked for
    held = [s for s in open_day(client, tutor_id, target)["slots"] if s["start_time"][:5] == "17:00"]
    assert held, "a pending request must not remove the slot from the picker"
    assert held[0]["held"] is True, "pending requests should mark the slot as held"

    accepted = client.put(
        f"/api/requests/{request_id}/status",
        headers=auth(tutor_token),
        json={"status": "accepted"},
    )
    assert accepted.status_code == 200, accepted.text

    assert "17:00" not in times_on(target.isoformat()), "accepted booking must block the start time"
    assert "18:00" in times_on(target.isoformat()), "other times stay open"

    # cancelling restores the slot
    client.post(f"/api/requests/{request_id}/cancel", headers=auth(tutor_token), json={"reason": "cleanup"})
    assert "17:00" in times_on(target.isoformat()), "cancelling frees the slot again"


def test_blocked_date_removes_all_slots(client):
    tutor = make_tutor(client)
    client.post(
        "/api/availability",
        headers=auth(tutor["token"]),
        json={"day_of_week": "Monday", "start_time": "16:00", "end_time": "19:00"},
    )
    target = bookable_date(0, "16:00")

    blocked = client.post(
        "/api/availability/exceptions",
        headers=auth(tutor["token"]),
        json={"date": target.isoformat(), "is_blocked": True, "reason": "Public holiday"},
    )
    assert blocked.status_code == 201, blocked.text

    slots = client.get(
        f"/api/tutors/{tutor['profile_id']}/open-slots",
        params={"from_date": target.isoformat(), "days": 1},
    ).json()
    assert slots["days"][0]["slots"] == []

    duplicate = client.post(
        "/api/availability/exceptions",
        headers=auth(tutor["token"]),
        json={"date": target.isoformat(), "is_blocked": True},
    )
    assert duplicate.status_code == 409

    past = client.post(
        "/api/availability/exceptions",
        headers=auth(tutor["token"]),
        json={"date": "2020-01-01", "is_blocked": True},
    )
    assert past.status_code == 400

    removed = client.delete(
        f"/api/availability/exceptions/{blocked.json()['data']['id']}", headers=auth(tutor["token"])
    )
    assert removed.status_code == 200

    restored = client.get(
        f"/api/tutors/{tutor['profile_id']}/open-slots",
        params={"from_date": target.isoformat(), "days": 1},
    ).json()
    assert len(restored["days"][0]["slots"]) > 0


def test_open_slots_respects_session_duration(client):
    tutor = make_tutor(client)
    # 90-minute sessions inside a 3-hour window -> only 2 non-overlapping starts at 30-min steps
    client.put("/api/tutors/me", headers=auth(tutor["token"]), json={"session_duration_minutes": 90})
    client.post(
        "/api/availability",
        headers=auth(tutor["token"]),
        json={"day_of_week": "Tuesday", "start_time": "10:00", "end_time": "13:00"},
    )
    target = bookable_date(1, "10:00")
    slots = client.get(
        f"/api/tutors/{tutor['profile_id']}/open-slots",
        params={"from_date": target.isoformat(), "days": 1},
    ).json()["days"][0]["slots"]
    assert slots, "expected at least one 90-minute slot"
    for slot in slots:
        assert slot["duration_minutes"] == 90
        start = int(slot["start_time"][:2]) * 60 + int(slot["start_time"][3:])
        end = int(slot["end_time"][:2]) * 60 + int(slot["end_time"][3:])
        assert end - start == 90
        assert start >= 600 and end <= 780


def test_students_cannot_create_availability(client, student_token):
    response = client.post(
        "/api/availability",
        headers=auth(student_token),
        json={"day_of_week": "Monday", "start_time": "16:00", "end_time": "18:00"},
    )
    assert response.status_code == 403


def test_admin_can_manage_any_tutors_availability(client, admin_token):
    tutor = make_tutor(client)
    created = client.post(
        "/api/availability",
        headers=auth(admin_token),
        params={"tutor_id": tutor["profile_id"]},
        json={"day_of_week": "Thursday", "start_time": "18:00", "end_time": "20:00"},
    )
    assert created.status_code == 201, created.text
    slot_id = created.json()["data"]["id"]

    updated = client.put(
        f"/api/availability/{slot_id}", headers=auth(admin_token), json={"start_time": "17:00"}
    )
    assert updated.status_code == 200

    assert client.delete(f"/api/availability/{slot_id}", headers=auth(admin_token)).status_code == 200
