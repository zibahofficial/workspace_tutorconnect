# TutorConnect — Tutor & Student Matching Platform

**Find the Right Tutor. Learn With Confidence.**

A complete, runnable full-stack MVP for discovering, vetting and booking private
tutors. Tutors publish real profiles and weekly availability, students search and
filter against live database records, book sessions that tutors accept or reject,
and leave star reviews once a session is completed. Administrators moderate the
whole marketplace from a dedicated dashboard.

Nothing on the frontend is mocked: every card, counter, rating and status you see
is read from — and written back to — a relational database through a REST API.

---

## Table of contents

1. [Features](#features)
2. [Tech stack](#tech-stack)
3. [Project structure](#project-structure)
4. [Quick start](#quick-start)
5. [Configuration (`.env`)](#configuration-env)
6. [Database](#database)
7. [Creating the administrator account](#creating-the-administrator-account)
8. [Demo accounts](#demo-accounts)
9. [Running the app](#running-the-app)
10. [The API](#the-api)
11. [Data model](#data-model)
12. [Testing](#testing)
13. [Security notes](#security-notes)
14. [Deployment](#deployment)
15. [Troubleshooting](#troubleshooting)

---

## Features

### Authentication & authorisation
- Registration and login for **Tutor**, **Student/Parent** and **Admin** roles.
- Passwords hashed with `pbkdf2_sha256` (via passlib) — never stored or returned in plain text.
- Session tokens are **JWTs** (HS256) sent as `Authorization: Bearer <token>`.
- Role-based route guards on the API (`require_roles(...)`) *and* in the browser
  (`App.boot({ requireAuth: true, roles: [...] })` redirects to `/login.html?next=…`).
- Password strength rules, confirmation matching, duplicate-email detection and
  friendly per-field error messages.
- Change password, update profile, deactivate/delete account.

### Tutor discovery (all against real rows)
- Free-text search across name, headline, bio, city, state, qualifications,
  languages and subjects.
- Filters: **subject**, **location** (city/state), **teaching mode**
  (in person / online / hybrid), **experience** (years), **budget** (max hourly
  rate with a slider), **availability** (weekday + time window + "available today"),
  **minimum rating**, **minimum reviews**, **verified only**.
- Sorting by relevance, rating, price (asc/desc), experience, newest, popularity.
- Pagination, live facet counts (`/api/tutors/facets`) and a match score.
- Unapproved or suspended tutors never appear in public results.

### Tutor profiles
- Headline, long bio, qualifications, languages, hourly rate, session length,
  city/state, teaching mode, cover photo, avatar, verification badge.
- Subjects taught (many-to-many with live per-subject tutor counts).
- Profile-completion meter, total students taught, completed-session count.
- Rating summary with the 5→1 star breakdown, and the real reviews behind it.
- "Similar tutors" suggestions and a map link for in-person tutors.

### Weekly availability (tutor-defined, never hard-coded)
- Tutors create/edit/pause/delete recurring weekly slots (day, start, end, mode,
  optional location).
- Overlapping slots on the same weekday are rejected with a clear 409.
- Date exceptions let a tutor block a single day (holiday, travel) without
  touching the recurring schedule.
- Students see a 7-day grid of **open** slots — already-booked times, paused
  slots and blocked dates are removed server-side.

### Booking requests
- Statuses: `pending → accepted | rejected | cancelled | completed`.
- Students pick a real open slot (or request an off-schedule time with an
  explicit `ignore_availability` consent flag).
- Validation: no past dates, minimum lead time (`MIN_BOOKING_LEAD_HOURS`),
  15-minute time increments, subject must actually be taught by that tutor,
  no double-booking of the same slot.
- Tutors accept/reject with an optional note; accepting checks for clashes with
  already-accepted sessions.
- Sessions can only be marked **completed** once they are accepted and in the past.
- Both sides see live status updates, and every transition writes a notification.
- Cancel (student or tutor) and delete guards so history is never lost silently.

### Reviews & ratings
- 1–5 stars plus an optional title, comment — only after a **completed** session,
  only by the student who attended, exactly one review per booking.
- Average rating, review count and the star breakdown are **always recomputed
  from `Review` rows** — nothing is denormalised, so editing, deleting or
  moderating a review immediately changes every number in the UI.
- Students can edit or delete their own review (60-day window); tutors can read
  but never modify them; admins can hide and restore.

### Saved tutors, notifications, dashboards
- Favourites (save/unsave/toggle), per-student and visible on tutor cards.
- Notification centre with unread count, mark-one-read, mark-all-read, delete,
  and a 45-second polling refresh in the navbar bell.
- Three role-specific dashboards with stats, charts, tables, tabs, modals,
  loading skeletons, empty states and error states:
  - **Tutor** — overview, incoming requests, availability manager, public profile
    editor, reviews, account.
  - **Student** — overview, my requests, saved tutors, browse, my profile, my
    reviews, account.
  - **Admin** — platform stats, users, tutor approvals, all requests, review
    moderation, subject CRUD, activity log, account.

### UI
- Hand-written HTML5 + CSS3 + vanilla ES6 — **no React, Next.js, Tailwind,
  Bootstrap or jQuery**.
- Responsive from 360 px phones to wide desktops (breakpoints at 1120/940/620 px),
  collapsible mobile navigation, sticky dashboard sidebar, modal dialogs.
- Design system with tokens, badges, pills, skeletons, toasts and a dark-friendly
  colour scale; Inter + Sora type pairing.
- Real cinematic education photography from the Unsplash CDN, every `<img>` with a
  gradient/initials fallback so a failed fetch never shows a broken icon.

---

## Tech stack

| Layer | Choice |
| --- | --- |
| Backend | **Python 3.11+**, **FastAPI**, Uvicorn (ASGI) |
| ORM | **SQLAlchemy 2.x** (typed `Mapped[...]` declarations) |
| Validation | Pydantic v2 (+ `email-validator`) |
| Auth | `passlib[pbkdf2_sha256]` password hashing, **PyJWT** tokens, role guards |
| Database | **SQLite** by default (zero setup), **PostgreSQL** ready via `DATABASE_URL` |
| Frontend | Vanilla **HTML5 / CSS3 / ES6 modules-free JS**, `fetch()` against the REST API |
| Docs | Auto-generated OpenAPI at `/docs` (Swagger UI) and `/redoc` |
| Tests | **pytest** + `fastapi.testclient` (205 tests) |

---

## Project structure

```
tutor-matching-platform/
├── backend/                     # FastAPI application
│   ├── main.py                  # app factory, middleware, error handlers, static mount
│   ├── config.py                # env-driven Settings + tiny .env loader
│   ├── database.py              # engine, SessionLocal, Base, init_db(), reset_db()
│   ├── models.py                # all SQLAlchemy tables + enums
│   ├── schemas.py               # Pydantic request/response models & validators
│   ├── auth.py                  # password hashing, JWT issue/verify, role dependencies
│   ├── helpers.py               # notifications, activity log, ratings, serialisers
│   ├── services.py              # search_tutors(), facets, featured tutors, match score
│   ├── seed.py                  # idempotent demo dataset (subjects, users, bookings…)
│   └── routers/
│       ├── __init__.py          # single `api_router` mounted at /api
│       ├── auth.py              # register, login, me, change-password, logout
│       ├── tutors.py            # discovery, profile CRUD, approval, rating
│       ├── availability.py      # weekly slots + date exceptions
│       ├── requests.py          # booking lifecycle
│       ├── reviews.py           # reviews & ratings
│       ├── students.py          # student profile
│       ├── subjects.py          # subject catalogue + favourites
│       ├── notifications.py     # notification centre
│       └── admin.py             # stats, users, moderation, activity log
├── frontend/                    # static site served by FastAPI
│   ├── index.html               # landing page (hero, search, featured, testimonials)
│   ├── login.html               # sign in + one-click demo credentials
│   ├── register.html            # role-aware sign up with live subject picker
│   ├── tutors.html              # search & filter results
│   ├── tutor-profile.html       # public profile + availability + booking modal
│   ├── dashboard.html           # role-aware dashboard shell (?view=… router)
│   ├── 404.html                 # styled not-found page
│   ├── css/styles.css           # the whole design system (no framework)
│   └── js/
│       ├── api.js               # window.API — typed wrapper over every endpoint
│       ├── ui.js                # window.UI — toasts, modals, badges, charts, nav…
│       ├── app.js               # window.App — boot(), route guards, tutor card
│       └── home/login/register/tutors/tutor-profile/dashboard.js
├── tests/                       # 205 pytest tests (API + frontend contract)
│   ├── conftest.py              # isolated temp DB, fixtures, auth helpers
│   ├── test_auth.py             test_tutors.py     test_availability.py
│   ├── test_requests.py         test_reviews.py    test_students_subjects.py
│   └── test_notifications.py    test_admin.py      test_frontend.py
├── scripts/
│   ├── serve.py                 # python scripts/serve.py [--port] [--reseed]
│   └── run.sh                   # bash launcher (installs deps if missing)
├── data/                        # SQLite file (git-ignored, created at runtime)
├── requirements.txt
├── .env.example                 # template — copy to .env
├── .gitignore
└── README.md
```

---

## Quick start

Requires **Python 3.11 or newer**. No Node.js, no build step.

```bash
# 1. unpack / clone, then enter the project
cd tutor-matching-platform

# 2. create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# 3. install dependencies
pip install -r requirements.txt

# 4. create your local configuration
cp .env.example .env               # then edit JWT_SECRET_KEY and ADMIN_PASSWORD

# 5. run it
python scripts/serve.py
```

Open **http://127.0.0.1:8000** — the API, the interactive docs at
**http://127.0.0.1:8000/docs** and the website are all served by the same
process. On first boot the database is created and seeded automatically.

Prefer a single command? `./scripts/run.sh` creates `.env` from the template,
installs missing dependencies and starts the server.

---

## Configuration (`.env`)

`.env.example` documents every variable; nothing sensitive is committed. Values
left unset fall back to safe development defaults in `backend/config.py`.

| Variable | Default | Purpose |
| --- | --- | --- |
| `APP_NAME` / `APP_TAGLINE` | TutorConnect | Branding shown in the UI and `/api` |
| `ENVIRONMENT` | `development` | `development` \| `staging` \| `production` |
| `DEBUG` | `true` in development | Verbose errors, permissive CORS |
| `DATABASE_URL` | `sqlite:///<project>/data/tutorconnect.db` | Any SQLAlchemy URL |
| `DB_ECHO` | `false` | Log every SQL statement |
| `JWT_SECRET_KEY` | *random per process* | **Set this in production** |
| `JWT_ALGORITHM` | `HS256` | Signing algorithm |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `1440` | Token lifetime (24 h) |
| `CORS_ORIGINS` | localhost origins | Comma-separated allow-list |
| `CORS_ALLOW_ALL` | `true` in debug | Convenience switch — disable in production |
| `SEED_DEMO_DATA` | `true` | Seed the demo marketplace on first boot |
| `ADMIN_EMAIL` / `ADMIN_PASSWORD` / `ADMIN_NAME` | see `.env.example` | First administrator |
| `MIN_BOOKING_LEAD_HOURS` | `2` | How far ahead students must book |
| `DEFAULT_PAGE_SIZE` / `MAX_PAGE_SIZE` | `12` / `100` | Pagination |
| `CURRENCY` / `CURRENCY_SYMBOL` | `NGN` / `₦` | Money formatting |

Generate a strong secret with:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

If `JWT_SECRET_KEY` is empty the app still boots, but it generates a random
secret per process, prints a warning and reports `"ephemeral_jwt_secret": true`
from `/api/health` — issued tokens then stop validating after a restart. A key
shorter than 32 bytes (the RFC 7518 minimum for HS256) is accepted but flagged
as `"weak_jwt_secret": true` with instructions for generating a stronger one.

---

## Database

### SQLite (default — zero setup)
The file lives at `data/tutorconnect.db` and is created on first start. Tables are
created with `Base.metadata.create_all()` inside the app's lifespan handler, then
seeded. Delete the file (or run `python scripts/serve.py --reseed`) for a clean slate.

### PostgreSQL (recommended for production)

```bash
createdb tutorconnect
```

```dotenv
DATABASE_URL=postgresql+psycopg2://tutorconnect:YOUR_PASSWORD@localhost:5432/tutorconnect
```

`psycopg2-binary` is already in `requirements.txt`. The engine adds
`pool_pre_ping=True` for non-Site URLs, and SQLite-specific options
(`check_same_thread=False`, `StaticPool` for in-memory test databases) are only
applied when the URL is SQLite — so the exact same code runs on either backend.

Schema migrations: `alembic` is included in the requirements for when you move
past `create_all()`; the models in `backend/models.py` are the single source of
truth for the schema.

---

## Creating the administrator account

The admin is created automatically on first boot from `ADMIN_EMAIL`,
`ADMIN_PASSWORD` and `ADMIN_NAME`. To change it later, either:

1. **Edit `.env` and re-seed** (destroys existing data):
   ```bash
   python scripts/serve.py --reseed
   ```
2. **Promote an existing user** from the running app — sign in as an admin,
   open *Dashboard → Users*, and create or edit an account with role `admin`.
3. **Promote from a shell:**
   ```bash
   cd backend && python -c "
   from database import SessionLocal
   from models import User, UserRole
   with SessionLocal() as db:
       u = db.query(User).filter_by(email='you@example.com').first()
       u.role = UserRole.ADMIN; db.commit(); print('promoted', u.email)"
   ```

Admins can also create further admins through `POST /api/admin/users`.

---

## Demo accounts

Seeded by `backend/seed.py` and printed to the console at startup. The login page
has one-click buttons that fill these in for you.

| Role | Email | Password |
| --- | --- | --- |
| **Admin** | `admin@example.com` | `AdminDemo123` |
| **Tutor** | `chinedu.okafor@example.com` | `TutorDemo123` |
| **Tutor** | `aisha.bello@example.com` | `TutorDemo123` |
| **Tutor** | `ibrahim.musa@example.com` | `TutorDemo123` |
| **Student** | `chiamaka@example.com` | `StudentDemo123` |
| **Student** | `tobi@example.com` | `StudentDemo123` |
| **Student** | `musa@example.com` | `StudentDemo123` |

The dataset contains **32 subjects, 12 tutors** (one deliberately left *pending*
so you can demo moderation), **6 students, 41 weekly availability slots, 16
booking requests** across every status, **6 reviews** and **6 saved tutors** —
plus an activity log so the admin dashboard has real charts on first load.

> Change `ADMIN_PASSWORD` (and every demo password) before deploying anywhere public.

---

## Running the app

```bash
python scripts/serve.py                     # 0.0.0.0:8000
python scripts/serve.py --port 9000         # different port
python scripts/serve.py --reload            # auto-reload while developing
python scripts/serve.py --reseed            # wipe + re-seed, then serve
python scripts/serve.py --no-seed           # empty database
```

Or run Uvicorn directly:

```bash
cd backend
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

What to click through:

1. **`/`** — landing page; the hero search jumps into a real filtered query.
2. **`/tutors.html`** — combine filters (subject + city + budget + weekday +
   rating) and watch the result count, chips and URL query string update.
3. **`/tutor-profile.html?id=1`** — weekly availability grid, next-7-days open
   slots, rating breakdown, reviews, similar tutors. Click **Request a session**.
4. **`/register.html`** — sign up as a tutor; you land on the availability
   manager with an onboarding prompt.
5. **`/dashboard.html`** — role-aware: tutor sees incoming requests and can
   accept/reject; the student who booked sees the status flip instantly and gets
   a notification; after a session is completed the student can leave a review
   and the tutor's rating recalculates everywhere.
6. **Admin → Users / Tutors / Reviews / Subjects** — approve the pending tutor,
   hide a review, add a subject: each change is immediately visible in public
   search.

---

## The API

Base URL `/api`. Interactive docs: **`/docs`** (Swagger UI) and **`/redoc`**.
A machine-readable index of every route is at **`GET /api`**, and
**`GET /api/health`** reports runtime configuration and database reachability.

83 endpoints. The main groups:

| Group | Endpoints |
| --- | --- |
| **Auth** | `POST /auth/register`, `POST /auth/login`, `GET/PUT/DELETE /auth/me`, `POST /auth/change-password`, `POST /auth/logout`, `POST/DELETE /auth/avatar` (device photo upload & delete) |
| **Tutors** | `GET/POST /tutors`, `GET /tutors/facets`, `GET/PUT/DELETE /tutors/me`, `GET /tutors/me/stats`, `POST/DELETE /tutors/me/subjects`, `GET/PUT/DELETE /tutors/{id}`, `PUT /tutors/{id}/status`, `GET/POST/DELETE /tutors/{id}/subjects`, `GET /tutors/{id}/reviews`, `GET /tutors/{id}/rating`, `GET /tutors/{id}/availability`, `GET /tutors/{id}/open-slots` |
| **Availability** | `GET /availability/mine`, `POST /availability`, `PUT/PATCH/DELETE /availability/{slotId}`, `POST /availability/exceptions`, `DELETE /availability/exceptions/{id}` |
| **Requests** | `GET/POST /requests`, `GET /requests/mine/stats`, `GET /requests/upcoming/list`, `GET/PUT/DELETE /requests/{id}`, `PUT /requests/{id}/status`, `POST /requests/{id}/cancel`, `POST /requests/{id}/read` |
| **Reviews** | `POST /reviews`, `GET /reviews/mine`, `GET/PUT/DELETE /reviews/{id}` |
| **Students** | `GET/PUT /students/me` |
| **Subjects & favourites** | `GET/POST /subjects`, `GET /subjects/categories`, `PUT/DELETE /subjects/{id}`, `GET /favorites`, `POST/DELETE /favorites/{tutorId}`, `POST /favorites/{tutorId}/toggle` |
| **Notifications** | `GET /notifications`, `GET /notifications/unread-count`, `POST /notifications/{id}/read`, `POST /notifications/read-all`, `DELETE /notifications/{id}` |
| **Admin** | `GET /admin/stats`, `GET /admin/activity`, `GET/POST /admin/users`, `GET/PUT/DELETE /admin/users/{id}`, `POST /admin/users/{id}/toggle-active`, `GET /admin/tutors`, `GET /admin/requests`, `POST /admin/requests/{id}/cancel`, `DELETE /admin/requests/{id}`, `GET /admin/reviews`, `POST /admin/reviews/{id}/hide`, `POST /admin/reviews/{id}/restore` |

### Conventions

- **Status codes**: `200` read/update, `201` create, `400` bad request,
  `401` missing/invalid token, `403` wrong role or not your resource,
  `404` unknown id, `409` conflict (overlap, duplicate, illegal transition),
  `410` moderated away, `422` validation with a per-field `errors[]` array.
- **Errors** always return `{"detail": "...", "type": "...", "errors": [...]}` —
  human-readable, never a stack trace (even for unhandled exceptions).
- **Lists** return `{"items": [...], "total": n, "page": p, "page_size": s, "pages": n}`.
- **Auth**: `Authorization: Bearer <jwt>`. Tokens carry the user id and role;
  the role is re-read from the database on every request so suspending a user
  takes effect immediately.
- Passwords, password hashes and other users' contact details are never returned
  by any endpoint.

### Example

```bash
# log in
TOKEN=$(curl -s -X POST http://127.0.0.1:8000/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"chiamaka@example.com","password":"StudentDemo123"}' \
  | python -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')

# search: mathematics tutors in Lagos under ₦7,000 with 5+ years, free Saturdays
curl -s "http://127.0.0.1:8000/api/tutors?q=mathematics&location=Lagos&max_price=7000&min_experience=5&day=Saturday&sort=rating"

# book an open slot
curl -s -X POST http://127.0.0.1:8000/api/requests \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"tutor_id":1,"subject_id":1,"preferred_date":"2026-10-12","preferred_time":"16:00",
       "duration_minutes":60,"mode":"hybrid","budget":6000,"message":"Help with calculus."}'
```

---

## Data model

Twelve tables, declared in `backend/models.py` (SQLAlchemy 2.x typed mappings).

| Table | Purpose / notable columns |
| --- | --- |
| `users` | id, email (unique, normalised), password_hash, full_name, role (`tutor`/`student`/`admin`), phone, avatar_url, is_active, last_login_at, timestamps |
| `tutor_profiles` | 1:1 with a tutor user — headline, bio, qualifications, languages, years_experience, hourly_rate, session_duration_minutes, city/state/country, teaching_mode, accepts_online/in_person, cover_image_url, verified, is_visible, approval_status (`pending`/`approved`/`suspended`) |
| `student_profiles` | 1:1 with a student user — education_level, guardian_name, city/state, learning_goals, preferred_mode, max_budget |
| `subjects` | id, name (unique), category, icon, is_active |
| `tutor_subjects` | join table (tutor_profile_id, subject_id) plus `proficiency` and `levels` |
| `availability` | tutor_profile_id, day_of_week, day_index, start_time, end_time, mode, is_active — unique per (tutor, day, start, end) |
| `availability_exceptions` | tutor_profile_id, date, is_blocked, reason — one-off overrides |
| `booking_requests` | tutor_profile_id, student_id, subject_id, preferred_date, preferred_time, duration_minutes, mode, budget, message, location_note, status, tutor_response_note, responded_at/completed_at/cancelled_at, cancel_reason, read_by_student/tutor, timestamps — unique per (tutor, student, subject, date, time) |
| `reviews` | tutor_profile_id, student_id, booking_request_id (unique — one review per session), rating 1–5, title, comment, is_deleted, deleted_reason |
| `favorites` | student_id + tutor_profile_id (unique) |
| `notifications` | user_id, type, title, body, link, is_read |
| `activity_log` | actor_user_id, action, description, entity_type/id — the admin audit trail |

Ratings are **never stored on the tutor**: `helpers.rating_aggregate()` and
`rating_breakdown()` compute them from `reviews` on every read, which is why
hiding or editing a review instantly changes the average, the star breakdown,
the search filter results and the profile card.

---

## Testing

```bash
cd tests
python -m pytest -q                    # 205 tests
python -m pytest -q -p no:cacheprovider          # leave no .pytest_cache behind
SKIP_NETWORK=1 python -m pytest -q               # skip the live image-URL check
python -m pytest test_requests.py -q             # one module
python -m pytest -k "availability and overlap" -q
```

Tests run against an **isolated temporary SQLite database**
(`/tmp/tutorconnect_test.db`) created in `tests/conftest.py`; your development
`data/tutorconnect.db` is never touched. `conftest.py` sets the environment
overrides *before* importing the app, provides session-scoped `client`, `db` and
per-role token fixtures, and ships helpers (`bookable_date()`, `past_weekday()`)
so date-sensitive booking tests stay deterministic regardless of the time of day
they run.

| Module | Covers |
| --- | --- |
| `test_auth.py` | register/login/logout, password rules, duplicate emails, JWT expiry & tampering, role guards, `/auth/me`, change password, account deletion |
| `test_tutors.py` | search by text/subject/location/mode/price/experience/day/rating/verified, sorting, pagination, facets, profile CRUD, subject management, visibility of pending tutors |
| `test_availability.py` | slot CRUD, overlap & duplicate rejection, pause/resume, ownership, date exceptions, open-slot computation (booked times disappear, duration respected), admin override |
| `test_requests.py` | creation + validation, availability consent, duplicates, full `pending → accepted → completed` lifecycle, rejection, cancellation by either party, edit/delete guards, per-user visibility, dashboard stats, upcoming list, notifications |
| `test_reviews.py` | rating maths recomputed from rows, breakdown percentages, one-review-per-booking, completed-session requirement, ownership, edit/delete, admin hide/restore, `min_rating`/`min_reviews` filters |
| `test_students_subjects.py` | auto-created student profile, partial updates, request counters, subject catalogue & filters, marker subject hidden, favourites add/toggle/remove and isolation |
| `test_notifications.py` | notifications for every lifecycle event, unread counts, filters, mark-read/read-all, delete, privacy between users, approval notifications |
| `test_admin.py` | role lockdown of all admin routes, stats integrity, user list/filter/create/update/suspend/delete, self-delete guard, tutor approval & suspension, request and review moderation, activity log, subject CRUD and soft-hide protection |
| `test_frontend.py` | every page and asset is served, required hero copy, no CSS/JS frameworks, output escaping, image fallbacks, `/api` index completeness, no secret leakage, **every `API.*` call in the frontend maps to a real route**, and every remote image URL returns HTTP 200 |

`test_frontend.py` is the one that keeps the two halves honest: it parses
`frontend/js/api.js`, converts concatenated paths (`"/tutors/" + id + "/rating"`)
into route templates and asserts each one exists in the generated OpenAPI schema.

---

## Security notes

- **Passwords**: `pbkdf2_sha256` with a per-password salt via passlib. The hash
  never leaves the database — no endpoint serialises it, and `test_admin.py`
  asserts `password_hash` appears in no response.
- **JWT**: HS256, configurable expiry, role embedded but **re-verified against
  the database** on each request. Tokens are kept in `localStorage` by the SPA
  and cleared on `401`.
- **Secrets**: everything sensitive comes from the environment. `.env` is
  git-ignored; only `.env.example` (placeholders) is committed. With no
  `JWT_SECRET_KEY` the app generates an ephemeral secret and flags it via
  `/api/health` instead of shipping a hard-coded default, and short keys are
  reported as `weak_jwt_secret` at startup.
- **Portable database path**: a relative `sqlite:///./data/...` URL is resolved
  against the project root, so starting the server from `backend/` can never
  create a second stray database.
- **Authorisation**: `require_roles(...)` on every protected route, plus explicit
  ownership checks (a student cannot read another student's request, a tutor
  cannot delete a review, an admin cannot delete their own account).
- **Output escaping**: all dynamic HTML goes through `UI.esc()`; the test suite
  fails if a page stops using it.
- **CORS**: allow-list by default; `CORS_ALLOW_ALL` is a development switch.
- **Error handling**: custom handlers convert validation errors into friendly
  per-field messages and turn unexpected exceptions into a generic 500 with the
  real traceback written to the server log only.
- **Rate limiting / HTTPS** are intentionally left to the deployment layer
  (see below) rather than baked into the app.

---

## Deployment

### 1. PostgreSQL + Uvicorn/Gunicorn (any VPS)

```bash
sudo -u postgres createdb tutorconnect
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt gunicorn
cp .env.example .env && nano .env
```

```dotenv
ENVIRONMENT=production
DEBUG=false
CORS_ALLOW_ALL=false
CORS_ORIGINS=https://tutors.example.com
DATABASE_URL=postgresql+psycopg2://tutorconnect:STRONG_PASSWORD@localhost:5432/tutorconnect
JWT_SECRET_KEY=<output of: python -c "import secrets; print(secrets.token_urlsafe(48))">
ACCESS_TOKEN_EXPIRE_MINUTES=720
SEED_DEMO_DATA=false          # or true once, for a demo deployment
ADMIN_EMAIL=you@yourdomain.com
ADMIN_PASSWORD=<strong, unique>
```

```bash
gunicorn backend.main:app -k uvicorn.workers.UvicornWorker \
         --bind 0.0.0.0:8000 --workers 4 --timeout 60
```

Put nginx (or Caddy) in front for TLS, gzip and static caching; it can serve
`frontend/` directly and proxy `/api` to Uvicorn. Add rate limiting there
(`limit_req_zone`) and set `Strict-Transport-Security` once HTTPS is live.

### 2. Render / Railway / Fly.io
- **Build**: `pip install -r requirements.txt`
- **Start**: `python scripts/serve.py --host 0.0.0.0 --port $PORT`
- **Env vars**: the same production `.env` values above (set `PORT` if the host
  injects it).
- Use a managed PostgreSQL add-on — ephemeral disks lose the SQLite file on
  every redeploy.

### 3. Docker (optional)

```dockerfile
FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["python", "scripts/serve.py", "--host", "0.0.0.0", "--port", "8000"]
```

```bash
docker build -t tutorconnect .
docker run --rm -p 8000:8000 --env-file .env -v $(pwd)/data:/app/data tutorconnect
```

### 4. Static frontend on a CDN
`frontend/` is plain static files. You can host it on Netlify/Vercel/GitHub Pages
and point the `BASE` constant at the top of `js/api.js` (currently the relative path `/api`) at your API origin — just remember to list that
origin in `CORS_ORIGINS`.

---

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `ModuleNotFoundError: No module named 'main'` | Run from the project root (`python scripts/serve.py`) or `cd backend` before `uvicorn main:app`. |
| Port 8000 already in use | `python scripts/serve.py --port 9000`. |
| Login says *"Invalid email or password"* with a demo account | The database was seeded before you changed `ADMIN_EMAIL`/`.env`. Run `python scripts/serve.py --reseed`. |
| `422 … special-use or reserved name` when registering | The email domain is reserved (`.test`, `.local`, `.invalid`). Use a real-looking domain such as `example.com`. |
| Tokens stop working after a restart | `JWT_SECRET_KEY` is unset, so a new ephemeral secret was generated. Set one in `.env`. |
| Search returns no tutors | New tutors self-approve, but tutors created by the seeder can be *pending*; check *Admin → Tutors* and approve them. Also clear any active filter chips. |
| Photos look missing | Remote images need internet access. Every `<img>` falls back to a gradient + initials, so the layout stays intact offline. |
| Tests fail on the image check | Run `SKIP_NETWORK=1 python -m pytest -q` to skip the live URL verification. |
| Want a clean database | `python scripts/serve.py --reseed`, or delete `data/tutorconnect.db*` and restart. |

---

### Licence

MIT — use it, fork it, demo it.
