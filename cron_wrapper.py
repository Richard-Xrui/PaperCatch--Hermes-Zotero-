#!/usr/bin/env python3
"""Cron job wrapper: runs the PaperCatch daily pipeline."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent
PIPELINE = PROJECT_DIR / "daily_pipeline.py"


def _startup_kwargs() -> dict:
    if os.name != "nt":
        return {}
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    return {"startupinfo": startupinfo}


def run() -> subprocess.CompletedProcess:
    os.chdir(PROJECT_DIR)
    return subprocess.run(
        [sys.executable, str(PIPELINE), "--email"],
        cwd=str(PROJECT_DIR),
        capture_output=True,
        text=True,
        timeout=300,
        **_startup_kwargs(),
    )


def main() -> int:
    try:
        result = run()
    except subprocess.TimeoutExpired as exc:
        print(f"CRON_TIMEOUT: {exc}", file=sys.stderr)
        return 1

    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, file=sys.stderr, end="")
    return int(result.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
