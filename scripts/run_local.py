"""Build the React dashboard and serve Arkagni from a single FastAPI server.

The built SPA is written to ``frontend/dist`` and mounted by
``backend.main`` at ``/``, so the API, docs, and dashboard share one origin
and one port:

    http://localhost:8000

Run with:
    .venv\\Scripts\\python.exe scripts\\run_local.py
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
URL = "http://localhost:8000"
HOST = "127.0.0.1"
PORT = "8000"
DIST_INDEX = PROJECT_ROOT / "frontend" / "dist" / "index.html"


def _announce() -> None:
    print("", flush=True)
    print(URL, flush=True)
    print("", flush=True)


def _find_npm() -> str:
    for name in ("npm.cmd", "npm"):
        found = shutil.which(name)
        if found:
            return found
    fallback = Path(r"C:\Program Files\nodejs\npm.cmd")
    if fallback.is_file():
        return str(fallback)
    raise SystemExit(
        "npm was not found. Add Node.js to PATH or install it from https://nodejs.org/."
    )


def _build_dashboard() -> None:
    """Build frontend/dist so FastAPI can serve the SPA from /."""
    if os.environ.get("ARKAGNI_SKIP_BUILD", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        if not DIST_INDEX.is_file():
            raise SystemExit(
                "ARKAGNI_SKIP_BUILD is set but frontend/dist/index.html is missing."
            )
        return
    result = subprocess.run(
        [_find_npm(), "--prefix", "frontend", "run", "build"],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        if result.stdout:
            print(result.stdout, file=sys.stderr)
        if result.stderr:
            print(result.stderr, file=sys.stderr)
        raise SystemExit(f"Dashboard build failed with exit code {result.returncode}.")


def _stop(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()


def main() -> int:
    _build_dashboard()
    _announce()

    env = os.environ.copy()
    env.setdefault("PYTHONUNBUFFERED", "1")
    env.setdefault("ARKAGNI_URL", URL)
    # The launcher already printed the only URL; keep the child log quiet.
    env.setdefault("ARKAGNI_SILENT_STARTUP", "1")

    server = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "backend.main:app",
            "--host",
            HOST,
            "--port",
            PORT,
            "--log-level",
            "warning",
        ],
        cwd=PROJECT_ROOT,
        env=env,
    )

    try:
        return server.wait()
    except KeyboardInterrupt:
        print("\nStopping Arkagni...", flush=True)
        return 0
    finally:
        _stop(server)


if __name__ == "__main__":
    raise SystemExit(main())
