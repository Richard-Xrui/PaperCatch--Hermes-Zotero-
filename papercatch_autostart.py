#!/usr/bin/env python3
"""Ensure PaperCatch is configured and running.

This file is intentionally small and hook-friendly: Hermes can run it on
``on_session_start`` and it will return quickly after starting PaperCatch in
the background when needed.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
LOG_DIR = BASE_DIR / "logs"
LOG_FILE = LOG_DIR / "papercatch_autostart.log"


def main() -> None:
    parser = argparse.ArgumentParser(description="Ensure PaperCatch is running")
    parser.add_argument("--ensure", action="store_true", help="configure discovered defaults and start if needed")
    parser.add_argument("--status", action="store_true", help="print JSON status")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    if args.status:
        print(json.dumps(status(args.port), ensure_ascii=False, indent=2))
        return

    if args.ensure:
        result = ensure_running(args.port)
        # Hermes shell hooks expect optional JSON on stdout.
        print(json.dumps(result, ensure_ascii=False))
        return

    parser.print_help()


def ensure_running(port: int) -> dict:
    LOG_DIR.mkdir(exist_ok=True)
    if health_ok(port):
        return {"ok": True, "already_running": True, "url": f"http://localhost:{port}"}

    run_quiet([sys.executable, str(BASE_DIR / "start.py"), "--setup", "--yes"])

    proc = start_background(port)
    deadline = time.time() + 8
    while time.time() < deadline:
        if health_ok(port):
            return {
                "ok": True,
                "started": True,
                "pid": proc.pid,
                "url": f"http://localhost:{port}",
            }
        time.sleep(0.5)
    return {"ok": False, "started": True, "pid": proc.pid, "error": "health check timed out"}


def status(port: int) -> dict:
    return {
        "running": health_ok(port),
        "url": f"http://localhost:{port}",
        "log": str(LOG_FILE),
    }


def health_ok(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=0.6) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data.get("status") == "ok"
    except Exception:
        return False


def start_background(port: int) -> subprocess.Popen:
    LOG_DIR.mkdir(exist_ok=True)
    log = open(LOG_FILE, "a", encoding="utf-8")
    cmd = [
        sys.executable,
        str(BASE_DIR / "start.py"),
        "--port",
        str(port),
        "--no-browser",
    ]
    kwargs = {
        "cwd": str(BASE_DIR),
        "stdin": subprocess.DEVNULL,
        "stdout": log,
        "stderr": subprocess.STDOUT,
    }
    if os.name == "nt":
        kwargs["creationflags"] = (
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            | getattr(subprocess, "CREATE_NO_WINDOW", 0)
        )
    else:
        kwargs["start_new_session"] = True
    return subprocess.Popen(cmd, **kwargs)


def run_quiet(cmd: list[str]) -> None:
    with open(LOG_FILE, "a", encoding="utf-8") as log:
        subprocess.run(
            cmd,
            cwd=str(BASE_DIR),
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            timeout=30,
            check=False,
        )


if __name__ == "__main__":
    main()
