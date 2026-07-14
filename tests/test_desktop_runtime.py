"""Isolated checks for the desktop shell lifecycle."""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from desktop.app import run_desktop
from desktop.runtime import (
    BackendService,
    DesktopDependencyError,
    DesktopPaths,
    DesktopRuntimeError,
    report_startup_failure,
    prepare_desktop_environment,
    require_webview,
    resolve_desktop_paths,
    seed_desktop_data,
)
from json_store import JsonStoreError


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class FakeServer:
    def __init__(self, address=("127.0.0.1", 49152)):
        self.server_address = address
        self.serve_started = threading.Event()
        self.stop_requested = threading.Event()
        self.shutdown_calls = 0
        self.close_calls = 0

    def serve_forever(self):
        self.serve_started.set()
        self.stop_requested.wait(timeout=2)

    def shutdown(self):
        self.shutdown_calls += 1
        self.stop_requested.set()

    def server_close(self):
        self.close_calls += 1


class OneShotServer(FakeServer):
    def __init__(self, address=("127.0.0.1", 49152)):
        super().__init__(address)

    def serve_forever(self):
        self.serve_started.set()
        return


class DesktopRuntimeTests(unittest.TestCase):
    def test_desktop_window_matches_the_viewer_brand_and_lifecycle(self):
        closed_handlers = []
        create_calls = []
        start_calls = []

        class ClosedEvent:
            def __iadd__(self, handler):
                closed_handlers.append(handler)
                return self

        window = SimpleNamespace(
            events=SimpleNamespace(closed=ClosedEvent())
        )
        webview = SimpleNamespace(
            create_window=lambda *args, **kwargs: (
                create_calls.append((args, kwargs)) or window
            ),
            start=lambda **kwargs: start_calls.append(kwargs),
        )
        backend = mock.Mock()
        backend.start.return_value = "http://127.0.0.1:49152"

        with mock.patch("desktop.app.BackendService", return_value=backend):
            run_desktop(webview)

        self.assertEqual(1, len(create_calls))
        args, kwargs = create_calls[0]
        self.assertEqual(("纸上得来 · PaperCatch",), args)
        self.assertEqual("http://127.0.0.1:49152", kwargs["url"])
        self.assertEqual((1280, 820), (kwargs["width"], kwargs["height"]))
        self.assertEqual((900, 600), kwargs["min_size"])
        self.assertEqual("#faf8f3", kwargs["background_color"])
        self.assertEqual([{"debug": False}], start_calls)
        self.assertEqual([backend.stop], closed_handlers)
        self.assertEqual(1, backend.stop.call_count)

    def test_desktop_stops_backend_if_webview_start_raises(self):
        class ClosedEvent:
            def __iadd__(self, _handler):
                return self

        webview = SimpleNamespace(
            create_window=lambda *args, **kwargs: SimpleNamespace(
                events=SimpleNamespace(closed=ClosedEvent())
            ),
            start=mock.Mock(side_effect=RuntimeError("webview failed")),
        )
        backend = mock.Mock()
        backend.start.return_value = "http://127.0.0.1:49152"

        with mock.patch("desktop.app.BackendService", return_value=backend):
            with self.assertRaisesRegex(RuntimeError, "webview failed"):
                run_desktop(webview)

        self.assertEqual(1, backend.start.call_count)
        self.assertEqual(1, backend.stop.call_count)

    def test_packaged_startup_failure_writes_log_and_shows_windows_dialog(self):
        dialogs = []
        with tempfile.TemporaryDirectory() as temp_dir:
            local_app_data = Path(temp_dir)
            log_path = report_startup_failure(
                "PaperCatch desktop failed",
                RuntimeError("backend could not start"),
                frozen=True,
                local_app_data=local_app_data,
                platform="win32",
                message_box=lambda title, message: dialogs.append((title, message)),
            )

            expected_path = (
                local_app_data / "PaperCatch" / "logs" / "desktop.log"
            )
            self.assertEqual(expected_path.resolve(), log_path)
            log_text = expected_path.read_text(encoding="utf-8")
            self.assertIn("PaperCatch desktop failed: backend could not start", log_text)
            self.assertIn("RuntimeError: backend could not start", log_text)

            self.assertEqual(1, len(dialogs))
            self.assertEqual("PaperCatch startup error", dialogs[0][0])
            self.assertIn("backend could not start", dialogs[0][1])
            self.assertIn(str(expected_path.resolve()), dialogs[0][1])

    def test_source_startup_failure_stays_on_stderr(self):
        stderr = io.StringIO()
        dialogs = []
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = report_startup_failure(
                "PaperCatch desktop error",
                DesktopDependencyError("install pywebview"),
                frozen=False,
                local_app_data=temp_dir,
                platform="win32",
                stderr=stderr,
                message_box=lambda title, message: dialogs.append((title, message)),
            )

            self.assertIsNone(log_path)
            self.assertEqual(
                "PaperCatch desktop error: install pywebview\n",
                stderr.getvalue(),
            )
            self.assertEqual([], dialogs)
            self.assertFalse(Path(temp_dir, "PaperCatch").exists())

    def test_backend_uses_random_loopback_port_and_stops_once(self):
        calls = []
        server = FakeServer()

        def factory(port):
            calls.append(port)
            return server

        backend = BackendService(factory)
        url = backend.start()

        self.assertEqual([0], calls)
        self.assertEqual("http://127.0.0.1:49152", url)
        self.assertTrue(server.serve_started.wait(timeout=1))
        self.assertTrue(backend.running)

        backend.stop()
        backend.stop()

        self.assertFalse(backend.running)
        self.assertEqual(1, server.shutdown_calls)
        self.assertEqual(1, server.close_calls)

    def test_backend_start_replaces_stale_server_after_worker_thread_exits(self):
        first = OneShotServer(("127.0.0.1", 49152))
        second = FakeServer(("127.0.0.1", 49153))
        servers = [first, second]
        calls = []

        def factory(port):
            calls.append(port)
            return servers.pop(0)

        backend = BackendService(factory)

        first_url = backend.start()
        self.assertTrue(first.serve_started.wait(timeout=1))
        if backend._thread is not None:
            backend._thread.join(timeout=1)
        self.assertFalse(backend.running)

        second_url = backend.start()

        self.assertEqual([0, 0], calls)
        self.assertEqual("http://127.0.0.1:49152", first_url)
        self.assertEqual("http://127.0.0.1:49153", second_url)
        self.assertEqual(1, first.close_calls)
        self.assertEqual(0, first.shutdown_calls)
        self.assertTrue(second.serve_started.wait(timeout=1))
        backend.stop()

    def test_backend_rejects_non_loopback_factory(self):
        server = FakeServer(("0.0.0.0", 49152))
        backend = BackendService(lambda _port: server)

        with self.assertRaisesRegex(DesktopRuntimeError, "loopback"):
            backend.start()

        self.assertEqual(0, server.shutdown_calls)
        self.assertEqual(1, server.close_calls)

    def test_missing_pywebview_error_contains_install_command(self):
        def missing_import(_name):
            error = ModuleNotFoundError("No module named 'webview'")
            error.name = "webview"
            raise error

        with self.assertRaises(DesktopDependencyError) as caught:
            require_webview(missing_import)

        message = str(caught.exception)
        self.assertIn("pywebview", message)
        self.assertIn("pip install -r desktop/requirements.txt", message)

    def test_internal_pywebview_import_errors_are_not_misreported(self):
        def broken_import(_name):
            error = ModuleNotFoundError("No module named 'clr_loader'")
            error.name = "clr_loader"
            raise error

        with self.assertRaises(ModuleNotFoundError):
            require_webview(broken_import)

    def test_packaged_paths_separate_bundle_assets_and_local_data(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = resolve_desktop_paths(
                frozen=True,
                bundle_root=root / "bundle",
                local_app_data=root / "local",
            )

            self.assertEqual((root / "bundle").resolve(), paths.resource_root)
            self.assertEqual((root / "local" / "PaperCatch").resolve(), paths.data_root)
            self.assertEqual(paths.resource_root / "viewer", paths.viewer_dir)
            self.assertEqual(paths.data_root / "viewer-state", paths.viewer_state_dir)

    def test_source_paths_keep_legacy_mirrors_in_existing_viewer(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir) / "project"
            paths = resolve_desktop_paths(frozen=False, project_root=project_root)
            environment = {}

            prepare_desktop_environment(paths, environment)

            self.assertEqual(project_root.resolve(), paths.data_root)
            self.assertEqual(project_root.resolve() / "viewer", paths.viewer_state_dir)
            self.assertEqual(str(project_root.resolve() / "viewer"), environment[
                "PAPERCATCH_VIEWER_STATE_DIR"
            ])
            self.assertFalse((project_root / "viewer-state").exists())

    def test_seed_copies_missing_defaults_without_overwriting_user_data(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            resource_root = root / "bundle"
            data_root = root / "local" / "PaperCatch"
            resource_root.mkdir(parents=True)
            data_root.mkdir(parents=True)
            (resource_root / "papercatch_categories.json").write_text(
                '[{"id":"default"}]', encoding="utf-8"
            )
            (resource_root / "search_config.json").write_text(
                '{"source":"bundle"}', encoding="utf-8"
            )
            (data_root / "search_config.json").write_text(
                '{"source":"user"}', encoding="utf-8"
            )
            paths = DesktopPaths(resource_root, data_root)

            seed_desktop_data(paths)

            self.assertEqual(
                '[{"id":"default"}]',
                (data_root / "papercatch_categories.json").read_text(encoding="utf-8"),
            )
            self.assertEqual(
                '{"source":"user"}',
                (data_root / "search_config.json").read_text(encoding="utf-8"),
            )
            self.assertTrue(paths.viewer_state_dir.is_dir())

    def test_backend_modules_resolve_desktop_environment_before_import(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            resource_root = root / "bundle"
            data_root = root / "local" / "PaperCatch"
            (resource_root / "viewer").mkdir(parents=True)
            paths = DesktopPaths(resource_root, data_root)
            environment = os.environ.copy()
            prepare_desktop_environment(paths, environment)
            environment["PYTHONPATH"] = str(PROJECT_ROOT)
            script = """
import json
import config
import enrich
import zotero_server
print(json.dumps({
    "viewer": str(zotero_server.VIEWER_DIR),
    "database": str(zotero_server.DB_JSON),
    "categories": str(zotero_server.CATS_JSON),
    "search": str(zotero_server.CONFIG_JSON),
    "crawled": str(zotero_server.CRAWLED_IDS_FILE),
    "config": str(config.CONFIG_FILE),
    "pending": str(enrich.PENDING_PATH),
    "viewer_state": str(zotero_server.viewer_state_dir()),
}))
"""

            result = subprocess.run(
                [sys.executable, "-c", script],
                cwd=PROJECT_ROOT,
                env=environment,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )

            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(str(paths.viewer_dir), payload["viewer"])
            self.assertEqual(str(data_root / "papers_database.json"), payload["database"])
            self.assertEqual(str(data_root / "papercatch_categories.json"), payload["categories"])
            self.assertEqual(str(data_root / "search_config.json"), payload["search"])
            self.assertEqual(str(data_root / "crawled_ids.txt"), payload["crawled"])
            self.assertEqual(str(data_root / "config.local.json"), payload["config"])
            self.assertEqual(str(data_root / "pending_enrichment.json"), payload["pending"])
            self.assertEqual(str(paths.viewer_state_dir), payload["viewer_state"])

    def test_optional_viewer_mirror_failure_does_not_undo_primary_write(self):
        import zotero_server

        calls = []

        def fake_write(path, data):
            calls.append((Path(path), data))
            if len(calls) == 2:
                raise JsonStoreError("read-only mirror")

        primary = PROJECT_ROOT / "not-written.json"
        with mock.patch.object(zotero_server, "write_json_atomic", side_effect=fake_write):
            zotero_server.write_json_with_optional_viewer_mirror(
                primary,
                "mirror.json",
                {"ok": True},
            )

        self.assertEqual(primary, calls[0][0])
        self.assertEqual({"ok": True}, calls[0][1])
        self.assertEqual(2, len(calls))


if __name__ == "__main__":
    unittest.main()
