from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import paper_download

if __package__:
    from .server_harness import IsolatedServerTestCase, zotero_server
else:
    from server_harness import IsolatedServerTestCase, zotero_server


class ManifestSafetyTests(unittest.TestCase):
    def test_manifest_cannot_reuse_file_outside_pdf_root(self):
        paper = {
            "paper_id": "arxiv:2607.00001",
            "doi": "",
            "arxiv_id": "2607.00001",
            "title": "Safe paper",
            "open_access": True,
            "pdf_url": "https://example.test/paper.pdf",
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            pdf_root = root / "PDFs"
            pdf_root.mkdir()
            outside = root / "outside.pdf"
            outside.write_bytes(b"%PDF-1.7\noutside")
            (pdf_root / "manifest.json").write_text(
                json.dumps(
                    {
                        "entries": [{
                            "status": "downloaded",
                            "aliases": ["arxiv:2607.00001", "2607.00001"],
                            "file_path": str(outside),
                        }]
                    }
                ),
                encoding="utf-8",
            )

            calls = {"count": 0}

            def opener(request, timeout=20):
                calls["count"] += 1
                return _FakeResponse(b"%PDF-1.7\ninside")

            result = paper_download.download_open_access_pdf(paper, root, opener=opener)
            self.assertEqual("downloaded", result["status"])
            self.assertEqual(1, calls["count"])
            self.assertNotEqual(str(outside.resolve()), result["file_path"])
            self.assertTrue(Path(result["file_path"]).resolve().is_file())
            Path(result["file_path"]).resolve().relative_to(pdf_root.resolve())


class _FakeHeaders:
    def get_content_type(self) -> str:
        return "application/pdf"


class _FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body
        self.headers = _FakeHeaders()

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read(self, size: int = -1) -> bytes:
        if size < 0:
            size = len(self._body)
        chunk = self._body[:size]
        self._body = self._body[size:]
        return chunk


class _FakeUrlopenResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self) -> "_FakeUrlopenResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read(self) -> bytes:
        return self._body


class ServerDownloadTests(IsolatedServerTestCase):
    def test_single_source_arxiv_results_are_marked_open_access_for_download_route(self):
        feed = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2607.00001v2</id>
    <updated>2026-07-14T01:02:03Z</updated>
    <published>2026-07-14T01:02:03Z</published>
    <title>Legacy arXiv Result</title>
    <summary>Legacy arXiv abstract</summary>
    <author><name>Author One</name></author>
    <category term="cs.AI" />
  </entry>
</feed>
"""
        with patch.object(zotero_server, "llm_parse_query", return_value=None), patch.object(
            zotero_server.urllib.request,
            "urlopen",
            return_value=_FakeUrlopenResponse(feed),
        ), patch.object(zotero_server, "local_enrich", return_value=0), patch.object(
            zotero_server, "mark_pending", return_value=0
        ):
            status, _, payload = self.request_json(
                "POST",
                "/hermes/search",
                {"message": "legacy arxiv result"},
            )

        self.assertEqual(200, status)
        self.assertTrue(payload["success"])
        self.assertEqual(["arxiv"], payload["sources"])
        self.assertTrue(payload["papers"][0]["open_access"])
        self.assertTrue(payload["papers"][0]["is_open_access"])

        saved = next(
            paper
            for paper in self.read_json(self.db_path)["papers"]
            if paper["arxiv_id"] == "2607.00001"
        )
        self.assertTrue(saved["open_access"])
        self.assertTrue(saved["is_open_access"])

        calls = {"count": 0}

        def fake_download(paper, data_root):
            calls["count"] += 1
            self.assertTrue(paper["open_access"])
            return {
                "paper_id": paper.get("paper_id", paper["arxiv_id"]),
                "arxiv_id": paper["arxiv_id"],
                "doi": "",
                "status": "downloaded",
                "reason": "ok",
                "downloaded_at": "2026-07-14T03:00:00+00:00",
                "file_path": str(Path(data_root) / "PDFs" / "2607.00001.pdf"),
            }

        with patch.object(zotero_server, "download_open_access_pdf", side_effect=fake_download):
            download_status, _, download_payload = self.request_json(
                "POST",
                "/api/papers/download",
                {"paper_ids": ["2607.00001"]},
            )

        self.assertEqual(200, download_status)
        self.assertEqual(1, calls["count"])
        self.assertEqual(1, download_payload["downloaded"])
        self.assertEqual("downloaded", download_payload["results"][0]["status"])

    def test_download_route_updates_database_and_counts(self):
        database = self.read_json(self.db_path)
        database["papers"][0].update(
            {"paper_id": "doi:10.1000/demo", "doi": "10.1000/demo", "pmid": "12345"}
        )
        database["papers"][1].update({"pdf_path": "keep-existing.pdf"})
        self.write_json(self.db_path, database)

        def fake_download(paper, data_root):
            if paper.get("doi") == "10.1000/demo":
                return {
                    "paper_id": "doi:10.1000/demo",
                    "arxiv_id": paper["arxiv_id"],
                    "doi": "10.1000/demo",
                    "status": "downloaded",
                    "reason": "ok",
                    "downloaded_at": "2026-07-14T01:00:00+00:00",
                    "file_path": str(Path(data_root) / "PDFs" / "doi_10.1000_demo.pdf"),
                }
            return {
                "paper_id": paper.get("paper_id", ""),
                "arxiv_id": paper["arxiv_id"],
                "doi": paper.get("doi", ""),
                "status": "no_authorized_pdf_found",
                "reason": "open_access_false_or_missing_pdf_url",
                "downloaded_at": "2026-07-14T01:05:00+00:00",
                "file_path": "",
            }

        with patch.object(zotero_server, "download_open_access_pdf", side_effect=fake_download):
            status, _, payload = self.request_json(
                "POST",
                "/api/papers/download",
                {"paper_ids": ["10.1000/demo", "10.1000/demo"], "arxiv_ids": ["2401.00002"]},
            )

        self.assertEqual(200, status)
        self.assertTrue(payload["success"])
        self.assertEqual(1, payload["downloaded"])
        self.assertEqual(0, payload["already_exists"])
        self.assertEqual(1, payload["failed"])
        self.assertEqual(2, len(payload["results"]))
        saved = self.read_json(self.db_path)["papers"]
        downloaded = next(item for item in saved if item.get("doi") == "10.1000/demo")
        self.assertEqual("downloaded", downloaded["download_status"])
        self.assertTrue(downloaded["pdf_path"].endswith("doi_10.1000_demo.pdf"))
        self.assertEqual("ok", downloaded["download_reason"])
        self.assertEqual("2026-07-14T01:00:00+00:00", downloaded["downloaded_at"])
        failed = next(item for item in saved if item["arxiv_id"] == "2401.00002")
        self.assertEqual("no_authorized_pdf_found", failed["download_status"])
        self.assertEqual("open_access_false_or_missing_pdf_url", failed["download_reason"])
        self.assertEqual("2026-07-14T01:05:00+00:00", failed["downloaded_at"])
        self.assertEqual("keep-existing.pdf", failed["pdf_path"])

    def test_download_route_deduplicates_semantically_equivalent_identifiers(self):
        database = self.read_json(self.db_path)
        database["papers"][0].update({"paper_id": "doi:10.1000/demo", "doi": "10.1000/demo"})
        self.write_json(self.db_path, database)

        calls = {"count": 0}

        def fake_download(paper, data_root):
            calls["count"] += 1
            return {
                "paper_id": "doi:10.1000/demo",
                "arxiv_id": paper["arxiv_id"],
                "doi": "10.1000/demo",
                "status": "downloaded",
                "reason": "ok",
                "downloaded_at": "2026-07-14T01:30:00+00:00",
                "file_path": str(Path(data_root) / "PDFs" / "doi_10.1000_demo.pdf"),
            }

        with patch.object(zotero_server, "download_open_access_pdf", side_effect=fake_download):
            status, _, payload = self.request_json(
                "POST",
                "/api/papers/download",
                {"paper_ids": ["doi:10.1000/demo", "10.1000/demo"], "arxiv_ids": ["2401.00001"]},
            )

        self.assertEqual(200, status)
        self.assertEqual(1, calls["count"])
        self.assertEqual(1, len(payload["results"]))
        self.assertEqual("downloaded", payload["results"][0]["status"])
        saved = self.read_json(self.db_path)["papers"][0]
        self.assertEqual("downloaded", saved["download_status"])
        self.assertEqual("ok", saved["download_reason"])

    def test_download_route_supports_existing_file_and_not_found(self):
        database = self.read_json(self.db_path)
        database["papers"][0].update({"paper_id": "pmid:999", "pmid": "999"})
        self.write_json(self.db_path, database)

        with patch.object(
            zotero_server,
            "download_open_access_pdf",
            return_value={
                "paper_id": "pmid:999",
                "arxiv_id": "2401.00001",
                "doi": "",
                "status": "already_exists",
                "reason": "existing_valid_pdf",
                "downloaded_at": "2026-07-14T02:00:00+00:00",
                "file_path": str(self.root / "PDFs" / "pmid_999.pdf"),
            },
        ):
            status, _, payload = self.request_json(
                "POST",
                "/api/papers/download",
                {"paper_ids": ["pmid:999", "missing-paper"]},
            )

        self.assertEqual(200, status)
        self.assertEqual(0, payload["downloaded"])
        self.assertEqual(1, payload["already_exists"])
        self.assertEqual(1, payload["failed"])
        self.assertEqual(1, payload["not_found"])
        self.assertEqual("already_exists", payload["results"][0]["status"])
        self.assertEqual("not_found", payload["results"][1]["status"])
        saved = self.read_json(self.db_path)["papers"][0]
        self.assertEqual("already_exists", saved["download_status"])
        self.assertTrue(saved["pdf_path"].endswith("pmid_999.pdf"))

    def test_download_route_keeps_not_found_when_mixed_with_known_identifier(self):
        database = self.read_json(self.db_path)
        database["papers"][0].update({"paper_id": "pmid:999", "pmid": "999"})
        self.write_json(self.db_path, database)

        with patch.object(
            zotero_server,
            "download_open_access_pdf",
            return_value={
                "paper_id": "pmid:999",
                "arxiv_id": "2401.00001",
                "doi": "",
                "status": "already_exists",
                "reason": "existing_valid_pdf",
                "downloaded_at": "2026-07-14T02:00:00+00:00",
                "file_path": str(self.root / "PDFs" / "pmid_999.pdf"),
            },
        ):
            status, _, payload = self.request_json(
                "POST",
                "/api/papers/download",
                {"paper_ids": ["missing-paper", "pmid:999"]},
            )

        self.assertEqual(200, status)
        self.assertEqual(["not_found", "already_exists"], [item["status"] for item in payload["results"]])

    def test_download_route_rejects_invalid_identifier_shapes(self):
        cases = [
            ({}, "paper_ids or arxiv_ids is required"),
            ({"paper_ids": []}, "paper_ids or arxiv_ids is required"),
            ({"paper_ids": ["ok", 7]}, "paper_ids and arxiv_ids must be arrays of strings"),
            ({"paper_ids": [str(index) for index in range(11)]}, "paper_ids and arxiv_ids must contain 1 to 10 unique strings"),
            ({"paper_ids": "2401.00001"}, "paper_ids must be an array of strings"),
        ]
        for body, message in cases:
            with self.subTest(body=body):
                status, _, payload = self.request_json("POST", "/api/papers/download", body)
                self.assertEqual(400, status)
                self.assertFalse(payload["success"])
                self.assertEqual("invalid_request", payload["error"]["code"])
                self.assertIn(message, payload["error"]["message"])

    def test_multisource_all_failed_returns_structured_502(self):
        with patch.object(zotero_server, "llm_parse_query", return_value=None), patch.object(
            zotero_server,
            "search_all_sources",
            return_value={
                "papers": [],
                "source_errors": {"openalex": "down", "crossref": "timeout"},
                "source_counts": {"openalex": 0, "crossref": 0},
            },
        ):
            status, _, payload = self.request_json(
                "POST",
                "/hermes/search",
                {"message": "agent", "sources": ["openalex", "crossref"]},
            )

        self.assertEqual(502, status)
        self.assertFalse(payload["success"])
        self.assertEqual("upstream_error", payload["error"]["code"])
        self.assertEqual(
            {"openalex": "down", "crossref": "timeout"},
            payload["source_errors"],
        )

    def test_multisource_partial_failure_with_empty_success_still_returns_200(self):
        with patch.object(zotero_server, "llm_parse_query", return_value=None), patch.object(
            zotero_server,
            "search_all_sources",
            return_value={
                "papers": [],
                "source_errors": {"crossref": "timeout"},
                "source_counts": {"openalex": 0, "crossref": 0},
            },
        ):
            status, _, payload = self.request_json(
                "POST",
                "/hermes/search",
                {"message": "agent", "sources": ["openalex", "crossref"]},
            )

        self.assertEqual(200, status)
        self.assertTrue(payload["success"])
        self.assertEqual([], payload["papers"])
        self.assertEqual({"crossref": "timeout"}, payload["source_errors"])


if __name__ == "__main__":
    unittest.main()
