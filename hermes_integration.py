#!/usr/bin/env python3
"""Install PaperCatch integration into Hermes."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

from local_discovery import discover_local_tools


BASE_DIR = Path(__file__).resolve().parent
HOOK_SCRIPT = BASE_DIR / "papercatch_autostart.py"
DEFAULT_PORT = 8765


def main() -> None:
    parser = argparse.ArgumentParser(description="PaperCatch Hermes integration")
    parser.add_argument("--install-autostart", action="store_true")
    parser.add_argument("--remove-autostart", action="store_true")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()

    if args.install_autostart:
        print(json.dumps(install_autostart(args.port), ensure_ascii=False, indent=2))
        return
    if args.remove_autostart:
        print(json.dumps(remove_autostart(args.port), ensure_ascii=False, indent=2))
        return
    parser.print_help()


def install_autostart(port: int = DEFAULT_PORT) -> dict:
    hermes_home = find_hermes_home()
    hermes_home.mkdir(parents=True, exist_ok=True)
    config_path = hermes_home / "config.yaml"
    allowlist_path = hermes_home / "shell-hooks-allowlist.json"
    command = hook_command(port)

    config = load_yaml(config_path)
    hooks = config.setdefault("hooks", {})
    entries = hooks.setdefault("on_session_start", [])
    if not isinstance(entries, list):
        entries = []
        hooks["on_session_start"] = entries

    if not any(item.get("command") == command for item in entries if isinstance(item, dict)):
        entries.append({"command": command, "timeout": 10})

    backup(config_path)
    save_yaml(config_path, config)
    approve_hook(allowlist_path, "on_session_start", command)
    return {
        "success": True,
        "hermes_home": str(hermes_home),
        "config": str(config_path),
        "allowlist": str(allowlist_path),
        "event": "on_session_start",
        "command": command,
    }


def remove_autostart(port: int = DEFAULT_PORT) -> dict:
    hermes_home = find_hermes_home()
    config_path = hermes_home / "config.yaml"
    allowlist_path = hermes_home / "shell-hooks-allowlist.json"
    command = hook_command(port)

    config = load_yaml(config_path)
    hooks = config.get("hooks", {})
    removed = False
    if isinstance(hooks, dict) and isinstance(hooks.get("on_session_start"), list):
        before = len(hooks["on_session_start"])
        hooks["on_session_start"] = [
            item for item in hooks["on_session_start"]
            if not (isinstance(item, dict) and item.get("command") == command)
        ]
        removed = len(hooks["on_session_start"]) != before
        if not hooks["on_session_start"]:
            hooks.pop("on_session_start", None)
        if not hooks:
            config.pop("hooks", None)

    if removed:
        backup(config_path)
        save_yaml(config_path, config)
    remove_hook_approval(allowlist_path, "on_session_start", command)
    return {"success": True, "removed": removed, "command": command}


def hook_command(port: int) -> str:
    return f'"{sys.executable}" "{HOOK_SCRIPT}" --ensure --port {port}'


def find_hermes_home() -> Path:
    found = discover_local_tools().get("hermes", {})
    homes = found.get("home_dirs") or []
    if homes:
        return Path(homes[0])
    return Path.home() / ".hermes"


def load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        import yaml
    except ImportError:
        return load_simple_yaml(path)
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def save_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        import yaml
    except ImportError:
        save_simple_yaml(path, data)
        return
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)


def load_simple_yaml(path: Path) -> dict:
    # Minimal fallback for fresh configs. Existing complex configs should have
    # PyYAML available in normal Hermes installs.
    text = path.read_text(encoding="utf-8", errors="replace")
    if text.strip():
        raise RuntimeError("PyYAML is required to edit an existing Hermes config safely")
    return {}


def save_simple_yaml(path: Path, data: dict) -> None:
    hooks = data.get("hooks", {})
    lines = []
    if hooks:
        lines.append("hooks:")
        for event, entries in hooks.items():
            lines.append(f"  {event}:")
            for item in entries:
                lines.append(f"    - command: {json.dumps(item['command'])}")
                lines.append(f"      timeout: {int(item.get('timeout', 10))}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def approve_hook(path: Path, event: str, command: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = load_json(path, {"approvals": []})
    approvals = data.setdefault("approvals", [])
    if not any(item.get("event") == event and item.get("command") == command for item in approvals):
        approvals.append({"event": event, "command": command})
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def remove_hook_approval(path: Path, event: str, command: str) -> None:
    if not path.exists():
        return
    data = load_json(path, {"approvals": []})
    data["approvals"] = [
        item for item in data.get("approvals", [])
        if not (item.get("event") == event and item.get("command") == command)
    ]
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_json(path: Path, default: dict) -> dict:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def backup(path: Path) -> None:
    if not path.exists():
        return
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    shutil.copy2(path, path.with_suffix(path.suffix + f".bak-{stamp}"))


if __name__ == "__main__":
    main()
