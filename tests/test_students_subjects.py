"""Student profile, subjects and saved tutors (favourites)."""
from __future__ import annotations

import uuid

from conftest import auth


def new_student(client, **extra) -> dict:
    suffix = uuid.uuid4().hex[:8]
    payload = {
        "full_name": f"Profile Student {suffix}",
        "email": f"profile.{suffix}@example.com",
        "password": "ValidPass123",
        "role": "student",
    }
    payload.update(extra)
    response = client.post("/api/auth/register", json=payload)
    assert response.status_code == 201, response.text
    body = response.json()
    return {"token": body["access_token"], "id": body["user"]["id"], "email": payload["email"]}


# --------------------------------------------------------------------------- #
# /api/students/me
# --------------------------------------------------------------------------- #
def test_student_profile_is_auto_created_on_register(client):
    student = new_student(client)
    response = client.get("/api/students/me", headers=auth(student["token"]))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["user_id"] == student["id"]
    assert body["counts"]["pending"] == 0
    assert body["counts"]["completed"] == 0
    assert body["reviews_written"] == 0
    assert body["favorites"] == 0


def test_update_student_profile(client):
    student = new_student(client)

    updated = client.put(
        "/api/students/me",
        headers=auth(student["token"]),
        json={
            "education_level": "Senior Secondary",
            "guardian_name": "Mrs. Ada Nwankwo",
            "city": "Enugu",
            "state": "Enugu State",
            "learning_goals": "Score A1 in Mathematics and Further Mathematics before WAEC.",
            "preferred_mode": "in_person",
            "max_budget": 8000,
            "avatar_url": "https://images.unsplash.com/photo-1544005313-94ddf0286df2?w=200&q=80",
        },
    )
    assert updated.status_code == 200, updated.text
    assert "updated" in updated.json()["detail"].lower()
    body = updated.json()["data"]
    assert body["education_level"] == "Senior Secondary"
    assert body["guardian_name"] == "Mrs. Ada Nwankwo"
    assert body["city"] == "Enugu"
    assert body["state"] == "Enugu State"
    assert body["preferred_mode"] == "in_person"
    assert body["max_budget"] == 8000

    # the change persists on a fresh read
    again = client.get("/api/students/me", headers=auth(student["token"])).json()
    assert again["city"] == "Enugu"

    # avatar lives on the user record
    me = client.get("/api/auth/me", headers=auth(student["token"])).json()
    assert me["avatar_url"].startswith("https://images.unsplash.com/")


def test_update_student_profile_validation(client):
    student = new_student(client)

    bad_mode = client.put(
        "/api/students/me", headers=auth(student["token"]), json={"preferred_mode": "telepathy"}
    )
    assert bad_mode.status_code == 422

    negative_budget = client.put(
        "/api/students/me", headers=auth(student["token"]), json={"max_budget": -5}
    )
    assert negative_budget.status_code == 422


def test_partial_update_keeps_other_fields(client):
    student = new_student(client)
    client.put(
        "/api/students/me",
        headers=auth(student["token"]),
        json={"city": "Ibadan", "state": "Oyo State", "education_level": "Junior Secondary"},
    )
    partial = client.put(
        "/api/students/me", headers=auth(student["token"]), json={"guardian_name": "Mr. Tunde"}
    )
    assert partial.status_code == 200
    body = partial.json()["data"]
    assert body["city"] == "Ibadan", "untouched fields must be preserved"
    assert body["guardian_name"] == "Mr. Tunde"


def test_student_profile_counts_track_requests(client):
    student = new_student(client)
    assert client.get("/api/students/me", headers=auth(student["token"])).json()["counts"]["pending"] == 0

    created = client.post(
        "/api/requests",
        headers=auth(student["token"]),
        json={
            "tutor_id": 1,
            "subject_id": 1,
            "preferred_date": "2030-05-06",
            "preferred_time": "16:00",
            "budget": 6000,
            "message": "Profile count test.",
            "ignore_availability": True,
        },
    )
    assert created.status_code == 201, created.text

    body = client.get("/api/students/me", headers=auth(student["token"])).json()
    assert body["counts"]["pending"] == 1

    # cancelling moves the count
    client.post(
        f"/api/requests/{created.json()['data']['id']}/cancel",
        headers=auth(student["token"]),
        json={"reason": "test cleanup"},
    )
    body = client.get("/api/students/me", headers=auth(student["token"])).json()
    assert body["counts"]["pending"] == 0
    assert body["counts"]["cancelled"] == 1


def test_tutors_cannot_use_the_student_profile_endpoint(client, tutor_token):
    assert client.get("/api/students/me", headers=auth(tutor_token)).status_code == 403
    assert client.put(
        "/api/students/me", headers=auth(tutor_token), json={"city": "Lagos"}
    ).status_code == 403


def test_student_profile_requires_auth(client):
    assert client.get("/api/students/me").status_code in (401, 403)


# --------------------------------------------------------------------------- #
# /api/subjects
# --------------------------------------------------------------------------- #
def test_subject_listing(client):
    response = client.get("/api/subjects")
    assert response.status_code == 200
    body = response.json()
    items = body["items"]
    assert len(items) >= 30
    first = items[0]
    assert {"id", "name", "category"} <= set(first)
    assert "tutor_count" in first  # live count, not hard-coded

    names = [s["name"] for s in items]
    assert "Mathematics" in names
    assert body["total"] == len(items)
    # sorted alphabetically for a stable UI
    assert names == sorted(names)


def test_subject_categories(client):
    response = client.get("/api/subjects/categories")
    assert response.status_code == 200
    categories = response.json()
    categories = categories["items"] if isinstance(categories, dict) else categories
    assert len(categories) >= 3


def test_the_seeded_marker_subject_is_not_exposed(client):
    items = client.get("/api/subjects").json()["items"]
    assert all(not s["name"].startswith("__") for s in items)


def test_subject_search_and_category_filters(client):
    searched = client.get("/api/subjects", params={"q": "math"}).json()
    assert searched["total"] >= 1
    assert all("math" in s["name"].lower() for s in searched["items"])

    by_category = client.get("/api/subjects", params={"category": searched["items"][0]["category"]}).json()
    assert by_category["total"] >= 1

    with_tutors = client.get("/api/subjects", params={"only_with_tutors": "true"}).json()
    assert with_tutors["total"] >= 1
    assert all(s["tutor_count"] > 0 for s in with_tutors["items"])


# --------------------------------------------------------------------------- #
# /api/favorites
# --------------------------------------------------------------------------- #
def test_favorite_add_list_remove(client):
    student = new_student(client)
    token = student["token"]

    assert client.get("/api/favorites", headers=auth(token)).json() == []

    added = client.post("/api/favorites/2", headers=auth(token))
    assert added.status_code == 201, added.text
    assert added.json()["data"]["tutor_id"] == 2
    assert added.json()["data"]["is_favorite"] is True

    duplicate = client.post("/api/favorites/2", headers=auth(token))
    assert duplicate.status_code == 409

    listing = client.get("/api/favorites", headers=auth(token)).json()
    assert len(listing) == 1
    assert listing[0]["id"] == 2
    assert listing[0]["is_favorite"] is True
    assert listing[0]["full_name"]

    # profile counter reflects it
    assert client.get("/api/students/me", headers=auth(token)).json()["favorites"] == 1

    # the tutor card in search now reports is_favorite for this student
    search = client.get("/api/tutors", headers=auth(token)).json()
    saved = [t for t in search["items"] if t["id"] == 2]
    if saved:
        assert saved[0]["is_favorite"] is True

    removed = client.delete("/api/favorites/2", headers=auth(token))
    assert removed.status_code == 200
    assert client.get("/api/favorites", headers=auth(token)).json() == []

    again = client.delete("/api/favorites/2", headers=auth(token))
    assert again.status_code == 404


def test_favorite_toggle(client):
    student = new_student(client)
    token = student["token"]

    on = client.post("/api/favorites/3/toggle", headers=auth(token))
    assert on.status_code == 200
    assert on.json()["data"]["is_favorite"] is True

    off = client.post("/api/favorites/3/toggle", headers=auth(token))
    assert off.json()["data"]["is_favorite"] is False

    assert client.get("/api/favorites", headers=auth(token)).json() == []


def test_favorite_unknown_tutor(client):
    student = new_student(client)
    assert client.post("/api/favorites/999999", headers=auth(student["token"])).status_code == 404


def test_favorites_are_per_student(client):
    first = new_student(client)
    second = new_student(client)
    client.post("/api/favorites/4", headers=auth(first["token"]))

    assert len(client.get("/api/favorites", headers=auth(first["token"])).json()) == 1
    assert client.get("/api/favorites", headers=auth(second["token"])).json() == []


def test_tutors_cannot_save_favorites(client, tutor_token):
    assert client.get("/api/favorites", headers=auth(tutor_token)).status_code == 403
    assert client.post("/api/favorites/1", headers=auth(tutor_token)).status_code == 403
