from __future__ import annotations

import json
import socket
import tempfile
import unittest
import urllib.error
from pathlib import Path

import paper_download


class _FakeHeaders:
    def __init__(self, content_type: str) -> None:
        self._content_type = content_type

    def get_content_type(self) -> str:
        return self._content_type


class _FakeResponse:
    def __init__(self, body: bytes, status: int = 200, content_type: str = "application/pdf") -> None:
        self._body = body
        self._status = status
        self.headers = _FakeHeaders(content_type)

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            size = len(self._body)
        chunk = self._body[:size]
        self._body = self._body[size:]
        return chunk

    def getcode(self) -> int:
        return self._status


class PaperDownloadTests(unittest.TestCase):
    def _paper(self, **overrides):
        paper = {
            "paper_id": "arxiv:2607.00001",
            "doi": "10.1000/demo",
            "arxiv_id": "2607.00001v1",
            "title": "A safe OA paper",
            "open_access": True,
            "pdf_url": "https://example.test/paper.pdf",
        }
        paper.update(overrides)
        return paper

    def test_downloads_valid_pdf_atomically_and_records_manifest(self):
        calls = []

        def opener(request, timeout=20):
            calls.append((request.full_url, timeout))
            return _FakeResponse(b"%PDF-1.7\nbody", 200, "application/pdf")

        with tempfile.TemporaryDirectory() as temp_dir:
            result = paper_download.download_open_access_pdf(self._paper(), temp_dir, opener=opener)
            pdf_root = Path(temp_dir) / "PDFs"
            saved = pdf_root / "arxiv_2607.00001.pdf"
            self.assertEqual("downloaded", result["status"])
            self.assertTrue(saved.is_file())
            self.assertEqual(b"%PDF-1.7\nbody", saved.read_bytes())
            self.assertFalse((pdf_root / "arxiv_2607.00001.pdf.part").exists())
            manifest = json.loads((pdf_root / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual("downloaded", manifest["entries"][-1]["status"])
            self.assertEqual([("https://example.test/paper.pdf", 20)], calls)

    def test_reuses_existing_pdf_by_alias_without_network(self):
        calls = []

        def first_opener(request, timeout=20):
            calls.append("first")
            return _FakeResponse(b"%PDF-1.7\nbody", 200, "application/pdf")

        def second_opener(request, timeout=20):
            calls.append("second")
            raise AssertionError("should not be called")

        with tempfile.TemporaryDirectory() as temp_dir:
            paper_download.download_open_access_pdf(self._paper(), temp_dir, opener=first_opener)
            result = paper_download.download_open_access_pdf(
                self._paper(paper_id="title:other", title="Different title"), temp_dir, opener=second_opener
            )
            self.assertEqual("already_exists", result["status"])
            self.assertEqual(1, calls.count("first"))
            self.assertNotIn("second", calls)

    def test_refuses_missing_authorized_pdf(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            result = paper_download.download_open_access_pdf(
                self._paper(open_access=True, pdf_url=""), temp_dir, opener=None
            )
            self.assertEqual("no_authorized_pdf_found", result["status"])
            self.assertEqual("open_access_false_or_missing_pdf_url", result["reason"])

    def test_html_response_is_rejected_and_leaves_no_part_file(self):
        def opener(request, timeout=20):
            return _FakeResponse(b"<html>Denied</html>", 200, "text/html")

        with tempfile.TemporaryDirectory() as temp_dir:
            result = paper_download.download_open_access_pdf(self._paper(), temp_dir, opener=opener)
            pdf_root = Path(temp_dir) / "PDFs"
            self.assertEqual("invalid_pdf", result["status"])
            self.assertEqual("html_response", result["reason"])
            self.assertFalse(any(pdf_root.glob("*.part")))
            self.assertFalse((pdf_root / "arxiv_2607.00001.pdf").exists())

    def test_permission_denied_is_reported_without_retrying_past_limit(self):
        def opener(request, timeout=20):
            raise urllib.error.HTTPError(
                request.full_url, 403, "Forbidden", hdrs=None, fp=None
            )

        with tempfile.TemporaryDirectory() as temp_dir:
            result = paper_download.download_open_access_pdf(self._paper(), temp_dir, opener=opener)
            self.assertEqual("no_authorized_pdf_found", result["status"])
            self.assertEqual(1, result["attempts"])
            self.assertEqual(403, result["http_status"])

    def test_retryable_timeout_eventually_fails_after_bounded_attempts(self):
        calls = {"count": 0}

        def opener(request, timeout=20):
            calls["count"] += 1
            raise socket.timeout("timed out")

        with tempfile.TemporaryDirectory() as temp_dir:
            result = paper_download.download_open_access_pdf(
                self._paper(), temp_dir, opener=opener, max_retries=2
            )
            self.assertEqual("failed_after_retry", result["status"])
            self.assertEqual(3, result["attempts"])
            self.assertEqual(3, calls["count"])
            self.assertFalse(any((Path(temp_dir) / "PDFs").glob("*.part")))

    def test_manifest_append_preserves_existing_entries(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manifest_path = Path(temp_dir) / "PDFs" / "manifest.json"
            paper_download._append_manifest(
                {"entries": []},
                manifest_path,
                {"status": "downloaded", "file_path": "one.pdf", "aliases": ["one"]},
            )
            paper_download._append_manifest(
                {"entries": []},
                manifest_path,
                {"status": "already_exists", "file_path": "two.pdf", "aliases": ["two"]},
            )
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(
                ["downloaded", "already_exists"],
                [entry["status"] for entry in manifest["entries"]],
            )


if __name__ == "__main__":
    unittest.main()
