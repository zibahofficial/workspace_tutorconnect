"""Router package — exposes a single `api_router` mounted at /api."""
from fastapi import APIRouter

from routers import admin, auth, availability, notifications, requests, reviews, students, subjects, tutors

api_router = APIRouter(prefix="/api")
api_router.include_router(auth.router)
api_router.include_router(tutors.router)
api_router.include_router(availability.router)
api_router.include_router(requests.router)
api_router.include_router(reviews.router)
api_router.include_router(subjects.router)
api_router.include_router(notifications.router)
api_router.include_router(students.router)
api_router.include_router(admin.router)

__all__ = ["api_router", "admin", "auth", "availability", "notifications", "requests", "reviews", "students", "subjects", "tutors"]
