#!/usr/bin/env python3
"""
PaperCatch launcher.

Common commands:
  python start.py            Start the web app with auto-reload
  python start.py --setup    Create or update config.local.json
  python start.py --doctor   Check local configuration
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

from config import CONFIG_FILE, DEFAULT_CONFIG, load_config, public_status, save_config
from hermes_integration import install_autostart
from local_discovery import discover_local_tools


BASE_DIR = Path(__file__).resolve().parent
WATCHED_FILES = [
    "zotero_server.py",
    "config.py",
    "local_discovery.py",
    "config.local.json",
    "viewer/index.html",
    "viewer/app.js",
]


def main() -> None:
    parser = argparse.ArgumentParser(description="PaperCatch")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--no-reload", action="store_true", help="disable automatic server reload")
    parser.add_argument("--doctor", action="store_true", help="check local configuration and exit")
    parser.add_argument("--setup", action="store_true", help="interactive setup for Zotero, Hermes, and email")
    parser.add_argument("--yes", action="store_true", help="accept discovered setup defaults without prompts")
    parser.add_argument("--discover", action="store_true", help="find local Zotero and Hermes installations")
    parser.add_argument("--bootstrap", action="store_true", help="auto-configure discovered defaults and Hermes autostart")
    parser.add_argument("--install-hermes-autostart", action="store_true", help="start PaperCatch on each Hermes session")
    args = parser.parse_args()

    if sys.version_info < (3, 8):
        print("ERROR: Python 3.8+ required")
        sys.exit(1)

    ensure_frontend()

    if args.setup:
        run_setup(auto_accept=args.yes)
        return

    if args.discover:
        print_discovery()
        return

    if args.bootstrap:
        bootstrap(args.port)
        return

    if args.install_hermes_autostart:
        result = install_autostart(args.port)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    if args.doctor:
        doctor()
        return

    doctor(short=True)
    run_server(args.port, args.no_browser, reload_enabled=not args.no_reload)


def ensure_frontend() -> None:
    viewer_dir = BASE_DIR / "viewer"
    viewer_dir.mkdir(exist_ok=True)
    index_html = viewer_dir / "index.html"
    if not index_html.exists():
        index_html.write_text(
            "<!DOCTYPE html><html><head><meta charset='utf-8'>"
            "<title>PaperCatch</title></head>"
            "<body style='font-family:sans-serif;max-width:680px;margin:56px auto'>"
            "<h1>PaperCatch</h1><p>Frontend is not ready yet.</p>"
            "<p>API: <a href='/api/papers'>/api/papers</a></p></body></html>",
            encoding="utf-8",
        )


def doctor(short: bool = False) -> None:
    status = public_status()
    db_file = BASE_DIR / "papers_database.json"
    total = 0
    if db_file.exists():
        try:
            with open(db_file, "r", encoding="utf-8") as f:
                total = int(json.load(f).get("total_count", 0))
        except Exception:
            total = -1

    print("PaperCatch check")
    print(f"  Project: {BASE_DIR}")
    print(f"  Config:  {'found' if status['config_file_exists'] else 'not found'} ({status['config_file']})")
    print(f"  Papers:  {total if total >= 0 else 'unreadable'}")
    print(f"  Zotero:  {'ready' if status['zotero']['configured'] else 'not configured'}")
    print(f"           local {'found' if status['zotero']['local_found'] else 'not found'}")
    print(f"  Hermes:  {status['hermes']['mode']}")
    print(f"           local {'found' if status['hermes']['local_found'] else 'not found'}")
    email_state = "ready" if status["email"]["enabled"] and status["email"]["configured"] else "off"
    print(f"  Email:   {email_state}")

    if not short:
        print()
        if not status["zotero"]["configured"]:
            print("Zotero setup: run python start.py --setup, or set ZOTERO_API_KEY and ZOTERO_USER_ID.")
            if status["zotero"]["local_found"]:
                print(f"Local Zotero found: {status['zotero']['local_data_dir'] or status['zotero']['local_executable']}")
        if status["hermes"]["mode"] == "builtin":
            print("Hermes mode: using built-in parser. Configure HERMES_API_URL or HERMES_COMMAND for a real LLM parser.")
            if status["hermes"]["local_found"]:
                print(f"Local Hermes found: {status['hermes']['home_dir'] or status['hermes']['command']}")
        if not status["email"]["configured"]:
            print("Email setup: run python start.py --setup and fill SMTP settings if you want daily digests.")
        print("Start app: python start.py")


def run_setup(auto_accept: bool = False) -> None:
    config = load_config()
    discovery = discover_local_tools()

    apply_discovery_defaults(config, discovery)
    if auto_accept:
        save_config(config)
        print_discovery_summary(discovery)
        print()
        print(f"Saved discovered defaults: {CONFIG_FILE}")
        doctor(short=True)
        return

    print("PaperCatch setup")
    print("Press Enter to keep the current value. Secrets are stored only in config.local.json.")
    print()
    print_discovery_summary(discovery)
    print()

    config["zotero"]["api_key"] = prompt("Zotero API key", config["zotero"].get("api_key", ""), secret=True)
    config["zotero"]["user_id"] = prompt("Zotero user ID", config["zotero"].get("user_id", ""))
    config["zotero"]["default_collection"] = prompt(
        "Default Zotero collection",
        config["zotero"].get("default_collection", "PaperCatch/Hermes Search"),
    )
    config["zotero"]["local_executable"] = prompt("Zotero executable", config["zotero"].get("local_executable", ""))
    config["zotero"]["local_data_dir"] = prompt("Zotero data dir", config["zotero"].get("local_data_dir", ""))
    config["zotero"]["local_profile_dir"] = prompt("Zotero profile dir", config["zotero"].get("local_profile_dir", ""))

    print()
    print("Hermes / LLM parser")
    config["hermes"]["api_url"] = prompt("Hermes API URL", config["hermes"].get("api_url", ""))
    config["hermes"]["command"] = prompt("Hermes command", config["hermes"].get("command", ""))
    config["hermes"]["model"] = prompt("Hermes model label", config["hermes"].get("model", ""))
    config["hermes"]["home_dir"] = prompt("Hermes home dir", config["hermes"].get("home_dir", ""))

    print()
    print("Email digest")
    enable_email = prompt("Enable email digest? (y/n)", "y" if config["email"].get("enabled") else "n")
    config["email"]["enabled"] = enable_email.strip().lower() in {"y", "yes", "1", "true", "on"}
    config["email"]["smtp_host"] = prompt("SMTP host", config["email"].get("smtp_host", ""))
    config["email"]["smtp_port"] = int(prompt("SMTP port", str(config["email"].get("smtp_port", 587))) or 587)
    config["email"]["smtp_user"] = prompt("SMTP user", config["email"].get("smtp_user", ""))
    config["email"]["smtp_password"] = prompt("SMTP password/app password", config["email"].get("smtp_password", ""), secret=True)
    config["email"]["smtp_from"] = prompt("Sender email", config["email"].get("smtp_from", ""))
    config["email"]["smtp_to"] = prompt("Recipient email(s)", config["email"].get("smtp_to", ""))
    tls = prompt("Use TLS? (y/n)", "y" if config["email"].get("use_tls", True) else "n")
    config["email"]["use_tls"] = tls.strip().lower() in {"y", "yes", "1", "true", "on"}

    save_config(config)
    print()
    print(f"Saved: {CONFIG_FILE}")
    doctor(short=True)


def bootstrap(port: int) -> None:
    print("PaperCatch bootstrap")
    run_setup(auto_accept=True)
    print()
    print("Installing Hermes autostart hook...")
    result = install_autostart(port)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print()
    print("Done. Next Hermes session will ensure PaperCatch is running.")
    print("Manual start is still available: python start.py")


def apply_discovery_defaults(config: dict, discovery: dict) -> None:
    zotero = discovery.get("zotero", {})
    hermes = discovery.get("hermes", {})

    if not config["zotero"].get("user_id") and zotero.get("user_id"):
        config["zotero"]["user_id"] = zotero["user_id"]
    if not config["zotero"].get("local_executable") and zotero.get("executable"):
        config["zotero"]["local_executable"] = zotero["executable"]
    if not config["zotero"].get("local_data_dir") and zotero.get("data_dirs"):
        config["zotero"]["local_data_dir"] = zotero["data_dirs"][0]
    if not config["zotero"].get("local_profile_dir") and zotero.get("profile_dirs"):
        config["zotero"]["local_profile_dir"] = zotero["profile_dirs"][0]

    if not config["hermes"].get("command") and hermes.get("suggested_command"):
        config["hermes"]["command"] = hermes["suggested_command"]
    if not config["hermes"].get("home_dir") and hermes.get("home_dirs"):
        config["hermes"]["home_dir"] = hermes["home_dirs"][0]


def print_discovery() -> None:
    print(json.dumps(discover_local_tools(), ensure_ascii=False, indent=2))


def print_discovery_summary(discovery: dict) -> None:
    zotero = discovery.get("zotero", {})
    hermes = discovery.get("hermes", {})
    print("Local discovery")
    if zotero.get("found"):
        print(f"  Zotero: found")
        if zotero.get("executable"):
            print(f"    executable: {zotero['executable']}")
        if zotero.get("data_dirs"):
            print(f"    data dir:   {zotero['data_dirs'][0]}")
        if zotero.get("user_id"):
            print(f"    user id:    {zotero['user_id']}")
        connector = zotero.get("connector", {})
        print(f"    connector:  {'running' if connector.get('running') else 'not running'}")
    else:
        print("  Zotero: not found")

    if hermes.get("found"):
        print("  Hermes: found")
        if hermes.get("executable"):
            print(f"    command:    {hermes['executable']}")
        if hermes.get("home_dirs"):
            print(f"    home:       {hermes['home_dirs'][0]}")
    else:
        print("  Hermes: not found")


def prompt(label: str, current: str, secret: bool = False) -> str:
    shown = "***" if secret and current else current
    suffix = f" [{shown}]" if shown else ""
    value = input(f"{label}{suffix}: ").strip()
    return current if value == "" else value


def run_server(port: int, no_browser: bool, reload_enabled: bool) -> None:
    url = f"http://localhost:{port}"
    proc = None
    opened = False
    mtimes = read_watched_mtimes()

    print()
    print("=" * 52)
    print("  PaperCatch is running")
    print(f"  Frontend: {url}")
    print(f"  API:      {url}/api/papers")
    print(f"  Health:   {url}/health")
    print(f"  Reload:   {'on' if reload_enabled else 'off'}")
    print("  Press Ctrl+C to stop")
    print("=" * 52)
    print()

    try:
        while True:
            if proc is None or proc.poll() is not None:
                proc = start_child(port)
                time.sleep(1.2)
                if proc.poll() is not None:
                    raise RuntimeError("Server failed to start")
                if not no_browser and not opened:
                    webbrowser.open(url)
                    opened = True

            time.sleep(1)
            if reload_enabled:
                next_mtimes = read_watched_mtimes()
                if next_mtimes != mtimes:
                    print("Change detected. Restarting backend...")
                    stop_child(proc)
                    proc = start_child(port)
                    mtimes = next_mtimes
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        if proc is not None:
            stop_child(proc)
        print("Goodbye!")


def start_child(port: int) -> subprocess.Popen:
    server_script = str(BASE_DIR / "zotero_server.py")
    return subprocess.Popen([sys.executable, server_script, "--port", str(port)], cwd=str(BASE_DIR))


def stop_child(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=8)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def read_watched_mtimes() -> dict[str, float | None]:
    mtimes: dict[str, float | None] = {}
    for rel in WATCHED_FILES:
        path = BASE_DIR / rel
        mtimes[rel] = path.stat().st_mtime if path.exists() else None
    return mtimes


if __name__ == "__main__":
    main()
