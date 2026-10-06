"""
Frontend contract tests.

These do not run a browser. Instead they assert the things that actually break a
vanilla-JS app sitting in front of a live API:

* every page and asset is served by the FastAPI static mount;
* the required marketing copy is present;
* every ``API.*`` call in the frontend maps to a real registered route;
* every remote image URL the app renders returns HTTP 200.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import httpx
import pytest

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"

PAGES = [
    "/",
    "/index.html",
    "/login.html",
    "/register.html",
    "/tutors.html",
    "/tutor-profile.html",
    "/dashboard.html",
    "/404.html",
]

ASSETS = [
    "/css/styles.css",
    "/js/api.js",
    "/js/ui.js",
    "/js/app.js",
    "/js/home.js",
    "/js/login.js",
    "/js/register.js",
    "/js/tutors.js",
    "/js/tutor-profile.js",
    "/js/dashboard.js",
]


# --------------------------------------------------------------------------- #
# Static serving
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("path", PAGES)
def test_pages_are_served(client, path):
    response = client.get(path)
    assert response.status_code == 200, path
    assert response.headers["content-type"].startswith("text/html")
    assert "<!DOCTYPE html>" in response.text


@pytest.mark.parametrize("path", ASSETS)
def test_assets_are_served(client, path):
    response = client.get(path)
    assert response.status_code == 200, path
    expected = "text/css" if path.endswith(".css") else "javascript"
    assert expected in response.headers["content-type"]
    assert len(response.text) > 500, f"{path} looks truncated"


def test_static_mount_never_shadows_the_api(client):
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/tutors").status_code == 200


def test_unknown_api_route_returns_json_404(client):
    response = client.get("/api/does-not-exist")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
    assert "detail" in response.json()


def test_unknown_page_returns_the_styled_404(client):
    response = client.get("/no-such-page.html")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("text/html")
    assert "We couldn&#39;t find that page" in response.text or "couldn't find that page" in response.text
    assert "/css/styles.css" in response.text

    # deep links also fall through to it
    assert client.get("/tutors/9999").status_code == 404
    # but API paths stay JSON so fetch() can handle them
    api = client.get("/api/nope")
    assert api.status_code == 404
    assert api.headers["content-type"].startswith("application/json")


# --------------------------------------------------------------------------- #
# Content requirements from the brief
# --------------------------------------------------------------------------- #
def test_landing_page_carries_the_required_copy(client):
    html = client.get("/").text
    assert "Find the Right Tutor" in html
    assert "Learn With Confidence" in html
    assert "Find a Tutor" in html
    assert "Become a Tutor" in html
    lowered = html.lower()
    for phrase in ("subject", "location", "availability", "experience", "budget"):
        assert phrase in lowered, f"missing '{phrase}' in the hero supporting text"


def test_pages_link_the_shared_assets():
    for page in PAGES[1:]:
        html = (FRONTEND / page.lstrip("/")).read_text(encoding="utf-8")
        assert "css/styles.css" in html, page
        assert "js/api.js" in html, page
        assert "js/ui.js" in html, page
        assert 'name="viewport"' in html, f"{page} is not responsive-ready"


def test_css_is_responsive():
    css = (FRONTEND / "css" / "styles.css").read_text(encoding="utf-8")
    assert css.count("@media") >= 3, "expected desktop/tablet/mobile breakpoints"
    assert "prefers-reduced-motion" in css or "transition" in css


FRAMEWORK_SIGNATURES = (
    "bootstrap.min.css",
    "cdn.jsdelivr.net/npm/bootstrap",
    "tailwindcss",
    "tailwind.config",
    "react-dom",
    "from \"react\"",
    "next/router",
    "vue.global",
    "angular.min",
    "jquery.min",
)


def test_no_css_or_js_frameworks_are_used():
    """The brief forbids React/Next/Tailwind/Bootstrap/jQuery - keep it vanilla."""
    for path in FRONTEND.rglob("*"):
        if path.suffix not in {".html", ".js", ".css"}:
            continue
        text = path.read_text(encoding="utf-8").lower()
        for signature in FRAMEWORK_SIGNATURES:
            assert signature not in text, f"{path.relative_to(FRONTEND)} pulls in {signature}"


def test_no_python_style_unicode_escapes_leaked_into_frontend():
    """`\\U0001f4cd` inside JS is a syntax error, so the build step must convert them."""
    pattern = re.compile(r"\\U[0-9a-fA-F]{8}")
    for path in list(FRONTEND.rglob("*.js")) + list(FRONTEND.rglob("*.html")):
        assert not pattern.search(path.read_text(encoding="utf-8")), path.name


def test_html_escapes_user_content():
    """Every page that renders DB strings must go through UI.esc()."""
    ui = (FRONTEND / "js" / "ui.js").read_text(encoding="utf-8")
    assert "function esc(" in ui
    for entity in ("&amp;", "&lt;", "&gt;", "&quot;", "&#39;"):
        assert entity in ui, f"esc() does not encode {entity}"

    for name in ("dashboard.js", "tutors.js", "tutor-profile.js", "home.js"):
        source = (FRONTEND / "js" / name).read_text(encoding="utf-8")
        imports_esc = re.search(r"\besc\b\s*[,}=]", source) is not None
        calls_esc = re.search(r"\besc\(", source) is not None
        assert imports_esc or calls_esc, f"{name} never uses the esc() helper"


def test_frontend_always_has_an_image_fallback():
    """Remote photos can fail, so every <img> the app builds needs a fallback."""
    source = (FRONTEND / "js" / "ui.js").read_text(encoding="utf-8")
    assert 'addEventListener("error"' in source or "onerror" in source
    assert "initials" in source
    assert "avatar-fallback" in source or "gradient" in source.lower()

    # a static <img> may point at a CDN, but only if it can degrade gracefully
    bare = re.compile(r'<img(?![^>]*\bonerror=)[^>]*src="https?://', re.S)
    for path in FRONTEND.rglob("*.html"):
        html = path.read_text(encoding="utf-8")
        assert not bare.search(html), f"{path.name} has a remote <img> with no onerror fallback"


# --------------------------------------------------------------------------- #
# Meta endpoints
# --------------------------------------------------------------------------- #
def test_health_endpoint(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["database_reachable"] is True
    assert body["version"]
    assert body["database"] in {"sqlite", "postgresql"}
    # these are boolean warning flags about the *configuration*, never values
    assert body["ephemeral_jwt_secret"] is False
    assert body["weak_jwt_secret"] is False
    assert not _looks_like_a_secret(str(body))


def test_api_index_lists_every_endpoint(client):
    index = client.get("/api").json()
    assert index["name"] == "TutorConnect"
    assert index["docs"] == "/docs"
    assert index["endpoint_count"] == len(index["endpoints"])
    assert index["endpoint_count"] > 60

    paths = {route["path"] for route in index["endpoints"]}
    assert all(route["path"].startswith("/api") for route in index["endpoints"])
    for expected in (
        "/api/auth/register", "/api/auth/login", "/api/tutors", "/api/availability",
        "/api/requests", "/api/reviews", "/api/subjects", "/api/students/me",
        "/api/notifications", "/api/admin/stats",
    ):
        assert expected in paths, f"{expected} missing from the API index"


def test_public_config_endpoint(client):
    config = client.get("/api/config").json()
    assert config["app_name"] == "TutorConnect"
    assert config["currency"] == "NGN"
    assert config["currency_symbol"] == "₦"
    assert config["min_booking_lead_hours"] >= 1
    assert config["default_page_size"] >= 1
    text = str(config).lower()
    for leak in ("jwt_secret", "secret_key", "admin_password", "database_url"):
        assert leak not in text


def test_no_secret_leaks_in_public_responses(client):
    for path in ("/api/health", "/api/config", "/api/subjects", "/api/tutors", "/api"):
        text = client.get(path).text.lower()
        for leak in ("password_hash", "secret_key", "admin_password", "database_url", "sqlite:///"):
            assert leak not in text, f"{path} leaks {leak}"
        assert not _looks_like_a_secret(client.get(path).text), path


def _looks_like_a_secret(text: str) -> bool:
    """True when a payload carries something that looks like a real credential."""
    return bool(
        re.search(r"(password_hash|secret_key|api_key)\s*[\"']?\s*[:=]\s*[\"'][^\"']{8,}", text, re.I)
        or re.search(r"bearer\s+[A-Za-z0-9_\-\.]{20,}", text, re.I)
    )


def test_interactive_docs_are_enabled(client):
    assert client.get("/docs").status_code == 200
    assert client.get("/openapi.json").status_code == 200
    schema = client.get("/openapi.json").json()
    assert schema["info"]["title"]
    assert len(schema["paths"]) > 40


# --------------------------------------------------------------------------- #
# Every API call the frontend makes must exist on the server
# --------------------------------------------------------------------------- #
CALL_RE = re.compile(
    r'request\(\s*"(GET|POST|PUT|PATCH|DELETE)"\s*,\s*"([^"]*)"((?:\s*\+[^,]*?)?)\s*[,)]',
    re.S,
)


def _frontend_api_calls() -> set[tuple[str, str]]:
    """Extract (METHOD, path) pairs from js/api.js.

    Paths are frequently built by concatenation -
    ``request("GET", "/tutors/" + id + "/rating")`` - so every non-literal chunk
    becomes a ``{}`` placeholder and the result is compared against the server's
    route templates.
    """
    source = (FRONTEND / "js" / "api.js").read_text(encoding="utf-8")
    calls: set[tuple[str, str]] = set()
    for match in CALL_RE.finditer(source):
        method, first, tail = match.group(1), match.group(2), match.group(3)
        path = "/api" + first
        if tail.strip():
            segments = re.findall(r'"([^"]*)"', tail)
            if tail.lstrip().lstrip("+").strip().startswith('"'):
                # "/tutors/" + id + "/rating" -> literal, dynamic, literal ...
                for index, segment in enumerate(segments):
                    path += ("{}" if index % 2 == 0 else segment)
                if len(segments) % 2 == 1:
                    path += "{}"
            else:
                # "/availability/" + slotId  -> dynamic tail
                path += "{}" + "".join(segments)
        calls.add((method, path))
    return calls


def _server_route_keys(client) -> set[tuple[str, str]]:
    keys = set()
    for path, operations in client.app.openapi().get("paths", {}).items():
        template = re.sub(r"\{[^}]+\}", "{}", path)
        for method in operations:
            if method.upper() in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
                keys.add((method.upper(), template))
    return keys


def test_every_frontend_endpoint_exists(client):
    server = _server_route_keys(client)
    calls = _frontend_api_calls()
    assert len(calls) > 40, f"only extracted {len(calls)} calls - the regex needs updating"

    missing = sorted(f"{method} {path}" for method, path in calls if (method, path) not in server)
    assert not missing, "frontend calls endpoints the API does not expose:\n  " + "\n  ".join(missing)


# --------------------------------------------------------------------------- #
# Remote imagery must not 404 (the brief forbids broken images)
# --------------------------------------------------------------------------- #
def _live_image_urls(client) -> list[str]:
    urls: set[str] = set()
    for tutor in client.get("/api/tutors", params={"page_size": 100}).json()["items"]:
        detail = client.get(f"/api/tutors/{tutor['id']}").json()
        for key in ("avatar_url", "cover_image_url"):
            value = detail.get(key)
            if value and str(value).startswith("http"):
                urls.add(value)
    return sorted(urls)


@pytest.mark.skipif(os.environ.get("SKIP_NETWORK") == "1", reason="SKIP_NETWORK=1")
def test_remote_tutor_images_resolve(client):
    urls = _live_image_urls(client)
    assert len(urls) >= 10, "the demo dataset should ship real photos"

    broken = []
    with httpx.Client(timeout=25, follow_redirects=True,
                      headers={"User-Agent": "Mozilla/5.0"}) as http:
        for url in urls[:45]:
            try:
                response = http.head(url)
                if response.status_code >= 400:
                    response = http.get(url)
                if response.status_code >= 400:
                    broken.append(f"{url} -> {response.status_code}")
            except httpx.HTTPError as exc:  # pragma: no cover - network flake
                broken.append(f"{url} -> {exc.__class__.__name__}")

    assert not broken, "broken image URLs:\n" + "\n".join(broken)
