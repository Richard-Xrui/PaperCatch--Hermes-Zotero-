from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from urllib.error import URLError
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch

import arxiv_daily_search


class _FakeResponse:
    def __init__(self, body: bytes):
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


def _entry_xml(
    arxiv_id: str,
    *,
    title: str = "Agent paper",
    published: str = "2026-07-12T00:00:00Z",
    updated: str = "2026-07-12T00:00:00Z",
    categories: tuple[str, ...] = ("cs.AI",),
) -> str:
    category_xml = "".join(f'<category term="{category}" />' for category in categories)
    return f"""
    <entry>
      <id>http://arxiv.org/abs/{arxiv_id}v1</id>
      <updated>{updated}</updated>
      <published>{published}</published>
      <title>{title}</title>
      <summary>Agent summary.</summary>
      <author><name>Author One</name></author>
      {category_xml}
    </entry>
    """


def _feed_xml(*entries: str, total_results: int | None = None) -> bytes:
    total = len(entries) if total_results is None else total_results
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<feed xmlns="http://www.w3.org/2005/Atom" '
        'xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/">'
        f"<opensearch:totalResults>{total}</opensearch:totalResults>"
        + "".join(entries)
        + "</feed>"
    ).encode("utf-8")


def _request_category(request) -> str:
    parsed = urlparse(request.full_url)
    search_query = parse_qs(parsed.query)["search_query"][0]
    marker = "cat:"
    start = search_query.index(marker) + len(marker)
    tail = search_query[start:]
    for separator in (" ", ")"):
        if separator in tail:
            return tail.split(separator, 1)[0]
    return tail


class ArxivDailySearchQueryTests(unittest.TestCase):
    def test_normalize_keywords_returns_empty_for_blank_input(self):
        self.assertEqual([], arxiv_daily_search.normalize_keywords(""))
        self.assertEqual([], arxiv_daily_search.normalize_keywords(" , ， , "))

    def test_normalize_keywords_preserves_phrase_spacing_and_deduplicates(self):
        self.assertEqual(
            ["large language model", "agent", "multi modal"],
            arxiv_daily_search.normalize_keywords(
                "large language model, agent，large language model, multi modal , agent"
            ),
        )

    def test_build_search_query_without_keywords_uses_category_only(self):
        self.assertEqual(
            "cat:cs.AI",
            arxiv_daily_search.build_search_query("cs.AI", []),
        )

    def test_build_search_query_with_single_keyword(self):
        self.assertEqual(
            "cat:cs.AI AND (all:agent)",
            arxiv_daily_search.build_search_query("cs.AI", ["agent"]),
        )

    def test_build_search_query_with_multiple_keywords_and_phrase(self):
        self.assertEqual(
            "cat:cs.AI AND (all:large language model OR all:agentic retrieval)",
            arxiv_daily_search.build_search_query(
                "cs.AI", ["large language model", "agentic retrieval"]
            ),
        )

    def test_build_category_url_uses_structured_encoding(self):
        url = arxiv_daily_search.build_category_url(
            "cs.AI",
            ["large language model", "agent"],
            max_results=25,
        )
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        self.assertEqual("/api/query", parsed.path)
        self.assertEqual(
            ["cat:cs.AI AND (all:large language model OR all:agent)"],
            params["search_query"],
        )
        self.assertEqual(["submittedDate"], params["sortBy"])
        self.assertEqual(["descending"], params["sortOrder"])
        self.assertEqual(["25"], params["max_results"])
        self.assertIn("large+language+model", parsed.query)
        self.assertIn("cat%3Acs.AI", parsed.query)


class ArxivDailySearchRuntimeTests(unittest.TestCase):
    def run_cli(self, root: Path, argv: list[str], urlopen_side_effect):
        with patch.object(arxiv_daily_search, "BASE_DIR", root), patch.object(
            arxiv_daily_search, "OUTPUT_JSON", root / "new_papers.json"
        ), patch.object(
            arxiv_daily_search.time, "sleep", return_value=None
        ), patch.object(
            arxiv_daily_search.urllib.request, "urlopen", side_effect=urlopen_side_effect
        ):
            return arxiv_daily_search.run_cli(argv)

    def test_run_cli_fails_when_all_category_requests_fail(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output_path = root / "artifacts" / "result.json"

            def fake_urlopen(request, timeout=0):
                raise URLError(f"offline for {_request_category(request)}")

            exit_code = self.run_cli(
                root,
                [
                    "--categories",
                    "cs.AI,cs.CL",
                    "--days",
                    "0",
                    "--no-ss",
                    "--output",
                    str(output_path),
                ],
                fake_urlopen,
            )

            self.assertEqual(1, exit_code)
            self.assertFalse(output_path.exists())
            status = json.loads((output_path.parent / "run_status.json").read_text(encoding="utf-8"))
            self.assertEqual("error", status["status"])
            self.assertIn("All arXiv category requests failed", status["error"])
            self.assertIn("cs.AI", status["error"])
            self.assertFalse((root / "run_status.json").exists())

    def test_run_cli_keeps_success_when_some_categories_fail_but_one_returns_empty_feed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output_path = root / "artifacts" / "result.json"

            def fake_urlopen(request, timeout=0):
                category = _request_category(request)
                if category == "cs.AI":
                    raise URLError("temporary failure")
                return _FakeResponse(_feed_xml(total_results=0))

            exit_code = self.run_cli(
                root,
                [
                    "--categories",
                    "cs.AI,cs.CL",
                    "--days",
                    "0",
                    "--no-ss",
                    "--output",
                    str(output_path),
                ],
                fake_urlopen,
            )

            self.assertEqual(0, exit_code)
            data = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(0, data["new_count"])
            self.assertEqual(["cs.AI"], data["failed_categories"])
            self.assertEqual("temporary failure", data["category_errors"]["cs.AI"])
            status = json.loads((output_path.parent / "run_status.json").read_text(encoding="utf-8"))
            self.assertEqual("ok", status["status"])
            self.assertEqual(["cs.AI"], status["failed_categories"])

    def test_run_cli_treats_empty_feed_as_legal_empty_result(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output_path = root / "artifacts" / "result.json"

            exit_code = self.run_cli(
                root,
                [
                    "--categories",
                    "cs.AI",
                    "--days",
                    "0",
                    "--no-ss",
                    "--output",
                    str(output_path),
                ],
                lambda request, timeout=0: _FakeResponse(_feed_xml(total_results=0)),
            )

            self.assertEqual(0, exit_code)
            data = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(0, data["new_count"])
            self.assertEqual([], data["failed_categories"])
            self.assertEqual({}, data["category_errors"])
            status = json.loads((output_path.parent / "run_status.json").read_text(encoding="utf-8"))
            self.assertEqual("ok", status["status"])
            self.assertEqual(0, status["new_count"])

    def test_relative_output_uses_same_root_for_status_and_crawled_ids_lookup(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            artifacts = root / "artifacts"
            artifacts.mkdir()
            (artifacts / "crawled_ids.txt").write_text("2401.00001\n", encoding="utf-8")
            (root / "crawled_ids.txt").write_text("2401.99999\n", encoding="utf-8")
            previous_cwd = Path.cwd()
            try:
                os.chdir(root)
                exit_code = self.run_cli(
                    root,
                    [
                        "--categories",
                        "cs.AI",
                        "--days",
                        "0",
                        "--no-ss",
                        "--output",
                        "artifacts/result.json",
                    ],
                    lambda request, timeout=0: _FakeResponse(
                        _feed_xml(_entry_xml("2401.00001"))
                    ),
                )
            finally:
                os.chdir(previous_cwd)

            self.assertEqual(0, exit_code)
            data = json.loads((artifacts / "result.json").read_text(encoding="utf-8"))
            self.assertEqual(0, data["new_count"])
            status = json.loads((artifacts / "run_status.json").read_text(encoding="utf-8"))
            self.assertEqual(str((artifacts / "result.json").resolve()), status["output_file"])
            self.assertFalse((root / "run_status.json").exists())
            self.assertFalse((root / "new_papers.json").exists())

    def test_absolute_output_uses_same_root_for_status_and_crawled_ids_lookup(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            artifacts = root / "nested" / "batch"
            artifacts.mkdir(parents=True)
            (artifacts / "crawled_ids.txt").write_text("2401.00002\n", encoding="utf-8")
            (root / "new_papers.json").write_text(
                json.dumps(
                    {
                        "new_count": 99,
                        "total_after_filter": 99,
                        "new_papers": [{"arxiv_id": "stale-default-output"}],
                    }
                ),
                encoding="utf-8",
            )
            output_path = artifacts / "result.json"

            exit_code = self.run_cli(
                root,
                [
                    "--categories",
                    "cs.AI",
                    "--days",
                    "0",
                    "--no-ss",
                    "--output",
                    str(output_path),
                ],
                lambda request, timeout=0: _FakeResponse(_feed_xml(_entry_xml("2401.00002"))),
            )

            self.assertEqual(0, exit_code)
            data = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(0, data["new_count"])
            status = json.loads((artifacts / "run_status.json").read_text(encoding="utf-8"))
            self.assertEqual(0, status["new_count"])
            self.assertEqual(1, status["total_count"])
            self.assertEqual(str(output_path.resolve()), status["output_file"])
            self.assertFalse((root / "run_status.json").exists())

    def test_search_success_does_not_commit_crawled_ids_before_merge(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output_path = root / "artifacts" / "result.json"

            exit_code = self.run_cli(
                root,
                [
                    "--categories",
                    "cs.AI",
                    "--days",
                    "0",
                    "--no-ss",
                    "--output",
                    str(output_path),
                ],
                lambda request, timeout=0: _FakeResponse(
                    _feed_xml(_entry_xml("2401.00003"))
                ),
            )

            self.assertEqual(0, exit_code)
            self.assertEqual(
                1,
                json.loads(output_path.read_text(encoding="utf-8"))["new_count"],
            )
            self.assertFalse((output_path.parent / "crawled_ids.txt").exists())

    def test_output_write_failure_does_not_commit_crawled_ids(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output_path = root / "artifacts" / "result.json"
            real_write = arxiv_daily_search.write_json_atomic

            def fail_output_write(path, data):
                if Path(path).resolve() == output_path.resolve():
                    raise OSError("synthetic output failure")
                return real_write(path, data)

            with patch.object(
                arxiv_daily_search,
                "write_json_atomic",
                side_effect=fail_output_write,
            ):
                exit_code = self.run_cli(
                    root,
                    [
                        "--categories",
                        "cs.AI",
                        "--days",
                        "0",
                        "--no-ss",
                        "--output",
                        str(output_path),
                    ],
                    lambda request, timeout=0: _FakeResponse(
                        _feed_xml(_entry_xml("2401.00004"))
                    ),
                )

            self.assertEqual(1, exit_code)
            self.assertFalse(output_path.exists())
            self.assertFalse((output_path.parent / "crawled_ids.txt").exists())
            status = json.loads(
                (output_path.parent / "run_status.json").read_text(encoding="utf-8")
            )
            self.assertEqual("error", status["status"])
            self.assertIn("synthetic output failure", status["error"])


if __name__ == "__main__":
    unittest.main()
