from __future__ import annotations

import unittest
from unittest.mock import patch

from .server_harness import IsolatedServerTestCase, zotero_server


class ServerAgentTests(IsolatedServerTestCase):
    def setUp(self) -> None:
        super().setUp()
        database = self.read_json(self.db_path)
        database["papers"][0].update({
            "paper_id": "doi:10.1000/paper-a",
            "doi": "10.1000/paper-a",
            "abstract_full": "We propose a controlled method for reliable agent planning. Experiments improve accuracy.",
            "summary_cn": "论文提出一种可靠的智能体规划方法。",
            "sources": ["openalex", "crossref"],
        })
        self.write_json(self.db_path, database)

    def test_ask_endpoint_answers_from_saved_paper_context(self):
        status, _, payload = self.request_json(
            "POST",
            "/hermes/ask",
            {"paper_id": "doi:10.1000/paper-a", "question": "方法是什么？"},
        )
        self.assertEqual(200, status)
        self.assertTrue(payload["success"])
        self.assertTrue(payload["grounded"])
        self.assertIn("method", payload["answer"])
        self.assertEqual("builtin", payload["mode"])

    def test_notes_endpoint_returns_learning_markdown(self):
        status, _, payload = self.request_json(
            "POST",
            "/hermes/notes",
            {"paper_id": "doi:10.1000/paper-a", "focus": "实验结果"},
        )
        self.assertEqual(200, status)
        self.assertTrue(payload["success"])
        self.assertIn("学习笔记", payload["markdown"])
        self.assertIn("## 主要发现", payload["markdown"])

    def test_agent_rejects_unknown_paper(self):
        status, _, payload = self.request_json(
            "POST", "/hermes/ask", {"paper_id": "doi:missing", "question": "总结"}
        )
        self.assertEqual(404, status)
        self.assertEqual("not_found", payload["error"]["code"])

    def test_search_can_use_configured_multi_sources(self):
        config = {**self.initial_config, "sources": ["openalex", "crossref"]}
        self.write_json(self.config_path, config)
        paper = {
            "paper_id": "doi:10.1000/new",
            "arxiv_id": "doi:10.1000/new",
            "doi": "10.1000/new",
            "title": "Global paper",
            "abstract": "A global abstract.",
            "authors": [],
            "categories": [],
            "published": "2026-07-13",
        }
        with patch.object(zotero_server, "llm_parse_query", return_value=None), patch.object(
            zotero_server,
            "search_all_sources",
            return_value={
                "papers": [paper],
                "source_errors": {"crossref": "offline"},
                "source_counts": {"openalex": 1, "crossref": 0},
            },
        ):
            status, _, payload = self.request_json(
                "POST", "/hermes/search", {"message": "recent agent papers"}
            )
        self.assertEqual(200, status)
        self.assertEqual(["openalex", "crossref"], payload["sources"])
        self.assertEqual({"crossref": "offline"}, payload["source_errors"])
        self.assertEqual(1, len(payload["papers"]))

    def test_search_without_sources_keeps_default_single_source_arxiv_path(self):
        paper = {
            "paper_id": "2607.00002",
            "arxiv_id": "2607.00002",
            "title": "Default arXiv paper",
            "abstract": "Single-source fallback result.",
            "authors": [],
            "categories": ["cs.AI"],
            "published": "2026-07-14",
        }
        with patch.object(zotero_server, "llm_parse_query", return_value=None), patch.object(
            zotero_server,
            "arxiv_search",
            return_value=[paper],
        ) as arxiv_search_mock, patch.object(
            zotero_server,
            "search_all_sources",
        ) as multi_source_mock:
            status, _, payload = self.request_json(
                "POST", "/hermes/search", {"message": "recent agent papers"}
            )

        self.assertEqual(200, status)
        self.assertEqual(["arxiv"], payload["sources"])
        arxiv_search_mock.assert_called_once()
        multi_source_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
