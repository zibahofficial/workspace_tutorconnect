#!/usr/bin/env python3
"""
Start the TutorConnect API + frontend with a single command.

    python scripts/serve.py                  # http://127.0.0.1:8000
    python scripts/serve.py --port 9000
    python scripts/serve.py --host 0.0.0.0 --reload
    python scripts/serve.py --reseed         # wipe the DB and re-seed first

Works from any directory: it puts ``backend/`` on ``sys.path`` and lets
``backend/config.py`` load the project ``.env`` (the default ``DATABASE_URL`` is
an absolute path, so the current working directory does not matter).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the TutorConnect platform.")
    parser.add_argument("--host", default="0.0.0.0", help="bind address (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8000, help="port (default: 8000)")
    parser.add_argument("--reload", action="store_true", help="auto-reload on code changes")
    parser.add_argument("--reseed", action="store_true", help="delete the database and seed it again")
    parser.add_argument("--no-seed", action="store_true", help="start with an empty database")
    args = parser.parse_args()

    # ``backend`` must be importable as a flat package (main, models, routers...).
    sys.path.insert(0, str(BACKEND))

    if args.no_seed:
        import os

        os.environ["SEED_DEMO_DATA"] = "false"

    if args.reseed:
        from database import reset_db
        from seed import print_demo_credentials, seed_database

        reset_db()
        from database import SessionLocal, init_db

        init_db()
        with SessionLocal() as db:
            seed_database(db, force=True)
            db.commit()
        print_demo_credentials()

    try:
        import uvicorn
    except ImportError:  # pragma: no cover
        print(
            "uvicorn is not installed. Run:\n"
            f"    python -m pip install -r {ROOT / 'requirements.txt'}",
            file=sys.stderr,
        )
        return 1

    print(f"\n  TutorConnect -> http://127.0.0.1:{args.port}   (API docs at /docs)\n")
    uvicorn.run(
        "main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        reload_dirs=[str(BACKEND), str(ROOT / "frontend")] if args.reload else None,
        app_dir=str(BACKEND),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
