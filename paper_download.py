from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from json_store import locked_update_json


PDF_DIR_NAME = "PDFs"
MANIFEST_NAME = "manifest.json"
PDF_MAGIC = b"%PDF-"
ALLOWED_CONTENT_TYPES = {
    "application/pdf",
    "application/octet-stream",
    "binary/octet-stream",
}
TERMINAL_HTTP_STATUSES = {401, 403, 404}
RETRYABLE_HTTP_STATUSES = {500, 502, 503, 504}


def download_open_access_pdf(
    paper: dict[str, Any],
    data_root: str | os.PathLike[str],
    *,
    opener: Callable[..., Any] | None = None,
    timeout: int = 20,
    max_retries: int = 2,
) -> dict[str, Any]:
    pdf_root = Path(data_root).expanduser().resolve() / PDF_DIR_NAME
    pdf_root.mkdir(parents=True, exist_ok=True)
    manifest_path = pdf_root / MANIFEST_NAME
    manifest = _read_manifest(manifest_path)
    aliases = _paper_aliases(paper)
    timestamp = datetime.now(timezone.utc).isoformat()

    base_result = {
        "paper_id": str(paper.get("paper_id") or ""),
        "doi": _normalize_doi(paper.get("doi")),
        "arxiv_id": _normalize_arxiv_id(paper.get("arxiv_id")),
        "pdf_url": str(paper.get("pdf_url") or "").strip(),
        "open_access": bool(paper.get("open_access")),
        "aliases": aliases,
        "attempts": 0,
        "downloaded_at": timestamp,
    }

    if not base_result["open_access"] or not base_result["pdf_url"]:
        result = {
            **base_result,
            "status": "no_authorized_pdf_found",
            "reason": "open_access_false_or_missing_pdf_url",
            "file_path": "",
            "size_bytes": 0,
        }
        _append_manifest(manifest, manifest_path, result)
        return result

    existing_path = _find_existing_pdf(pdf_root, manifest.get("entries", []), aliases)
    if existing_path is not None:
        result = {
            **base_result,
            "status": "already_exists",
            "reason": "existing_valid_pdf",
            "file_path": str(existing_path),
            "size_bytes": existing_path.stat().st_size,
        }
        _append_manifest(manifest, manifest_path, result)
        return result

    file_stem = _safe_filename(_preferred_identifier(paper))
    target_path = pdf_root / f"{file_stem}.pdf"
    part_path = pdf_root / f"{file_stem}.pdf.part"
    open_url = opener or urllib.request.urlopen

    last_error = ""
    attempts = max(1, int(max_retries) + 1)
    for attempt in range(1, attempts + 1):
        try:
            _cleanup_file(part_path)
            request = urllib.request.Request(
                base_result["pdf_url"],
                headers={
                    "Accept": "application/pdf,application/octet-stream;q=0.9,*/*;q=0.1",
                    "User-Agent": "PaperCatch/2.0",
                },
            )
            with open_url(request, timeout=timeout) as response:
                status_code = _response_status(response)
                if status_code in TERMINAL_HTTP_STATUSES:
                    result = {
                        **base_result,
                        "status": "no_authorized_pdf_found",
                        "reason": f"http_{status_code}",
                        "http_status": status_code,
                        "attempts": attempt,
                        "file_path": "",
                        "size_bytes": 0,
                    }
                    _append_manifest(manifest, manifest_path, result)
                    return result
                if status_code in RETRYABLE_HTTP_STATUSES:
                    raise _RetryableDownloadError(f"http_{status_code}", status_code)
                if status_code >= 400:
                    result = {
                        **base_result,
                        "status": "invalid_pdf",
                        "reason": f"http_{status_code}",
                        "http_status": status_code,
                        "attempts": attempt,
                        "file_path": "",
                        "size_bytes": 0,
                    }
                    _append_manifest(manifest, manifest_path, result)
                    return result

                content_type = _content_type(response)
                size_bytes = _write_response_to_part(response, part_path)
                validation = _validate_download(part_path, content_type, size_bytes)
                if validation is not None:
                    result = {
                        **base_result,
                        "status": "invalid_pdf",
                        "reason": validation,
                        "content_type": content_type,
                        "attempts": attempt,
                        "file_path": "",
                        "size_bytes": size_bytes,
                    }
                    _cleanup_file(part_path)
                    _append_manifest(manifest, manifest_path, result)
                    return result

                os.replace(part_path, target_path)
                result = {
                    **base_result,
                    "status": "downloaded",
                    "reason": "ok",
                    "content_type": content_type,
                    "attempts": attempt,
                    "file_path": str(target_path),
                    "size_bytes": target_path.stat().st_size,
                }
                _append_manifest(manifest, manifest_path, result)
                return result
        except urllib.error.HTTPError as exc:
            if exc.code in TERMINAL_HTTP_STATUSES:
                result = {
                    **base_result,
                    "status": "no_authorized_pdf_found",
                    "reason": f"http_{exc.code}",
                    "http_status": exc.code,
                    "attempts": attempt,
                    "file_path": "",
                    "size_bytes": 0,
                }
                _cleanup_file(part_path)
                _append_manifest(manifest, manifest_path, result)
                return result
            if exc.code in RETRYABLE_HTTP_STATUSES:
                last_error = f"http_{exc.code}"
            else:
                result = {
                    **base_result,
                    "status": "invalid_pdf",
                    "reason": f"http_{exc.code}",
                    "http_status": exc.code,
                    "attempts": attempt,
                    "file_path": "",
                    "size_bytes": 0,
                }
                _cleanup_file(part_path)
                _append_manifest(manifest, manifest_path, result)
                return result
        except _RetryableDownloadError as exc:
            last_error = str(exc)
        except (TimeoutError, socket.timeout, urllib.error.URLError) as exc:
            if _is_terminal_url_error(exc):
                result = {
                    **base_result,
                    "status": "no_authorized_pdf_found",
                    "reason": _url_error_reason(exc),
                    "attempts": attempt,
                    "file_path": "",
                    "size_bytes": 0,
                }
                _cleanup_file(part_path)
                _append_manifest(manifest, manifest_path, result)
                return result
            last_error = str(exc)
        finally:
            _cleanup_file(part_path)

    result = {
        **base_result,
        "status": "failed_after_retry",
        "reason": last_error or "retry_limit_exceeded",
        "attempts": attempts,
        "file_path": "",
        "size_bytes": 0,
    }
    _append_manifest(manifest, manifest_path, result)
    return result


class _RetryableDownloadError(RuntimeError):
    pass


def _response_status(response: Any) -> int:
    if hasattr(response, "status"):
        return int(response.status)
    if hasattr(response, "getcode"):
        return int(response.getcode())
    return 200


def _content_type(response: Any) -> str:
    headers = getattr(response, "headers", None)
    if headers is None:
        return ""
    if hasattr(headers, "get_content_type"):
        return str(headers.get_content_type() or "").lower()
    value = headers.get("Content-Type", "")
    return str(value).split(";", 1)[0].strip().lower()


def _write_response_to_part(response: Any, part_path: Path) -> int:
    size_bytes = 0
    with part_path.open("wb") as handle:
        while True:
            chunk = response.read(64 * 1024)
            if not chunk:
                break
            handle.write(chunk)
            size_bytes += len(chunk)
    return size_bytes


def _validate_download(path: Path, content_type: str, size_bytes: int) -> str | None:
    if size_bytes <= 0:
        return "empty_body"
    with path.open("rb") as handle:
        prefix = handle.read(len(PDF_MAGIC))
    if prefix != PDF_MAGIC:
        if content_type == "text/html":
            return "html_response"
        return "missing_pdf_magic"
    if content_type and content_type not in ALLOWED_CONTENT_TYPES:
        return f"unexpected_content_type:{content_type}"
    return None


def _find_existing_pdf(pdf_root: Path, entries: list[dict[str, Any]], aliases: list[str]) -> Path | None:
    alias_set = set(aliases)
    for entry in reversed(entries):
        if entry.get("status") not in {"downloaded", "already_exists"}:
            continue
        entry_aliases = {str(item).strip() for item in entry.get("aliases", []) if str(item).strip()}
        if not alias_set.intersection(entry_aliases):
            continue
        candidate = _manifest_file_path(pdf_root, entry.get("file_path"))
        if candidate is not None and candidate.is_file() and _is_valid_existing_pdf(candidate):
            return candidate

    for alias in aliases:
        candidate = pdf_root / f"{_safe_filename(alias)}.pdf"
        if candidate.is_file() and _is_valid_existing_pdf(candidate):
            return candidate
    return None


def _manifest_file_path(pdf_root: Path, file_path: Any) -> Path | None:
    if not file_path:
        return None
    try:
        candidate = Path(str(file_path)).expanduser().resolve(strict=True)
        candidate.relative_to(pdf_root.resolve())
    except (OSError, RuntimeError, ValueError):
        return None
    return candidate


def _is_valid_existing_pdf(path: Path) -> bool:
    try:
        if path.stat().st_size <= 0:
            return False
        with path.open("rb") as handle:
            return handle.read(len(PDF_MAGIC)) == PDF_MAGIC
    except OSError:
        return False


def _preferred_identifier(paper: dict[str, Any]) -> str:
    for candidate in (
        str(paper.get("paper_id") or "").strip(),
        _normalize_doi(paper.get("doi")),
        _normalize_arxiv_id(paper.get("arxiv_id")),
    ):
        if candidate:
            return candidate
    title = re.sub(r"\s+", " ", str(paper.get("title") or "").strip())
    if title:
        digest = hashlib.sha1(title.casefold().encode("utf-8")).hexdigest()[:16]
        return f"title:{digest}"
    return "paper"


def _paper_aliases(paper: dict[str, Any]) -> list[str]:
    values = [
        str(paper.get("paper_id") or "").strip(),
        _normalize_doi(paper.get("doi")),
        _normalize_arxiv_id(paper.get("arxiv_id")),
    ]
    aliases: list[str] = []
    for value in values:
        if value and value not in aliases:
            aliases.append(value)
    if not aliases:
        aliases.append(_preferred_identifier(paper))
    return aliases


def _normalize_doi(value: Any) -> str:
    text = str(value or "").strip()
    text = re.sub(r"^https?://doi\.org/", "", text, flags=re.I)
    return text.rstrip(" .").lower()


def _normalize_arxiv_id(value: Any) -> str:
    text = str(value or "").strip()
    if text.startswith(("doi:", "pmid:", "openalex:", "title:")):
        return ""
    if text.startswith("arxiv:"):
        text = text.split(":", 1)[1]
    return text.split("v", 1)[0]


def _safe_filename(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    safe = safe.strip("._")
    return safe[:120] or "paper"


def _read_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"entries": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"entries": []}
    if not isinstance(data, dict):
        return {"entries": []}
    entries = data.get("entries")
    if not isinstance(entries, list):
        return {"entries": []}
    return {"entries": entries}


def _append_manifest(manifest: dict[str, Any], path: Path, entry: dict[str, Any]) -> None:
    def update(current: dict[str, Any]) -> dict[str, Any]:
        entries = current.get("entries")
        if not isinstance(entries, list):
            entries = []
        entries = list(entries)
        entries.append(entry)
        return {"entries": entries}

    locked_update_json(path, {"entries": []}, update)


def _cleanup_file(path: Path) -> None:
    try:
        if path.exists():
            path.unlink()
    except OSError:
        pass


def _is_terminal_url_error(exc: urllib.error.URLError) -> bool:
    reason = getattr(exc, "reason", None)
    return isinstance(reason, PermissionError)


def _url_error_reason(exc: urllib.error.URLError) -> str:
    reason = getattr(exc, "reason", None)
    if isinstance(reason, PermissionError):
        return "permission_denied"
    return str(exc)
