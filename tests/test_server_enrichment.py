import json
import unittest
from unittest.mock import patch

from .server_harness import IsolatedServerTestCase, zotero_server


class ServerEnrichmentTests(IsolatedServerTestCase):
    def _search_result(self, arxiv_id="2607.00001"):
        return {
            "arxiv_id": arxiv_id,
            "title": "Agent planning with a large language model",
            "abstract": "An agent uses a large language model for reliable planning.",
            "authors": ["Test Author"],
            "categories": ["cs.AI"],
            "published": "2026-07-12",
        }

    def _parsed_query(self):
        return {
            "keywords": ["agent"],
            "days": 1,
            "max_results": 1,
            "auto_zotero": False,
            "collection": "PaperCatch/Test",
        }

    def test_search_directly_enriches_the_temporary_database(self):
        paper = self._search_result()
        with patch.object(zotero_server, "llm_parse_query", return_value=self._parsed_query()), patch.object(
            zotero_server, "arxiv_search", return_value=[paper]
        ):
            status, _, payload = self.request_json(
                "POST", "/hermes/search", {"message": "recent agent paper"}
            )

        self.assertEqual(200, status)
        self.assertTrue(payload["success"])
        self.assertEqual("completed", payload["enrichment"]["status"])
        self.assertEqual([], payload["warnings"])
        database = self.read_json(self.db_path)
        saved = next(p for p in database["papers"] if p["arxiv_id"] == paper["arxiv_id"])
        self.assertIn("Agent", saved["tags"])
        self.assertIn("LLM", saved["tags"])
        self.assertIsNotNone(saved["quality_score"])
        pending_path = self.root / "pending_enrichment.json"
        self.assertTrue(pending_path.exists())
        pending_ids = {
            item["arxiv_id"]
            for item in json.loads(pending_path.read_text(encoding="utf-8"))
        }
        self.assertIn(paper["arxiv_id"], pending_ids)

    def test_enrichment_failure_warns_but_keeps_merge_and_attempts_pending(self):
        paper = self._search_result("2607.00002")
        real_mark_pending = zotero_server.mark_pending
        with patch.object(zotero_server, "llm_parse_query", return_value=self._parsed_query()), patch.object(
            zotero_server, "arxiv_search", return_value=[paper]
        ), patch.object(
            zotero_server, "local_enrich", side_effect=RuntimeError("synthetic local failure")
        ), patch.object(
            zotero_server, "mark_pending", wraps=real_mark_pending
        ) as pending, patch.object(zotero_server.LOGGER, "error") as log_error:
            status, _, payload = self.request_json(
                "POST", "/hermes/search", {"message": "recent agent paper"}
            )

        self.assertEqual(200, status)
        self.assertTrue(payload["success"])
        self.assertEqual("partial", payload["enrichment"]["status"])
        self.assertEqual("local_enrichment_failed", payload["warnings"][0]["code"])
        pending.assert_called_once()
        log_error.assert_called_once()
        database = self.read_json(self.db_path)
        self.assertIn(paper["arxiv_id"], {p["arxiv_id"] for p in database["papers"]})

        with patch.object(zotero_server, "llm_parse_query", return_value=self._parsed_query()), patch.object(
            zotero_server, "arxiv_search", return_value=[paper]
        ):
            retry_status, _, retry_payload = self.request_json(
                "POST", "/hermes/search", {"message": "retry agent paper"}
            )
        self.assertEqual(200, retry_status)
        self.assertEqual("completed", retry_payload["enrichment"]["status"])
        retried = next(
            p for p in self.read_json(self.db_path)["papers"] if p["arxiv_id"] == paper["arxiv_id"]
        )
        self.assertIn("Agent", retried["tags"])


if __name__ == "__main__":
    unittest.main()
