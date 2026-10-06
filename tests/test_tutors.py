"""Tutor discovery, filtering, and profile CRUD tests."""
from __future__ import annotations

import uuid

import pytest
from conftest import auth, bookable_date


def make_tutor(client, **overrides) -> dict:
    """Register a tutor and return {token, profile_id, email}."""
    suffix = uuid.uuid4().hex[:8]
    payload = {
        "full_name": f"Tutor {suffix}",
        "email": f"tutor.{suffix}@example.com",
        "password": "ValidPass123",
        "role": "tutor",
        "headline": f"E2E tutor profile {suffix}",
        "bio": "An experienced educator who has helped hundreds of students improve their grades.",
        "years_experience": 5,
        "hourly_rate": 5000,
        "city": "Yaba",
        "state": "Lagos State",
        "teaching_mode": "hybrid",
        "subject_ids": [1],
    }
    payload.update(overrides)
    response = client.post("/api/auth/register", json=payload)
    assert response.status_code == 201, response.text
    body = response.json()
    return {
        "token": body["access_token"],
        "profile_id": body["user"]["tutor_profile_id"],
        "email": payload["email"],
        "name": payload["full_name"],
    }


# --------------------------------------------------------------------------- #
# Search & filtering — all against real rows
# --------------------------------------------------------------------------- #
def test_search_returns_seeded_tutors(client):
    response = client.get("/api/tutors")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] >= 10
    assert len(body["items"]) >= 10
    first = body["items"][0]
    for key in ("id", "full_name", "headline", "hourly_rate", "city", "state",
                "subjects", "availability", "rating", "review_count", "years_experience"):
        assert key in first, f"missing {key} in tutor payload"


def test_search_by_name(client):
    response = client.get("/api/tutors", params={"q": "Chinedu"})
    assert response.status_code == 200
    names = [t["full_name"] for t in response.json()["items"]]
    assert any("Chinedu" in n for n in names)


def test_search_by_subject_text_and_id(client):
    by_text = client.get("/api/tutors", params={"q": "Mathematics"}).json()
    assert by_text["total"] > 0

    by_id = client.get("/api/tutors", params={"subject_id": 1}).json()
    assert by_id["total"] > 0
    for tutor in by_id["items"]:
        assert any(s["id"] == 1 for s in tutor["subjects"])


def test_search_by_location(client):
    lagos = client.get("/api/tutors", params={"location": "Lagos"}).json()
    assert lagos["total"] > 0
    for tutor in lagos["items"]:
        assert "lagos" in (tutor["city"] + tutor["state"]).lower()

    nowhere = client.get("/api/tutors", params={"location": "Atlantis"}).json()
    assert nowhere["total"] == 0


def test_filter_by_budget(client):
    cheap = client.get("/api/tutors", params={"max_price": 4000}).json()
    assert cheap["total"] > 0
    for tutor in cheap["items"]:
        assert tutor["hourly_rate"] <= 4000

    expensive = client.get("/api/tutors", params={"min_price": 8000}).json()
    for tutor in expensive["items"]:
        assert tutor["hourly_rate"] >= 8000

    impossible = client.get("/api/tutors", params={"min_price": 100000}).json()
    assert impossible["total"] == 0


def test_filter_by_experience(client):
    senior = client.get("/api/tutors", params={"min_experience": 8}).json()
    assert senior["total"] > 0
    for tutor in senior["items"]:
        assert tutor["years_experience"] >= 8


def test_filter_by_availability_day_and_window(client):
    saturday = client.get("/api/tutors", params={"day": "Saturday"}).json()
    assert saturday["total"] > 0
    for tutor in saturday["items"]:
        assert any(s["day_of_week"] == "Saturday" for s in tutor["availability"])

    window = client.get(
        "/api/tutors",
        params={"day": "Monday", "start_after": "16:00", "end_before": "19:00"},
    ).json()
    assert window["total"] >= 0


def test_filter_by_rating_and_verified(client):
    rated = client.get("/api/tutors", params={"min_rating": 4}).json()
    for tutor in rated["items"]:
        assert tutor["rating"] >= 4

    verified = client.get("/api/tutors", params={"verified_only": True}).json()
    assert verified["total"] > 0
    for tutor in verified["items"]:
        assert tutor["verified"] is True


def test_filter_by_teaching_mode(client):
    online = client.get("/api/tutors", params={"mode": "online"}).json()
    for tutor in online["items"]:
        assert tutor["accepts_online"] is True

    in_person = client.get("/api/tutors", params={"mode": "in_person"}).json()
    for tutor in in_person["items"]:
        assert tutor["accepts_in_person"] is True


def test_combined_filters_narrow_results(client):
    broad = client.get("/api/tutors").json()["total"]
    narrow = client.get(
        "/api/tutors",
        params={
            "location": "Lagos",
            "max_price": 7000,
            "min_experience": 5,
            "subject_id": 1,
        },
    ).json()
    assert narrow["total"] <= broad
    for tutor in narrow["items"]:
        assert tutor["hourly_rate"] <= 7000
        assert tutor["years_experience"] >= 5
        assert any(s["id"] == 1 for s in tutor["subjects"])


def test_invalid_filter_ranges_rejected(client):
    assert client.get("/api/tutors", params={"min_price": 9000, "max_price": 1000}).status_code == 400
    assert client.get("/api/tutors", params={"min_experience": 10, "max_experience": 2}).status_code == 400


def test_sorting(client):
    by_price = client.get("/api/tutors", params={"sort": "price_asc"}).json()["items"]
    prices = [t["hourly_rate"] for t in by_price]
    assert prices == sorted(prices)

    by_experience = client.get("/api/tutors", params={"sort": "experience"}).json()["items"]
    years = [t["years_experience"] for t in by_experience]
    assert years == sorted(years, reverse=True)


def test_pagination(client):
    page1 = client.get("/api/tutors", params={"page": 1, "page_size": 3}).json()
    page2 = client.get("/api/tutors", params={"page": 2, "page_size": 3}).json()
    assert len(page1["items"]) == 3
    assert page1["total"] == page2["total"]
    assert {t["id"] for t in page1["items"]}.isdisjoint({t["id"] for t in page2["items"]})
    assert page1["pages"] >= 2


def test_facets_reflect_database(client):
    facets = client.get("/api/tutors/facets").json()
    assert facets["total_tutors"] > 0
    assert "Lagos State" in facets["states"] or any("Lagos" in s for s in facets["states"])
    assert facets["price"]["min"] > 0
    assert facets["price"]["max"] >= facets["price"]["min"]
    assert len(facets["subjects"]) > 5
    assert facets["days"][0] == "Monday"


def test_new_tutor_appears_in_search_immediately(client):
    tutor = make_tutor(client, hourly_rate=4321, city="Testville", state="Test State")
    found = client.get("/api/tutors", params={"q": "Testville"})
    assert found.status_code == 200
    ids = [t["id"] for t in found.json()["items"]]
    assert tutor["profile_id"] in ids

    listed = [t for t in found.json()["items"] if t["id"] == tutor["profile_id"]][0]
    assert listed["hourly_rate"] == 4321


def test_price_update_is_visible_everywhere(client):
    tutor = make_tutor(client, hourly_rate=3000)
    assert client.get(f"/api/tutors/{tutor['profile_id']}").json()["hourly_rate"] == 3000

    updated = client.put(
        "/api/tutors/me", headers=auth(tutor["token"]), json={"hourly_rate": 7777}
    )
    assert updated.status_code == 200

    assert client.get(f"/api/tutors/{tutor['profile_id']}").json()["hourly_rate"] == 7777
    search = client.get("/api/tutors", params={"q": tutor["name"].split()[1]}).json()
    match = [t for t in search["items"] if t["id"] == tutor["profile_id"]]
    assert match and match[0]["hourly_rate"] == 7777


def test_get_single_tutor_profile(client):
    profile = client.get("/api/tutors/1").json()
    assert profile["full_name"]
    assert profile["headline"]
    assert isinstance(profile["subjects"], list)
    assert isinstance(profile["availability"], list)
    assert "rating_breakdown" in profile
    assert "profile_completion" in profile
    # contact details are hidden from anonymous visitors
    assert profile["email"] is None
    assert profile["phone"] is None


def test_tutor_email_visible_to_signed_in_student(client, student_token):
    profile = client.get("/api/tutors/1", headers=auth(student_token)).json()
    assert profile["email"]


def test_unknown_tutor_404(client):
    response = client.get("/api/tutors/999999")
    assert response.status_code == 404
    assert "does not exist" in response.json()["detail"]


# --------------------------------------------------------------------------- #
# Profile CRUD
# --------------------------------------------------------------------------- #
def test_create_profile_conflict_when_one_exists(client, tutor_token):
    response = client.post(
        "/api/tutors",
        headers=auth(tutor_token),
        json={
            "headline": "Second profile",
            "bio": "A second profile biography that is definitely longer than forty characters.",
            "years_experience": 1,
            "hourly_rate": 1000,
            "city": "Yaba",
            "state": "Lagos State",
            "subject_ids": [1],
        },
    )
    assert response.status_code == 409


def test_update_profile_validation(client):
    tutor = make_tutor(client)
    short_bio = client.put("/api/tutors/me", headers=auth(tutor["token"]), json={"bio": "too short"})
    assert short_bio.status_code == 422

    negative_rate = client.put(
        "/api/tutors/me", headers=auth(tutor["token"]), json={"hourly_rate": -5}
    )
    assert negative_rate.status_code == 422

    no_modes = client.put(
        "/api/tutors/me",
        headers=auth(tutor["token"]),
        json={"accepts_online": False, "accepts_in_person": False},
    )
    assert no_modes.status_code in (400, 422)


def test_update_profile_subjects_replace_links(client):
    tutor = make_tutor(client, subject_ids=[1])
    response = client.put(
        "/api/tutors/me", headers=auth(tutor["token"]), json={"subject_ids": [2, 3]}
    )
    assert response.status_code == 200
    ids = {s["id"] for s in response.json()["subjects"]}
    assert ids == {2, 3}

    bad = client.put(
        "/api/tutors/me", headers=auth(tutor["token"]), json={"subject_ids": [99999]}
    )
    assert bad.status_code == 400


def test_add_and_remove_single_subject(client):
    tutor = make_tutor(client, subject_ids=[1])
    added = client.post(
        "/api/tutors/me/subjects",
        headers=auth(tutor["token"]),
        params={"subject_id": 4, "proficiency": "Intermediate"},
    )
    assert added.status_code == 201, added.text

    duplicate = client.post(
        "/api/tutors/me/subjects", headers=auth(tutor["token"]), params={"subject_id": 4}
    )
    assert duplicate.status_code == 409

    removed = client.delete("/api/tutors/me/subjects/4", headers=auth(tutor["token"]))
    assert removed.status_code == 200

    missing = client.delete("/api/tutors/me/subjects/4", headers=auth(tutor["token"]))
    assert missing.status_code == 404


def test_profile_visibility_toggle_hides_from_search(client):
    tutor = make_tutor(client, city="Hideville")
    assert client.get("/api/tutors", params={"q": "Hideville"}).json()["total"] == 1

    client.put("/api/tutors/me", headers=auth(tutor["token"]), json={"is_visible": False})
    assert client.get("/api/tutors", params={"q": "Hideville"}).json()["total"] == 0

    # owner can still see their own profile
    assert client.get(f"/api/tutors/{tutor['profile_id']}", headers=auth(tutor["token"])).status_code == 200
    # anonymous cannot
    assert client.get(f"/api/tutors/{tutor['profile_id']}").status_code == 404


def test_delete_profile_blocked_by_active_requests(client, tutor_token, student_token):
    profile = client.get("/api/tutors/me", headers=auth(tutor_token)).json()
    slot = [s for s in profile["availability"] if s["is_active"]][0]
    target = bookable_date(slot["day_index"], slot["start_time"])

    created = client.post(
        "/api/requests",
        headers=auth(student_token),
        json={
            "tutor_id": profile["id"],
            "subject_id": profile["subjects"][0]["id"],
            "preferred_date": target.isoformat(),
            "preferred_time": slot["start_time"],
            "duration_minutes": 60,
            "mode": "hybrid",
            "budget": float(profile["hourly_rate"]),
        },
    )
    assert created.status_code == 201, created.text

    blocked = client.delete("/api/tutors/me", headers=auth(tutor_token))
    assert blocked.status_code == 409
    assert "active request" in blocked.json()["detail"].lower()

    # clean up so later tests are unaffected
    client.post(
        f"/api/requests/{created.json()['data']['id']}/cancel",
        headers=auth(student_token),
        json={"reason": "test cleanup"},
    )


def test_delete_own_profile(client):
    tutor = make_tutor(client)
    response = client.delete("/api/tutors/me", headers=auth(tutor["token"]))
    assert response.status_code == 200

    assert client.get(f"/api/tutors/{tutor['profile_id']}").status_code == 404
    assert client.get("/api/tutors/me", headers=auth(tutor["token"])).status_code == 404


def test_tutor_dashboard_stats(client, tutor_token):
    response = client.get("/api/tutors/me/stats", headers=auth(tutor_token))
    assert response.status_code == 200
    stats = response.json()
    for key in (
        "profile_completion", "total_requests", "pending_requests", "accepted_requests",
        "completed_sessions", "upcoming_sessions", "rating", "review_count",
        "weekly_slots", "total_earnings",
    ):
        assert key in stats
    assert 0 <= stats["profile_completion"] <= 100
    assert stats["weekly_slots"] >= 1


def test_tutor_reviews_endpoint(client):
    response = client.get("/api/tutors/2/reviews")
    assert response.status_code == 200
    body = response.json()
    assert body["tutor_id"] == 2
    assert len(body["breakdown"]) == 5
    assert body["review_count"] == sum(row["count"] for row in body["breakdown"])


def test_demo_reviews_are_spread_across_tutors(client):
    """Seeded reviews must not all land on one tutor, or rating sorting looks broken."""
    items = client.get("/api/tutors", params={"page_size": 100}).json()["items"]
    # other test modules register their own tutors during the session, so look at
    # the seeded marketplace only (every demo bio mentions the dataset)
    seeded = [t for t in items if "automated test-suite" not in (t["bio"] or "")]
    assert len(seeded) >= 11

    reviewed = [t for t in seeded if t["review_count"] > 0]
    assert len(reviewed) >= 4, f"only {len(reviewed)} seeded tutors have reviews"
    assert len({t["rating"] for t in reviewed}) >= 2, "expected a spread of averages"
    assert max(t["review_count"] for t in reviewed) <= 2, "reviews are clustered on one tutor"
    assert sum(t["review_count"] for t in reviewed) >= 6

    # sort=rating puts the best-reviewed tutors first, unrated ones last
    ordered = client.get("/api/tutors", params={"sort": "rating", "page_size": 100}).json()["items"]
    ratings = [t["rating"] for t in ordered]
    assert ratings == sorted(ratings, reverse=True)
    assert ordered[0]["review_count"] > 0, "the top result should be a rated tutor"
