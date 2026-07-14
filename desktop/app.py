"""PaperCatch desktop application entry point."""

from __future__ import annotations

import os
import sys
from pathlib import Path


if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from desktop.runtime import (
    BackendService,
    DesktopDependencyError,
    report_startup_failure,
    require_webview,
)


def run_desktop(webview_module) -> None:
    backend = BackendService()
    try:
        url = backend.start()
        window = webview_module.create_window(
            "纸上得来 · PaperCatch",
            url=url,
            width=1280,
            height=820,
            min_size=(900, 600),
            background_color="#faf8f3",
        )
        window.events.closed += backend.stop
        webview_module.start(debug=os.environ.get("PAPERCATCH_DESKTOP_DEBUG") == "1")
    finally:
        backend.stop()


def main() -> int:
    try:
        webview_module = require_webview()
        run_desktop(webview_module)
    except DesktopDependencyError as exc:
        report_startup_failure("PaperCatch desktop error", exc)
        return 2
    except Exception as exc:
        report_startup_failure("PaperCatch desktop failed", exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
