#!/usr/bin/env python3
"""Read-only discovery for locally installed Zotero and Hermes."""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import sys
from pathlib import Path
from urllib.request import urlopen


BASE_DIR = Path(__file__).resolve().parent


def discover_local_tools() -> dict:
    zotero = discover_zotero()
    hermes = discover_hermes()
    return {"zotero": zotero, "hermes": hermes}


def discover_zotero() -> dict:
    executable = find_zotero_executable()
    profiles = find_zotero_profiles()
    data_dirs = find_zotero_data_dirs(profiles)
    sqlite_path = next((path / "zotero.sqlite" for path in data_dirs if (path / "zotero.sqlite").exists()), None)
    user_id = read_zotero_user_id(sqlite_path) if sqlite_path else ""
    connector = check_zotero_connector()

    return {
        "found": bool(executable or data_dirs or profiles or connector["running"]),
        "executable": str(executable) if executable else "",
        "profile_dirs": [str(path) for path in profiles],
        "data_dirs": [str(path) for path in data_dirs],
        "sqlite": str(sqlite_path) if sqlite_path else "",
        "user_id": user_id,
        "connector": connector,
        "notes": [
            "Discovery is read-only.",
            "PaperCatch never writes Zotero's local sqlite database directly.",
            "For automatic import, Zotero Web API credentials are still the safest path.",
        ],
    }


def find_zotero_executable() -> Path | None:
    for name in ("zotero", "zotero.exe"):
        found = shutil.which(name)
        if found:
            return Path(found)

    candidates = []
    if sys.platform.startswith("win"):
        program_files = [os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)"), os.environ.get("LOCALAPPDATA")]
        for root in [Path(item) for item in program_files if item]:
            candidates.extend([
                root / "Zotero" / "zotero.exe",
                root / "Programs" / "Zotero" / "zotero.exe",
            ])
    elif sys.platform == "darwin":
        candidates.extend([
            Path("/Applications/Zotero.app/Contents/MacOS/zotero"),
            Path.home() / "Applications" / "Zotero.app" / "Contents" / "MacOS" / "zotero",
        ])
    else:
        candidates.extend([
            Path("/usr/bin/zotero"),
            Path("/usr/local/bin/zotero"),
            Path("/opt/Zotero/zotero"),
            Path.home() / ".local" / "bin" / "zotero",
        ])

    return next((path for path in candidates if path.exists()), None)


def find_zotero_profiles() -> list[Path]:
    roots = []
    if sys.platform.startswith("win"):
        appdata = os.environ.get("APPDATA")
        if appdata:
            roots.append(Path(appdata) / "Zotero" / "Zotero" / "Profiles")
    elif sys.platform == "darwin":
        roots.append(Path.home() / "Library" / "Application Support" / "Zotero" / "Profiles")
    else:
        roots.extend([
            Path.home() / ".zotero" / "zotero",
            Path.home() / ".zotero" / "Zotero" / "Profiles",
        ])

    profiles = []
    for root in roots:
        if root.exists():
            profiles.extend([path for path in root.iterdir() if path.is_dir()])
    return unique_paths(profiles)


def find_zotero_data_dirs(profiles: list[Path]) -> list[Path]:
    candidates = [Path.home() / "Zotero"]
    for profile in profiles:
        prefs = profile / "prefs.js"
        if prefs.exists():
            candidates.extend(parse_zotero_data_dirs_from_prefs(prefs))
        candidates.append(profile / "zotero")

    return unique_paths([path for path in candidates if (path / "zotero.sqlite").exists()])


def parse_zotero_data_dirs_from_prefs(prefs: Path) -> list[Path]:
    paths = []
    try:
        text = prefs.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return paths

    for line in text.splitlines():
        if "extensions.zotero.dataDir" not in line:
            continue
        parts = line.split(",", 1)
        if len(parts) != 2:
            continue
        raw = parts[1].rsplit(")", 1)[0].strip().strip(";").strip()
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            value = raw.strip('"')
        if value:
            paths.append(Path(os.path.expandvars(os.path.expanduser(value))))
    return paths


def read_zotero_user_id(sqlite_path: Path | None) -> str:
    if not sqlite_path or not sqlite_path.exists():
        return ""
    try:
        uri = f"file:{sqlite_path.as_posix()}?mode=ro&immutable=1"
        with sqlite3.connect(uri, uri=True, timeout=0.2) as conn:
            candidates = [
                "SELECT value FROM settings WHERE setting='sync' AND key='userID' LIMIT 1",
                "SELECT value FROM settings WHERE setting='sync' AND key='userID_local' LIMIT 1",
            ]
            for query in candidates:
                try:
                    row = conn.execute(query).fetchone()
                except sqlite3.Error:
                    continue
                if row and str(row[0]).strip():
                    return str(row[0]).strip()
    except sqlite3.Error:
        return ""
    return ""


def check_zotero_connector() -> dict:
    url = "http://127.0.0.1:23119/connector/ping"
    try:
        with urlopen(url, timeout=0.5) as resp:
            body = resp.read(200).decode("utf-8", errors="replace")
        return {"running": True, "url": url, "response": body}
    except Exception:
        return {"running": False, "url": url, "response": ""}


def discover_hermes() -> dict:
    executable = find_hermes_executable()
    homes = find_hermes_homes()
    return {
        "found": bool(executable or homes),
        "executable": str(executable) if executable else "",
        "home_dirs": [str(path) for path in homes],
        "suggested_command": str(executable) if executable else "",
        "notes": [
            "If the Hermes command does not emit PaperCatch plan JSON, configure HERMES_API_URL instead.",
            "PaperCatch falls back to its built-in parser when Hermes is unavailable.",
        ],
    }


def find_hermes_executable() -> Path | None:
    for name in ("hermes", "hermes.exe"):
        found = shutil.which(name)
        if found:
            return Path(found)

    candidates = [
        Path.home() / ".hermes" / "bin" / ("hermes.exe" if sys.platform.startswith("win") else "hermes"),
        Path.home() / "hermes" / ("hermes.exe" if sys.platform.startswith("win") else "hermes"),
        BASE_DIR.parent / "hermes" / ("hermes.exe" if sys.platform.startswith("win") else "hermes"),
        BASE_DIR.parent / "Hermes" / ("hermes.exe" if sys.platform.startswith("win") else "hermes"),
    ]
    return next((path for path in candidates if path.exists()), None)


def find_hermes_homes() -> list[Path]:
    candidates = [
        Path.home() / ".hermes",
        Path.home() / "hermes",
        Path.home() / "Hermes",
        BASE_DIR.parent / "hermes",
        BASE_DIR.parent / "Hermes",
    ]
    return unique_paths([path for path in candidates if path.exists()])


def unique_paths(paths: list[Path]) -> list[Path]:
    seen = set()
    out = []
    for path in paths:
        try:
            key = str(path.resolve()).lower()
        except OSError:
            key = str(path).lower()
        if key not in seen:
            out.append(path)
            seen.add(key)
    return out


if __name__ == "__main__":
    print(json.dumps(discover_local_tools(), ensure_ascii=False, indent=2))
