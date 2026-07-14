import json
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import enrich

from .server_harness import IsolatedServerTestCase, zotero_server


class StorageIntegrationTests(IsolatedServerTestCase):
    def test_enrich_and_merge_keep_both_papers_when_interleaved(self):
        self.write_json(
            self.db_path,
            {
                "papers": [
                    {
                        "arxiv_id": "A",
                        "title": "A paper",
                        "abstract": "Short abstract",
                        "tags": [],
                        "quality_score": None,
                        "quality_signals": {},
                    }
                ],
                "total_count": 1,
            },
        )
        loaded = threading.Event()
        release = threading.Event()
        merge_started = threading.Event()
        merge_done = threading.Event()
        errors = []
        original_extract = enrich.extract_tags

        def blocked_extract(paper):
            loaded.set()
            if not release.wait(5):
                raise RuntimeError("test release timeout")
            return original_extract(paper)

        paper_b = {
            "arxiv_id": "B",
            "title": "Agent paper",
            "abstract": "An agent learns.",
            "categories": ["cs.AI"],
        }

        def run_enrich():
            try:
                enrich.local_enrich(db_path=self.db_path)
            except BaseException as exc:
                errors.append(exc)

        def run_merge():
            try:
                merge_started.set()
                zotero_server.merge_into_db([paper_b])
                merge_done.set()
            except BaseException as exc:
                errors.append(exc)

        with patch.object(enrich, "extract_tags", blocked_extract):
            enrich_thread = threading.Thread(target=run_enrich)
            enrich_thread.start()
            self.assertTrue(loaded.wait(3))

            merge_thread = threading.Thread(target=run_merge)
            merge_thread.start()
            self.assertTrue(merge_started.wait(1))
            self.assertFalse(merge_done.wait(0.2))
            release.set()

            enrich_thread.join(timeout=5)
            merge_thread.join(timeout=5)

        self.assertFalse(enrich_thread.is_alive())
        self.assertFalse(merge_thread.is_alive())
        self.assertEqual([], errors)
        saved = self.read_json(self.db_path)
        self.assertEqual({"A", "B"}, {paper["arxiv_id"] for paper in saved["papers"]})

    def test_corrupt_database_returns_structured_storage_error_without_overwrite(self):
        original = b'{"papers": ['
        self.db_path.write_bytes(original)

        with patch.object(zotero_server.LOGGER, "error") as log_error:
            status, _, payload = self.request_json("GET", "/api/papers")

        self.assertEqual(500, status)
        self.assertFalse(payload["success"])
        self.assertEqual("storage_error", payload["error"]["code"])
        self.assertEqual(original, self.db_path.read_bytes())
        log_error.assert_called_once()


if __name__ == "__main__":
    unittest.main()
