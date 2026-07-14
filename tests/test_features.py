"""Isolated feature tests for the PaperCatch HTTP service."""

import unittest

if __package__:
    from .server_harness import IsolatedServerTestCase
else:
    from server_harness import IsolatedServerTestCase


class FeatureTests(IsolatedServerTestCase):
    def test_health(self):
        status, headers, payload = self.request_json("GET", "/health")

        self.assertEqual(200, status)
        self.assertTrue(headers["content-type"].startswith("application/json"))
        self.assertEqual({"status": "ok", "service": "PaperCatch"}, payload)

    def test_papers_api(self):
        status, _, payload = self.request_json("GET", "/api/papers")

        self.assertEqual(200, status)
        self.assertEqual(2, payload["total_count"])
        self.assertEqual(
            ["2401.00001", "2401.00002"],
            [paper["arxiv_id"] for paper in payload["papers"]],
        )
        self.assertEqual("2026-07-12T00:00:00+00:00", payload["updated_at"])

    def test_categories_api(self):
        status, _, payload = self.request_json("GET", "/api/categories")

        self.assertEqual(200, status)
        self.assertEqual("llm", payload[0]["id"])
        self.assertEqual("大语言模型", payload[0]["label"])

    def test_config_api(self):
        status, _, payload = self.request_json("GET", "/api/config")

        self.assertEqual(200, status)
        self.assertEqual(self.initial_config, payload)

    def test_sources_api_lists_public_adapters(self):
        status, _, payload = self.request_json("GET", "/api/sources")

        self.assertEqual(200, status)
        self.assertEqual(
            ["arxiv", "openalex", "crossref", "semantic_scholar", "europe_pmc"],
            payload["sources"],
        )

    def test_config_fallback_can_be_saved_again(self):
        self.config_path.unlink()

        status, _, payload = self.request_json("GET", "/api/config")
        self.assertEqual(200, status)
        self.assertIn("keywords", payload)

        save_status, _, save_payload = self.request_json("POST", "/api/config", payload)
        self.assertEqual(200, save_status)
        self.assertTrue(save_payload["success"])

    def test_valid_config_update_is_written_to_both_locations(self):
        updated = {
            "categories": ["cs.CV"],
            "keywords": "vision agent",
            "max_per_cat": 8,
            "days": 1,
        }

        status, _, payload = self.request_json("POST", "/api/config", updated)

        self.assertEqual(200, status)
        self.assertTrue(payload["success"])
        self.assertEqual(updated, self.read_json(self.config_path))
        self.assertEqual(updated, self.read_json(self.viewer_config_path))

    def test_multi_source_config_is_written_to_both_locations(self):
        updated = {
            **self.initial_config,
            "sources": ["arxiv", "openalex", "europe_pmc"],
        }

        status, _, payload = self.request_json("POST", "/api/config", updated)

        self.assertEqual(200, status)
        self.assertTrue(payload["success"])
        self.assertEqual(updated, self.read_json(self.config_path))
        self.assertEqual(updated, self.read_json(self.viewer_config_path))

    def test_valid_categories_update_is_written_to_both_locations(self):
        updated = [
            {"id": "agent", "label": "智能体", "keywords": "agent,memory"},
            {"id": "cv", "label": "计算机视觉"},
        ]

        status, _, payload = self.request_json("POST", "/api/categories", updated)

        self.assertEqual(200, status)
        self.assertTrue(payload["success"])
        self.assertEqual(updated, self.read_json(self.cats_path))
        self.assertEqual(
            updated,
            self.read_json(self.viewer_dir / "papercatch_categories.json"),
        )

    def test_frontend_index(self):
        status, headers, body = self.request("GET", "/")

        self.assertEqual(200, status)
        self.assertTrue(headers["content-type"].startswith("text/html"))
        self.assertIn("PaperCatch", body.decode("utf-8"))

    def test_frontend_script(self):
        status, headers, body = self.request("GET", "/app.js")

        self.assertEqual(200, status)
        self.assertTrue(headers["content-type"].startswith("application/javascript"))
        self.assertIn("papercatch", body.decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
