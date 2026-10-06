"""Reviews, star ratings and the rating breakdown shown on tutor profiles."""
from __future__ import annotations

import uuid

import conftest
import pytest
from conftest import auth, bookable_date, past_weekday


def _make_pair(client) -> dict:
    """Create a fresh tutor + student and drive one booking through to *completed*."""
    from models import BookingRequest

    suffix = uuid.uuid4().hex[:8]
    tutor_body = client.post(
        "/api/auth/register",
        json={
            "full_name": f"Review Tutor {suffix}",
            "email": f"review.tutor.{suffix}@example.com",
            "password": "ValidPass123",
            "role": "tutor",
            "headline": f"Reviewflow {suffix} tutor",
            "bio": "Created by the automated test-suite to exercise reviews and ratings.",
            "years_experience": 6,
            "hourly_rate": 6000,
            "city": "Garki",
            "state": "Federal Capital Territory",
            "subject_ids": [1, 2],
        },
    ).json()
    tutor_token = tutor_body["access_token"]
    tutor_id = tutor_body["user"]["tutor_profile_id"]

    student_body = client.post(
        "/api/auth/register",
        json={
            "full_name": f"Review Student {suffix}",
            "email": f"review.student.{suffix}@example.com",
            "password": "ValidPass123",
            "role": "student",
        },
    ).json()
    student_token = student_body["access_token"]

    client.post(
        "/api/availability",
        headers=auth(tutor_token),
        json={"day_of_week": "Tuesday", "start_time": "16:00", "end_time": "19:00"},
    )
    created = client.post(
        "/api/requests",
        headers=auth(student_token),
        json={
            "tutor_id": tutor_id,
            "subject_id": 1,
            "preferred_date": bookable_date(1, "16:00").isoformat(),
            "preferred_time": "16:00",
            "budget": 6000,
            "mode": "hybrid",
            "message": "Review-flow booking.",
        },
    )
    assert created.status_code == 201, created.text
    request_id = created.json()["data"]["id"]

    client.put(
        f"/api/requests/{request_id}/status",
        headers=auth(tutor_token),
        json={"status": "accepted"},
    )

    # move the session into the past so it becomes completable
    with conftest.SessionLocal() as db:
        db.get(BookingRequest, request_id).preferred_date = past_weekday(1)
        db.commit()

    completed = client.put(
        f"/api/requests/{request_id}/status",
        headers=auth(tutor_token),
        json={"status": "completed"},
    )
    assert completed.status_code == 200, completed.text

    return {
        "tutor_token": tutor_token,
        "student_token": student_token,
        "tutor_id": tutor_id,
        "request_id": request_id,
        "suffix": suffix,
    }


@pytest.fixture()
def pair(client, admin_token):
    """An isolated tutor/student pair.

    The tutor profile is deleted afterwards (as admin, which bypasses the
    "resolve active requests first" guard) so aggregate assertions elsewhere are
    not polluted by reviews left behind from earlier tests in the same session.
    """
    data = _make_pair(client)
    yield data
    removed = client.delete(f"/api/tutors/{data['tutor_id']}", headers=auth(admin_token))
    assert removed.status_code == 200, removed.text


def post_review(client, token, request_id, rating, **extra):
    payload = {"booking_request_id": request_id, "rating": rating}
    payload.update(extra)
    return client.post("/api/reviews", headers=auth(token), json=payload)


def rating_of(client, tutor_id) -> dict:
    response = client.get(f"/api/tutors/{tutor_id}/rating")
    assert response.status_code == 200, response.text
    return response.json()


def counts(body: dict) -> dict:
    return {row["star"]: row["count"] for row in body["breakdown"]}


# --------------------------------------------------------------------------- #
# Baseline
# --------------------------------------------------------------------------- #
def test_new_tutor_has_no_rating(client):
    suffix = uuid.uuid4().hex[:8]
    response = client.post(
        "/api/auth/register",
        json={
            "full_name": f"Unrated Tutor {suffix}",
            "email": f"unrated.{suffix}@example.com",
            "password": "ValidPass123",
            "role": "tutor",
            "headline": f"Unrated tutor {suffix}",
            "bio": "No reviews yet for this test tutor - the automated suite created this profile.",
            "years_experience": 1,
            "hourly_rate": 2500,
            "city": "Lekki",
            "state": "Lagos State",
            "subject_ids": [1],
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    tutor_id = body["user"]["tutor_profile_id"]

    summary = rating_of(client, tutor_id)
    assert summary["review_count"] == 0
    assert summary["average_rating"] is None
    assert summary["stars"] == 0
    assert summary["has_reviews"] is False
    assert all(row["count"] == 0 and row["percentage"] == 0 for row in summary["breakdown"])
    assert [row["star"] for row in summary["breakdown"]] == [5, 4, 3, 2, 1]

    profile = client.get(f"/api/tutors/{tutor_id}").json()
    assert profile["review_count"] == 0
    assert profile["rating"] == 0.0
    assert profile["reviews"] == []


def test_seeded_reviews_drive_the_rating_breakdown(client):
    items = client.get("/api/tutors", params={"sort": "rating", "page_size": 100}).json()["items"]
    reviewed = [t for t in items if t["review_count"] > 0]
    assert reviewed, "the demo dataset should contain real reviews"

    tutor_id = reviewed[0]["id"]
    profile = client.get(f"/api/tutors/{tutor_id}").json()
    assert profile["review_count"] >= 1
    assert 1 <= profile["rating"] <= 5
    assert sum(row["count"] for row in profile["rating_breakdown"]) == profile["review_count"]
    assert profile["rating"] == round(
        sum(row["star"] * row["count"] for row in profile["rating_breakdown"])
        / profile["review_count"],
        2,
    )
    assert len(profile["reviews"]) <= profile["review_count"]  # detail view is capped

    summary = rating_of(client, tutor_id)
    assert summary["review_count"] == profile["review_count"]
    assert summary["average_rating"] == profile["rating"]
    assert summary["stars"] == round(profile["rating"])

    listing = client.get(f"/api/tutors/{tutor_id}/reviews").json()
    assert listing["review_count"] == profile["review_count"]
    assert len(listing["items"]) == profile["review_count"]

    ratings = [t["rating"] for t in reviewed]
    assert ratings == sorted(ratings, reverse=True), "sort=rating must order best first"


# --------------------------------------------------------------------------- #
# Create
# --------------------------------------------------------------------------- #
def test_create_review(client, pair):
    response = post_review(
        client,
        pair["student_token"],
        pair["request_id"],
        5,
        title="Made calculus finally click",
        comment="Patient, well prepared, and explained every step. My test score jumped from 42% to 78%.",
    )
    assert response.status_code == 201, response.text
    data = response.json()["data"]
    review = data["review"]
    assert review["rating"] == 5
    assert review["title"] == "Made calculus finally click"
    assert review["subject_name"] == "Mathematics"
    assert review["student_name"]
    assert review["booking_request_id"] == pair["request_id"]
    assert data["tutor_rating"]["review_count"] == 1
    assert data["tutor_rating"]["rating"] == 5.0

    # rating propagates to the profile and to search results
    profile = client.get(f"/api/tutors/{pair['tutor_id']}").json()
    assert profile["review_count"] == 1
    assert profile["rating"] == 5.0
    assert len(profile["reviews"]) == 1
    assert [r for r in profile["rating_breakdown"] if r["star"] == 5][0]["count"] == 1
    assert [r for r in profile["rating_breakdown"] if r["star"] == 5][0]["percentage"] == 100.0

    search = client.get("/api/tutors", params={"q": "Reviewflow"}).json()
    assert search["total"] == 1
    assert search["items"][0]["review_count"] == 1
    assert search["items"][0]["rating"] == 5.0


def test_default_title_is_used_when_omitted(client, pair):
    review = post_review(client, pair["student_token"], pair["request_id"], 4).json()["data"]["review"]
    assert review["title"] == "Great session"


def test_review_validation(client, pair):
    token = pair["student_token"]

    for bad_rating in (0, 6, -1, 3.5):
        response = post_review(client, token, pair["request_id"], bad_rating)
        assert response.status_code == 422, f"rating {bad_rating} should be rejected"

    assert client.post("/api/reviews", headers=auth(token), json={"rating": 5}).status_code == 422
    assert post_review(client, token, 999999, 5).status_code == 404
    assert client.post("/api/reviews", json={"booking_request_id": pair["request_id"], "rating": 5}).status_code in (401, 403)


def test_review_requires_completed_session(client, pair):
    other = client.post(
        "/api/requests",
        headers=auth(pair["student_token"]),
        json={
            "tutor_id": pair["tutor_id"],
            "subject_id": 2,
            "preferred_date": bookable_date(1, "17:00").isoformat(),
            "preferred_time": "17:00",
            "budget": 6000,
            "message": "Physics help.",
        },
    ).json()["data"]
    assert other["status"] == "pending"

    response = post_review(client, pair["student_token"], other["id"], 4)
    assert response.status_code == 409
    assert "completed" in response.json()["detail"].lower()


def test_only_the_owning_student_can_review(client, pair):
    stranger = client.post(
        "/api/auth/register",
        json={
            "full_name": "Unrelated Student",
            "email": f"unrelated.{uuid.uuid4().hex[:8]}@example.com",
            "password": "ValidPass123",
            "role": "student",
        },
    ).json()

    assert post_review(client, stranger["access_token"], pair["request_id"], 5).status_code == 403
    assert post_review(client, pair["tutor_token"], pair["request_id"], 5).status_code == 403


def test_one_review_per_booking(client, pair):
    assert post_review(client, pair["student_token"], pair["request_id"], 5).status_code == 201
    duplicate = post_review(client, pair["student_token"], pair["request_id"], 1)
    assert duplicate.status_code == 409
    assert rating_of(client, pair["tutor_id"])["review_count"] == 1


# --------------------------------------------------------------------------- #
# Aggregate maths
# --------------------------------------------------------------------------- #
def test_rating_is_recomputed_from_rows(client):
    from models import BookingRequest

    pair = _make_pair(client)

    assert post_review(client, pair["student_token"], pair["request_id"], 5).status_code == 201
    assert rating_of(client, pair["tutor_id"])["average_rating"] == 5.0

    # a second student completes a session and leaves a 4
    second = client.post(
        "/api/auth/register",
        json={
            "full_name": "Second Reviewer",
            "email": f"second.{uuid.uuid4().hex[:8]}@example.com",
            "password": "ValidPass123",
            "role": "student",
        },
    ).json()["access_token"]

    request = client.post(
        "/api/requests",
        headers=auth(second),
        json={
            "tutor_id": pair["tutor_id"],
            "subject_id": 1,
            "preferred_date": bookable_date(1, "18:00").isoformat(),
            "preferred_time": "18:00",
            "budget": 6000,
            "message": "Second reviewer booking.",
        },
    ).json()["data"]

    client.put(
        f"/api/requests/{request['id']}/status",
        headers=auth(pair["tutor_token"]),
        json={"status": "accepted"},
    )
    with conftest.SessionLocal() as db:
        db.get(BookingRequest, request["id"]).preferred_date = past_weekday(1)
        db.commit()
    client.put(
        f"/api/requests/{request['id']}/status",
        headers=auth(pair["tutor_token"]),
        json={"status": "completed"},
    )

    assert post_review(client, second, request["id"], 4).status_code == 201

    summary = rating_of(client, pair["tutor_id"])
    assert summary["review_count"] == 2
    assert summary["average_rating"] == 4.5  # (5 + 4) / 2
    assert counts(summary) == {5: 1, 4: 1, 3: 0, 2: 0, 1: 0}

    # min_rating filter now matches this tutor
    filtered = client.get("/api/tutors", params={"q": "Reviewflow", "min_rating": 4}).json()
    assert filtered["total"] == 1, [(i["full_name"], i["headline"]) for i in filtered["items"]]
    assert filtered["items"][0]["id"] == pair["tutor_id"]

    too_high = client.get("/api/tutors", params={"q": "Reviewflow", "min_rating": 5}).json()
    assert too_high["total"] == 0

    needs_reviews = client.get("/api/tutors", params={"q": "Reviewflow", "min_reviews": 2}).json()
    assert needs_reviews["total"] == 1


# --------------------------------------------------------------------------- #
# Edit / delete / moderation
# --------------------------------------------------------------------------- #
def test_edit_and_delete_review(client, pair):
    review = post_review(
        client, pair["student_token"], pair["request_id"], 3, comment="Average so far"
    ).json()["data"]["review"]
    review_id = review["id"]
    assert rating_of(client, pair["tutor_id"])["average_rating"] == 3.0

    edited = client.put(
        f"/api/reviews/{review_id}",
        headers=auth(pair["student_token"]),
        json={"rating": 5, "title": "Changed my mind", "comment": "The follow-up session was excellent."},
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["data"]["review"]["rating"] == 5
    assert rating_of(client, pair["tutor_id"])["average_rating"] == 5.0

    mine = client.get("/api/reviews/mine", headers=auth(pair["student_token"])).json()
    assert mine["total"] == 1
    assert mine["items"][0]["id"] == review_id

    single = client.get(f"/api/reviews/{review_id}")
    assert single.status_code == 200
    assert single.json()["rating"] == 5
    assert single.json()["tutor"]["id"] == pair["tutor_id"]

    assert client.delete(f"/api/reviews/{review_id}", headers=auth(pair["student_token"])).status_code == 200
    assert rating_of(client, pair["tutor_id"])["review_count"] == 0
    assert client.get("/api/reviews/mine", headers=auth(pair["student_token"])).json()["total"] == 0


def test_tutor_cannot_edit_or_delete_reviews(client, pair):
    review = post_review(
        client, pair["student_token"], pair["request_id"], 2, comment="Needs improvement"
    ).json()["data"]["review"]

    assert client.put(
        f"/api/reviews/{review['id']}", headers=auth(pair["tutor_token"]), json={"rating": 5}
    ).status_code == 403
    assert client.delete(
        f"/api/reviews/{review['id']}", headers=auth(pair["tutor_token"])
    ).status_code == 403

    # but tutors can read the reviews written about them
    tutor_view = client.get("/api/reviews/mine", headers=auth(pair["tutor_token"]))
    assert tutor_view.status_code == 200
    assert tutor_view.json()["total"] == 1
    assert tutor_view.json()["average_rating"] == 2.0
    assert rating_of(client, pair["tutor_id"])["average_rating"] == 2.0


def test_another_student_cannot_edit(client, pair):
    review = post_review(client, pair["student_token"], pair["request_id"], 5).json()["data"]["review"]
    other = client.post(
        "/api/auth/register",
        json={
            "full_name": "Another Student",
            "email": f"another.{uuid.uuid4().hex[:8]}@example.com",
            "password": "ValidPass123",
            "role": "student",
        },
    ).json()["access_token"]

    assert client.put(f"/api/reviews/{review['id']}", headers=auth(other), json={"rating": 1}).status_code == 403
    assert client.delete(f"/api/reviews/{review['id']}", headers=auth(other)).status_code == 403


def test_review_listing_limit(client, pair):
    post_review(client, pair["student_token"], pair["request_id"], 5, comment="Top tutor")
    listing = client.get(f"/api/tutors/{pair['tutor_id']}/reviews").json()
    assert listing["review_count"] == 1
    assert listing["rating"] == 5.0
    assert listing["items"][0]["student_name"]
    assert len(listing["breakdown"]) == 5

    limited = client.get(f"/api/tutors/{pair['tutor_id']}/reviews", params={"limit": 1})
    assert limited.status_code == 200
    assert len(limited.json()["items"]) == 1

    assert client.get("/api/tutors/999999/reviews").status_code == 404


def test_review_notification_reaches_tutor(client, pair):
    post_review(client, pair["student_token"], pair["request_id"], 5, comment="Wonderful")
    notes = client.get("/api/notifications", headers=auth(pair["tutor_token"])).json()
    matching = [n for n in notes["items"] if n["type"] == "review_new"]
    assert matching
    assert "5-star" in matching[0]["title"]


def test_admin_can_hide_and_restore_a_review(client, pair, admin_token):
    review = post_review(
        client, pair["student_token"], pair["request_id"], 1, comment="Rude and unprepared"
    ).json()["data"]["review"]
    assert rating_of(client, pair["tutor_id"])["review_count"] == 1

    hidden = client.post(f"/api/admin/reviews/{review['id']}/hide", headers=auth(admin_token))
    assert hidden.status_code == 200, hidden.text

    assert rating_of(client, pair["tutor_id"])["review_count"] == 0
    assert client.get(f"/api/tutors/{pair['tutor_id']}/reviews").json()["review_count"] == 0
    assert client.get(f"/api/tutors/{pair['tutor_id']}").json()["review_count"] == 0

    restored = client.post(f"/api/admin/reviews/{review['id']}/restore", headers=auth(admin_token))
    assert restored.status_code == 200
    assert rating_of(client, pair["tutor_id"])["review_count"] == 1


def test_non_admins_cannot_moderate(client, pair, tutor_token, student_token):
    review = post_review(client, pair["student_token"], pair["request_id"], 5).json()["data"]["review"]
    for token in (tutor_token, student_token):
        assert client.post(f"/api/admin/reviews/{review['id']}/hide", headers=auth(token)).status_code == 403


def test_admin_review_listing(client, pair, admin_token):
    post_review(client, pair["student_token"], pair["request_id"], 5, comment="Great")
    listing = client.get("/api/admin/reviews", headers=auth(admin_token))
    assert listing.status_code == 200
    assert listing.json()["total"] >= 1
    assert listing.json()["items"][0]["rating"] >= 1
