"""Isolated deletion tests for the PaperCatch HTTP service."""

import unittest

if __package__:
    from .server_harness import IsolatedServerTestCase
else:
    from server_harness import IsolatedServerTestCase


class DeleteTests(IsolatedServerTestCase):
    def test_single_delete_removes_only_requested_paper(self):
        status, _, payload = self.request_json(
            "DELETE", "/api/papers", {"arxiv_ids": ["2401.00002"]}
        )

        self.assertEqual(200, status)
        self.assertTrue(payload["success"])
        self.assertEqual(1, payload["removed"])
        database = self.read_json(self.db_path)
        self.assertEqual(1, database["total_count"])
        self.assertEqual(["2401.00001"], [paper["arxiv_id"] for paper in database["papers"]])

    def test_batch_delete_removes_each_requested_paper(self):
        status, _, payload = self.request_json(
            "DELETE",
            "/api/papers",
            {"arxiv_ids": ["2401.00001", "2401.00002"]},
        )

        self.assertEqual(200, status)
        self.assertEqual(2, payload["removed"])
        database = self.read_json(self.db_path)
        self.assertEqual([], database["papers"])
        self.assertEqual(0, database["total_count"])

    def test_unknown_id_does_not_change_database(self):
        status, _, payload = self.request_json(
            "DELETE", "/api/papers", {"arxiv_ids": ["missing"]}
        )

        self.assertEqual(200, status)
        self.assertEqual(0, payload["removed"])
        database = self.read_json(self.db_path)
        self.assertEqual(2, database["total_count"])

    def test_empty_delete_does_not_change_database(self):
        status, _, payload = self.request_json(
            "DELETE", "/api/papers", {"arxiv_ids": []}
        )

        self.assertEqual(200, status)
        self.assertEqual(0, payload["removed"])
        database = self.read_json(self.db_path)
        self.assertEqual(2, database["total_count"])


if __name__ == "__main__":
    unittest.main()
