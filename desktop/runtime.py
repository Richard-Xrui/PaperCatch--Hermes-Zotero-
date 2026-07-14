"""Runtime helpers shared by the source launcher and packaged desktop app."""

from __future__ import annotations

import importlib
import ipaddress
import os
import shutil
import sys
import threading
import traceback
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, MutableMapping, Protocol, TextIO


APP_NAME = "PaperCatch"
LOOPBACK_HOSTS = frozenset({"localhost"})
SEED_FILES = ("papercatch_categories.json", "search_config.json")


class DesktopRuntimeError(RuntimeError):
    """Raised when the desktop runtime cannot start safely."""


class DesktopDependencyError(DesktopRuntimeError):
    """Raised when an optional desktop dependency is unavailable."""


class ServerProtocol(Protocol):
    server_address: tuple[str, int]

    def serve_forever(self) -> None: ...

    def shutdown(self) -> None: ...

    def server_close(self) -> None: ...


ServerFactory = Callable[[int], ServerProtocol]
ErrorDialog = Callable[[str, str], None]


@dataclass(frozen=True)
class DesktopPaths:
    """Read-only application resources and writable desktop data paths."""

    resource_root: Path
    data_root: Path

    @property
    def viewer_dir(self) -> Path:
        return self.resource_root / "viewer"

    @property
    def viewer_state_dir(self) -> Path:
        if self.data_root == self.resource_root:
            return self.resource_root / "viewer"
        return self.data_root / "viewer-state"


def _desktop_data_root(
    local_app_data: str | os.PathLike[str] | None = None,
) -> Path:
    raw_local_root = local_app_data or os.environ.get("LOCALAPPDATA")
    if not raw_local_root:
        raw_local_root = Path.home() / "AppData" / "Local"
    return (Path(raw_local_root).expanduser() / APP_NAME).resolve()


def resolve_desktop_paths(
    *,
    frozen: bool | None = None,
    bundle_root: str | os.PathLike[str] | None = None,
    local_app_data: str | os.PathLike[str] | None = None,
    project_root: str | os.PathLike[str] | None = None,
) -> DesktopPaths:
    """Resolve source-mode or packaged paths without changing the filesystem."""

    if frozen is None:
        frozen = bool(getattr(sys, "frozen", False))

    source_root = Path(project_root or Path(__file__).resolve().parents[1]).resolve()
    if not frozen:
        return DesktopPaths(resource_root=source_root, data_root=source_root)

    raw_bundle_root = bundle_root or getattr(sys, "_MEIPASS", None)
    if not raw_bundle_root:
        raise DesktopRuntimeError("Packaged runtime is missing its bundle directory.")

    return DesktopPaths(
        resource_root=Path(raw_bundle_root).resolve(),
        data_root=_desktop_data_root(local_app_data),
    )


def desktop_log_path(
    local_app_data: str | os.PathLike[str] | None = None,
) -> Path:
    """Return the writable startup log used by the packaged application."""

    return _desktop_data_root(local_app_data) / "logs" / "desktop.log"


def show_windows_error_dialog(title: str, message: str) -> None:
    """Display a native error dialog without importing GUI modules at startup."""

    import ctypes

    ctypes.windll.user32.MessageBoxW(None, message, title, 0x10)


def report_startup_failure(
    prefix: str,
    error: BaseException,
    *,
    frozen: bool | None = None,
    local_app_data: str | os.PathLike[str] | None = None,
    platform: str | None = None,
    stderr: TextIO | None = None,
    message_box: ErrorDialog | None = None,
) -> Path | None:
    """Report source failures to stderr and packaged failures to disk and GUI."""

    if frozen is None:
        frozen = bool(getattr(sys, "frozen", False))
    message = f"{prefix}: {error}"
    if not frozen:
        output = sys.stderr if stderr is None else stderr
        if output is not None:
            print(message, file=output)
        return None

    log_path = desktop_log_path(local_app_data)
    log_note = f"Log: {log_path}"
    details = "".join(
        traceback.format_exception(type(error), error, error.__traceback__)
    ).rstrip()
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as log_file:
            timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
            log_file.write(f"[{timestamp}] {message}\n{details}\n\n")
    except OSError as log_error:
        log_note = f"Log could not be written at {log_path}: {log_error}"

    if (platform or sys.platform) == "win32":
        dialog = message_box or show_windows_error_dialog
        try:
            dialog("PaperCatch startup error", f"{message}\n\n{log_note}")
        except Exception:
            pass
    return log_path


def seed_desktop_data(paths: DesktopPaths) -> None:
    """Create writable directories and copy defaults only when absent."""

    paths.data_root.mkdir(parents=True, exist_ok=True)
    paths.viewer_state_dir.mkdir(parents=True, exist_ok=True)
    for filename in SEED_FILES:
        source = paths.resource_root / filename
        destination = paths.data_root / filename
        if source.is_file() and not destination.exists():
            shutil.copy2(source, destination)


def prepare_desktop_environment(
    paths: DesktopPaths,
    environ: MutableMapping[str, str] | None = None,
) -> None:
    """Prepare data and configure backend paths before importing it."""

    seed_desktop_data(paths)
    target = os.environ if environ is None else environ
    target["PAPERCATCH_RESOURCE_DIR"] = str(paths.resource_root)
    target["PAPERCATCH_DATA_DIR"] = str(paths.data_root)
    target["PAPERCATCH_VIEWER_STATE_DIR"] = str(paths.viewer_state_dir)


def create_papercatch_server(port: int) -> ServerProtocol:
    """Create the existing PaperCatch backend after desktop path setup."""

    paths = resolve_desktop_paths()
    prepare_desktop_environment(paths)
    if str(paths.resource_root) not in sys.path:
        sys.path.insert(0, str(paths.resource_root))

    from zotero_server import create_server

    return create_server(port)


def require_webview(import_module: Callable[[str], object] = importlib.import_module):
    """Import pywebview lazily so web-only installs remain dependency-free."""

    try:
        return import_module("webview")
    except ModuleNotFoundError as exc:
        if exc.name != "webview":
            raise
        raise DesktopDependencyError(
            "pywebview is required for the desktop app. Install it with: "
            "python -m pip install -r desktop/requirements.txt"
        ) from exc


def _is_loopback(host: str) -> bool:
    normalized = host.rstrip(".").lower()
    if normalized in LOOPBACK_HOSTS:
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


class BackendService:
    """Own one in-process PaperCatch HTTP server and its worker thread."""

    def __init__(self, server_factory: ServerFactory = create_papercatch_server):
        self._server_factory = server_factory
        self._server: ServerProtocol | None = None
        self._thread: threading.Thread | None = None
        self._url: str | None = None
        self._lock = threading.RLock()

    @staticmethod
    def _dispose_server(
        server: ServerProtocol | None,
        thread: threading.Thread | None,
        *,
        request_shutdown: bool,
    ) -> None:
        if server is None:
            return
        try:
            if request_shutdown:
                server.shutdown()
        finally:
            if thread is not None and thread is not threading.current_thread():
                thread.join(timeout=5)
            server.server_close()

    @property
    def running(self) -> bool:
        with self._lock:
            return bool(self._server and self._thread and self._thread.is_alive())

    def start(self) -> str:
        """Bind a system-assigned loopback port and start serving."""

        stale_server: ServerProtocol | None = None
        stale_thread: threading.Thread | None = None
        with self._lock:
            if self._server is not None:
                if (
                    self._thread is not None
                    and self._thread.is_alive()
                    and self._url is not None
                ):
                    return self._url
                stale_server = self._server
                stale_thread = self._thread
                self._server = None
                self._thread = None
                self._url = None

        if stale_server is not None:
            self._dispose_server(
                stale_server,
                stale_thread,
                request_shutdown=bool(stale_thread and stale_thread.is_alive()),
            )

        with self._lock:
            if (
                self._server is not None
                and self._thread is not None
                and self._thread.is_alive()
                and self._url is not None
            ):
                return self._url

            server = self._server_factory(0)
            host, port = server.server_address[:2]
            host = str(host)
            if not _is_loopback(host):
                server.server_close()
                raise DesktopRuntimeError(
                    f"Desktop backend must bind to loopback, got {host!r}."
                )

            display_host = f"[{host}]" if ":" in host else host
            thread = threading.Thread(
                target=server.serve_forever,
                name="PaperCatchDesktopServer",
                daemon=True,
            )
            self._server = server
            self._thread = thread
            self._url = f"http://{display_host}:{int(port)}"
            thread.start()
            return self._url

    def stop(self, *_event_args) -> None:
        """Stop and close the backend. Repeated calls are harmless."""

        with self._lock:
            server = self._server
            thread = self._thread
            self._server = None
            self._thread = None
            self._url = None

        self._dispose_server(server, thread, request_shutdown=server is not None)


__all__ = [
    "BackendService",
    "DesktopDependencyError",
    "DesktopPaths",
    "DesktopRuntimeError",
    "create_papercatch_server",
    "desktop_log_path",
    "prepare_desktop_environment",
    "report_startup_failure",
    "require_webview",
    "resolve_desktop_paths",
    "seed_desktop_data",
    "show_windows_error_dialog",
]
