"""
TutorConnect API — FastAPI application entrypoint.

Run (from the `backend/` directory):
    uvicorn main:app --host 0.0.0.0 --port 8000 --reload

The same process also serves the frontend from `../frontend`, so a single port
hosts the whole product (useful for demos and single-container deployments).
Interactive API docs: /docs   |   Health: /api/health
"""
from __future__ import annotations

import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict

from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from config import FRONTEND_DIR, settings
from database import SessionLocal, init_db
from routers import api_router

BANNER = r"""
  _______              __  __       _            _
 |__   __|             |  \/  |     | |          | |
    | | _   _  ___ _ __| \  / | __ _| |_ ___  ___| |__
    | || | | |/ _ \ '__| |\/| |/ _` | __/ __|/ __| '_ \
    | || |_| |  __/ |  | |  | | (_| | |_\__ \ (__| | | |
    |_| \__,_|\___|_|  |_|  |_|\__,_|\__|___/\___|_| |_|
    Find the right tutor. Learn with confidence.
"""


# --------------------------------------------------------------------------- #
# Lifespan: create tables + seed demo data once at startup
# --------------------------------------------------------------------------- #
@asynccontextmanager
async def lifespan(app: FastAPI):
    print(BANNER)
    init_db()
    with SessionLocal() as db:
        if settings.seed_demo_data:
            try:
                from seed import print_demo_credentials, seed_database

                created = seed_database(db, force=False)
                db.commit()
                if created:
                    print_demo_credentials()
            except Exception as exc:  # pragma: no cover - seeding must never kill the app
                db.rollback()
                print(f"[startup] Seeding skipped ({exc.__class__.__name__}: {exc})")
        else:
            print("[startup] SEED_DEMO_DATA=false - starting with an empty database.")

    if settings.jwt_secret_is_ephemeral:
        print(
            "[startup] WARNING: JWT_SECRET_KEY is not set - an ephemeral secret was generated. "
            "Tokens will be invalidated on restart. Set it in your .env for production."
        )
    print(f"[startup] Environment: {settings.environment} | Database: {settings.summary()['database']}")
    print(f"[startup] Frontend directory: {FRONTEND_DIR}")
    yield
    print("[shutdown] TutorConnect API stopped.")


app = FastAPI(
    title=f"{settings.app_name} API",
    description=(
        "Full-stack Tutor & Student Matching Platform - REST API.\n\n"
        "**Roles:** tutor, student, admin. Authenticate with `POST /api/auth/login` and send the "
        "returned JWT as `Authorization: Bearer <token>`.\n\n"
        "**Demo accounts** (created by the seeder): "
        "`chinedu.okafor@example.com / TutorDemo123`, "
        "`chiamaka@example.com / StudentDemo123`, "
        "`admin@example.com / AdminDemo123`."
    ),
    version="1.0.0",
    contact={"name": f"{settings.app_name} Engineering", "url": "https://example.com"},
    license_info={"name": "MIT"},
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

# --------------------------------------------------------------------------- #
# Middleware
# --------------------------------------------------------------------------- #
if settings.cors_allow_all:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Process-Time"],
    )
else:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Requested-With"],
        expose_headers=["X-Process-Time"],
    )


@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    response.headers["X-Process-Time"] = f"{(time.perf_counter() - start) * 1000:.1f}ms"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    return response


# --------------------------------------------------------------------------- #
# Consistent, friendly error payloads
# --------------------------------------------------------------------------- #
def _error(payload: Dict[str, Any], status_code: int, headers: Dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse(status_code=status_code, content=payload, headers=headers)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Turn pydantic errors into readable sentences for the UI."""
    messages = []
    for error in exc.errors():
        location = [str(part) for part in error.get("loc", []) if part not in ("body", "query")]
        field = location[-1] if location else "request"
        message = error.get("msg", "Invalid value")
        if message.startswith("Value error, "):
            message = message[len("Value error, "):]
        messages.append({"field": field, "message": message})

    detail = messages[0]["message"] if messages else "Please check the form and try again."
    return _error(
        {
            "detail": detail,
            "errors": messages,
            "type": "validation_error",
        },
        status.HTTP_422_UNPROCESSABLE_ENTITY,
    )


@app.exception_handler(ValidationError)
async def pydantic_validation_handler(request: Request, exc: ValidationError):
    return _error(
        {"detail": "The submitted data is invalid.", "errors": exc.errors(), "type": "validation_error"},
        status.HTTP_422_UNPROCESSABLE_ENTITY,
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    detail = exc.detail if isinstance(exc.detail, str) else "Request failed."
    return _error(
        {"detail": detail, "status_code": exc.status_code, "type": "http_error"},
        exc.status_code,
        headers=getattr(exc, "headers", None),
    )


@app.exception_handler(IntegrityError)
async def integrity_exception_handler(request: Request, exc: IntegrityError):
    return _error(
        {
            "detail": (
                "That change conflicts with existing data (a duplicate or a related record is "
                "still in use). Please adjust and try again."
            ),
            "type": "database_conflict",
        },
        status.HTTP_409_CONFLICT,
    )


@app.exception_handler(SQLAlchemyError)
async def sqlalchemy_exception_handler(request: Request, exc: SQLAlchemyError):
    # Never leak SQL or driver details to clients.
    print(f"[error] SQLAlchemyError on {request.url.path}: {exc}")
    return _error(
        {"detail": "A database error occurred. Please try again.", "type": "database_error"},
        status.HTTP_500_INTERNAL_SERVER_ERROR,
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    print(f"[error] Unhandled {exc.__class__.__name__} on {request.url.path}: {exc}")
    return _error(
        {"detail": "Something went wrong on our side. Please try again.", "type": "server_error"},
        status.HTTP_500_INTERNAL_SERVER_ERROR,
    )


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #
app.include_router(api_router)


@app.get("/api/health", tags=["Meta"], summary="Health & runtime configuration")
def health() -> Dict[str, Any]:
    from sqlalchemy import text

    db_ok = True
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
    except Exception:  # pragma: no cover
        db_ok = False

    info = settings.summary()
    info.update({"status": "ok" if db_ok else "degraded", "database_reachable": db_ok, "version": app.version})
    return info


@app.get("/api", tags=["Meta"], summary="API index")
def api_index() -> Dict[str, Any]:
    """Machine-readable list of every registered endpoint.

    Built from the generated OpenAPI schema rather than ``app.routes``: this
    FastAPI version stores included routers inside an opaque ``_IncludedRouter``,
    so walking ``app.routes`` would only see the routes declared directly on the
    app. The schema is generated once and cached by FastAPI.
    """
    routes = []
    for path, operations in app.openapi().get("paths", {}).items():
        if not path.startswith("/api"):
            continue
        for method, operation in operations.items():
            if method.upper() not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
                continue
            routes.append(
                {
                    "method": method.upper(),
                    "path": path,
                    "summary": operation.get("summary") or operation.get("operationId", ""),
                    "tags": operation.get("tags") or [],
                }
            )
    routes.sort(key=lambda r: (r["path"], r["method"]))
    return {
        "name": settings.app_name,
        "tagline": settings.app_tagline,
        "version": app.version,
        "docs": "/docs",
        "endpoint_count": len(routes),
        "endpoints": routes,
    }


@app.get("/api/config", tags=["Meta"], summary="Public client configuration")
def client_config() -> Dict[str, Any]:
    """Non-secret configuration the frontend needs at runtime."""
    return {
        "app_name": settings.app_name,
        "tagline": settings.app_tagline,
        "currency": settings.currency,
        "currency_symbol": settings.currency_symbol,
        "min_booking_lead_hours": settings.min_booking_lead_hours,
        "default_page_size": settings.default_page_size,
        "environment": settings.environment,
    }


# --------------------------------------------------------------------------- #
# Static frontend (mounted last so /api/* always wins)
# --------------------------------------------------------------------------- #
@app.api_route("/api/{unmatched:path}", include_in_schema=False)
def api_not_found(unmatched: str) -> JSONResponse:
    """JSON 404 for unknown API paths.

    Declared *before* the static mount below: otherwise the mount at "/" would
    swallow the request and answer with plain text, which breaks ``fetch()``
    callers that expect JSON errors.
    """
    return JSONResponse(
        {
            "detail": f"No API endpoint matches /api/{unmatched}. "
                      "Browse the full list at /api or the docs at /docs.",
            "type": "not_found",
        },
        status_code=status.HTTP_404_NOT_FOUND,
    )


if FRONTEND_DIR.exists():
    app.mount(
        "/",
        StaticFiles(directory=str(FRONTEND_DIR), html=True, check_dir=True),
        name="frontend",
    )

    @app.get("/{unknown_path:path}", include_in_schema=False)
    def page_not_found(unknown_path: str, request: Request) -> Response:
        """Serve the styled 404 page for any unmatched non-API GET request.

        The static mount above answers first whenever the file exists, so this
        only ever runs for genuinely unknown paths. API routes keep returning
        JSON so ``fetch()`` callers can show a friendly error instead of HTML.
        """
        if unknown_path.startswith("api/") or unknown_path == "api":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No API endpoint matches /{unknown_path}. See /api for the full list.",
            )
        page = FRONTEND_DIR / "404.html"
        if not page.exists():  # pragma: no cover
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")
        return HTMLResponse(page.read_text(encoding="utf-8"), status_code=status.HTTP_404_NOT_FOUND)
else:  # pragma: no cover
    @app.get("/", include_in_schema=False)
    def missing_frontend():
        return JSONResponse(
            {
                "detail": (
                    "Frontend directory not found. Expected it at "
                    f"{FRONTEND_DIR}. The API is still available at /api."
                )
            },
            status_code=status.HTTP_404_NOT_FOUND,
        )


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(__import__("os").getenv("PORT", "8000")),
        reload=settings.debug,
    )
