#!/usr/bin/env python3
"""Shared local configuration helpers for PaperCatch."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent
CONFIG_FILE = BASE_DIR / "config.local.json"

DEFAULT_CONFIG: dict[str, Any] = {
    "zotero": {
        "api_key": "",
        "user_id": "",
        "default_collection": "PaperCatch/Hermes Search",
        "local_executable": "",
        "local_data_dir": "",
        "local_profile_dir": "",
    },
    "hermes": {
        "api_url": "",
        "command": "",
        "model": "",
        "home_dir": "",
    },
    "email": {
        "enabled": False,
        "smtp_host": "",
        "smtp_port": 587,
        "smtp_user": "",
        "smtp_password": "",
        "smtp_from": "",
        "smtp_to": "",
        "use_tls": True,
    },
}


ENV_MAP = {
    ("zotero", "api_key"): "ZOTERO_API_KEY",
    ("zotero", "user_id"): "ZOTERO_USER_ID",
    ("zotero", "default_collection"): "ZOTERO_DEFAULT_COLLECTION",
    ("zotero", "local_executable"): "ZOTERO_EXECUTABLE",
    ("zotero", "local_data_dir"): "ZOTERO_DATA_DIR",
    ("zotero", "local_profile_dir"): "ZOTERO_PROFILE_DIR",
    ("hermes", "api_url"): "HERMES_API_URL",
    ("hermes", "command"): "HERMES_COMMAND",
    ("hermes", "model"): "HERMES_MODEL",
    ("hermes", "home_dir"): "HERMES_HOME",
    ("email", "enabled"): "PAPERCATCH_EMAIL_ENABLED",
    ("email", "smtp_host"): "SMTP_HOST",
    ("email", "smtp_port"): "SMTP_PORT",
    ("email", "smtp_user"): "SMTP_USER",
    ("email", "smtp_password"): "SMTP_PASSWORD",
    ("email", "smtp_from"): "SMTP_FROM",
    ("email", "smtp_to"): "SMTP_TO",
    ("email", "use_tls"): "SMTP_TLS",
}


def load_config() -> dict[str, Any]:
    config = json.loads(json.dumps(DEFAULT_CONFIG))
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            file_config = json.load(f)
        deep_update(config, file_config)

    for (section, key), env_name in ENV_MAP.items():
        if env_name in os.environ and os.environ[env_name] != "":
            current = DEFAULT_CONFIG.get(section, {}).get(key)
            config.setdefault(section, {})[key] = coerce_value(os.environ[env_name], current)

    return config


def save_config(config: dict[str, Any]) -> None:
    merged = json.loads(json.dumps(DEFAULT_CONFIG))
    deep_update(merged, config)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)
        f.write("\n")


def deep_update(target: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    for key, value in (source or {}).items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            deep_update(target[key], value)
        else:
            target[key] = value
    return target


def coerce_value(value: str, default: Any) -> Any:
    if isinstance(default, bool):
        return value.strip().lower() in {"1", "true", "yes", "on", "y"}
    if isinstance(default, int):
        try:
            return int(value)
        except ValueError:
            return default
    return value


def public_status() -> dict[str, Any]:
    config = load_config()
    try:
        from local_discovery import discover_local_tools
        local = discover_local_tools()
    except Exception as exc:
        local = {"error": str(exc), "zotero": {}, "hermes": {}}
    email = config["email"]
    hermes = config["hermes"]
    zotero = config["zotero"]
    return {
        "config_file": str(CONFIG_FILE),
        "config_file_exists": CONFIG_FILE.exists(),
        "zotero": {
            "configured": bool(zotero.get("api_key") and zotero.get("user_id")),
            "default_collection": zotero.get("default_collection") or "PaperCatch/Hermes Search",
            "local_executable": zotero.get("local_executable") or local.get("zotero", {}).get("executable", ""),
            "local_data_dir": zotero.get("local_data_dir") or first_item(local.get("zotero", {}).get("data_dirs", [])),
            "local_connector_running": bool(local.get("zotero", {}).get("connector", {}).get("running")),
            "local_found": bool(local.get("zotero", {}).get("found")),
        },
        "email": {
            "enabled": bool(email.get("enabled")),
            "configured": bool(email.get("smtp_host") and email.get("smtp_to")),
            "smtp_host": email.get("smtp_host") or "",
            "smtp_to": email.get("smtp_to") or "",
        },
        "hermes": {
            "mode": "api" if hermes.get("api_url") else "command" if hermes.get("command") else "builtin",
            "configured": bool(hermes.get("api_url") or hermes.get("command")),
            "api_url": hermes.get("api_url") or "",
            "command": hermes.get("command") or "",
            "model": hermes.get("model") or "",
            "home_dir": hermes.get("home_dir") or first_item(local.get("hermes", {}).get("home_dirs", [])),
            "local_found": bool(local.get("hermes", {}).get("found")),
        },
    }


def first_item(values: list[Any]) -> str:
    return str(values[0]) if values else ""
