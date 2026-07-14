"""Isolated HTTP server harness for PaperCatch integration tests."""

from __future__ import annotations

import http.client
import builtins
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

REAL_CONFIG_PATH = (PROJECT_ROOT / "config.local.json").resolve()
_path_exists = Path.exists
_builtin_open = builtins.open


def _is_real_config_path(value) -> bool:
    try:
        return Path(value).resolve() == REAL_CONFIG_PATH
    except (OSError, TypeError, ValueError):
        return False


def _safe_exists(path) -> bool:
    if _is_real_config_path(path):
        return False
    return _path_exists(path)


def _guarded_open(file, *args, **kwargs):
    if _is_real_config_path(file):
        raise AssertionError("tests must not read the real config.local.json")
    return _builtin_open(file, *args, **kwargs)


with patch.object(Path, "exists", _safe_exists), patch(
    "builtins.open", _guarded_open
):
    import zotero_server  # noqa: E402


class IsolatedServerTestCase(unittest.TestCase):
    """Run the real request handler against temporary data on loopback."""

    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp_dir.cleanup)

        self.root = Path(self._temp_dir.name)
        self.viewer_dir = self.root / "viewer"
        self.viewer_dir.mkdir()
        (self.viewer_dir / "index.html").write_text(
            "<!doctype html><title>PaperCatch Test</title><h1>纸上得来 · PaperCatch</h1>",
            encoding="utf-8",
        )
        (self.viewer_dir / "app.js").write_text(
            'document.documentElement.dataset.app = "papercatch";\n',
            encoding="utf-8",
        )

        self.db_path = self.root / "papers_database.json"
        self.cats_path = self.root / "papercatch_categories.json"
        self.config_path = self.root / "search_config.json"
        self.viewer_config_path = self.viewer_dir / "search_config.json"
        self.crawled_path = self.root / "crawled_ids.txt"

        self.paper_a = {
            "arxiv_id": "2401.00001",
            "title": "Paper A",
            "authors": ["Author A"],
            "categories": ["cs.AI"],
            "published": "2026-07-11",
        }
        self.paper_b = {
            "arxiv_id": "2401.00002",
            "title": "Paper B",
            "authors": ["Author B"],
            "categories": ["cs.CL"],
            "published": "2026-07-12",
        }
        self.write_json(
            self.db_path,
            {
                "papers": [self.paper_a, self.paper_b],
                "total_count": 2,
                "updated_at": "2026-07-12T00:00:00+00:00",
            },
        )
        self.write_json(
            self.cats_path,
            [{"id": "llm", "label": "大语言模型", "keywords": "LLM,agent"}],
        )
        self.initial_config = {
            "categories": ["cs.AI", "cs.CL"],
            "keywords": "agent",
            "max_per_cat": 12,
            "days": 3,
        }
        self.write_json(self.config_path, self.initial_config)
        self.write_json(self.viewer_config_path, self.initial_config)

        patch_values = {
            "BASE_DIR": self.root,
            "VIEWER_DIR": self.viewer_dir,
            "DB_JSON": self.db_path,
            "CATS_JSON": self.cats_path,
            "CONFIG_JSON": self.config_path,
            "CRAWLED_IDS_FILE": self.crawled_path,
            "APP_CONFIG": {},
            "ZOTERO_API_KEY": "",
            "ZOTERO_USER_ID": "",
            "ZOTERO_API_ROOT": "",
            "DEFAULT_COLLECTION": "PaperCatch/Test",
        }
        self._patcher = patch.multiple(zotero_server, **patch_values)
        self._patcher.start()
        self.addCleanup(self._patcher.stop)

        self.server = zotero_server.ThreadingHTTPServer(
            ("127.0.0.1", 0), zotero_server.Handler
        )
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        self._server_thread = threading.Thread(
            target=self.server.serve_forever,
            name="papercatch-test-server",
            daemon=True,
        )
        self._server_thread.start()
        self.addCleanup(self._stop_server)

    def _stop_server(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self._server_thread.join(timeout=3)

    def request(self, method, path, body=None, headers=None):
        request_headers = dict(headers or {})
        request_body = body
        if isinstance(body, (dict, list)):
            request_body = json.dumps(body, ensure_ascii=False).encode("utf-8")
            request_headers.setdefault("Content-Type", "application/json")
        elif isinstance(body, str):
            request_body = body.encode("utf-8")

        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        try:
            connection.request(method, path, body=request_body, headers=request_headers)
            response = connection.getresponse()
            response_body = response.read()
            response_headers = {key.lower(): value for key, value in response.getheaders()}
            return response.status, response_headers, response_body
        finally:
            connection.close()

    def request_json(self, method, path, body=None, headers=None):
        status, response_headers, response_body = self.request(
            method, path, body=body, headers=headers
        )
        return status, response_headers, json.loads(response_body.decode("utf-8"))

    @staticmethod
    def write_json(path, data) -> None:
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def read_json(path):
        return json.loads(path.read_text(encoding="utf-8"))
