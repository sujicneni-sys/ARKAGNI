"""Run the reproducible L2-L5 analysis on the frozen L1 canonical table.

Usage:
    .venv\\Scripts\\python.exe scripts\\03_run_analysis.py
    .venv\\Scripts\\python.exe scripts\\03_run_analysis.py --force
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from pyroharmonize.analysis import run_analysis  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="ignore existing results")
    args = parser.parse_args()
    result = run_analysis(force=args.force)
    if result.get("skipped"):
        print("[analysis] existing results are current; use --force to rebuild")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
