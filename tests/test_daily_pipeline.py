from __future__ import annotations

import json
import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import daily_pipeline


class DailyPipelineConfigTests(unittest.TestCase):
    def test_search_config_defaults_are_forwarded_when_cli_omits_values(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "search_config.json").write_text(
                json.dumps(
                    {
                        "days": 7,
                        "max_per_cat": 42,
                        "categories": ["cs.AI", "cs.CL"],
                        "keywords": "large language model, agent",
                    }
                ),
                encoding="utf-8",
            )

            calls = []

            def fake_run(cmd, **kwargs):
                calls.append((cmd, kwargs))
                return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

            with patch.object(daily_pipeline, "BASE_DIR", root), patch.object(
                sys, "argv", ["daily_pipeline.py"]
            ), patch.object(daily_pipeline.subprocess, "run", side_effect=fake_run):
                daily_pipeline.main()

            self.assertEqual(1, len(calls))
            cmd, kwargs = calls[0]
            self.assertEqual([sys.executable, str(root / "arxiv_daily_search.py")], cmd[:2])
            self.assertIn("--days", cmd)
            self.assertIn("--max-per-cat", cmd)
            self.assertIn("--categories", cmd)
            self.assertIn("--keywords", cmd)
            self.assertEqual("7", cmd[cmd.index("--days") + 1])
            self.assertEqual("42", cmd[cmd.index("--max-per-cat") + 1])
            self.assertEqual("cs.AI,cs.CL", cmd[cmd.index("--categories") + 1])
            self.assertEqual(
                "large language model, agent",
                cmd[cmd.index("--keywords") + 1],
            )
            self.assertEqual(str(root), kwargs["cwd"])
            self.assertEqual(
                '["cs.AI", "cs.CL"]',
                kwargs["env"]["PAPERCATCH_SEARCH_CATEGORIES"],
            )
            self.assertEqual(
                "large language model, agent",
                kwargs["env"]["PAPERCATCH_SEARCH_KEYWORDS"],
            )

    def test_explicit_cli_zero_and_25_are_not_overridden(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "search_config.json").write_text(
                json.dumps(
                    {
                        "days": 7,
                        "max_per_cat": 42,
                        "categories": ["cs.CV"],
                        "keywords": "vision transformer",
                    }
                ),
                encoding="utf-8",
            )

            calls = []

            def fake_run(cmd, **kwargs):
                calls.append((cmd, kwargs))
                return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

            with patch.object(daily_pipeline, "BASE_DIR", root), patch.object(
                sys,
                "argv",
                ["daily_pipeline.py", "--days", "0", "--max-per-cat", "25"],
            ), patch.object(daily_pipeline.subprocess, "run", side_effect=fake_run):
                daily_pipeline.main()

            self.assertEqual(1, len(calls))
            cmd, kwargs = calls[0]
            self.assertEqual("0", cmd[cmd.index("--days") + 1])
            self.assertEqual("25", cmd[cmd.index("--max-per-cat") + 1])
            self.assertEqual("cs.CV", cmd[cmd.index("--categories") + 1])
            self.assertEqual(
                "vision transformer",
                cmd[cmd.index("--keywords") + 1],
            )
            self.assertEqual(
                "vision transformer",
                kwargs["env"]["PAPERCATCH_SEARCH_KEYWORDS"],
            )

    def test_configured_non_arxiv_sources_select_multi_source_searcher(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "search_config.json").write_text(
                json.dumps({
                    "days": 2,
                    "max_per_cat": 5,
                    "categories": ["cs.AI"],
                    "keywords": "agent",
                    "sources": ["arxiv", "openalex", "crossref"],
                }),
                encoding="utf-8",
            )
            calls = []

            def fake_run(cmd, **kwargs):
                calls.append((cmd, kwargs))
                return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

            with patch.object(daily_pipeline, "BASE_DIR", root), patch.object(
                sys, "argv", ["daily_pipeline.py"]
            ), patch.object(daily_pipeline.subprocess, "run", side_effect=fake_run):
                daily_pipeline.main()

            self.assertEqual(1, len(calls))
            cmd, _ = calls[0]
            self.assertEqual(str(root / "paper_sources.py"), cmd[1])
            self.assertEqual("arxiv,openalex,crossref", cmd[cmd.index("--sources") + 1])
            self.assertEqual("5", cmd[cmd.index("--max-results") + 1])


class DailyPipelineCrawledIdTests(unittest.TestCase):
    @staticmethod
    def write_batch(root: Path, arxiv_ids: list[str]) -> None:
        payload = {
            "new_count": len(arxiv_ids),
            "total_after_filter": len(arxiv_ids),
            "new_papers": [
                {
                    "arxiv_id": arxiv_id,
                    "title": f"Paper {index}",
                    "authors": ["Author"],
                    "categories": ["cs.AI"],
                    "published": "2026-07-13",
                    "primary_cat": "cs.AI",
                    "pdf_url": f"https://arxiv.org/pdf/{arxiv_id}",
                    "abs_url": f"https://arxiv.org/abs/{arxiv_id}",
                    "abstract": "Agent abstract.",
                }
                for index, arxiv_id in enumerate(arxiv_ids, start=1)
            ],
        }
        (root / "new_papers.json").write_text(
            json.dumps(payload, ensure_ascii=False),
            encoding="utf-8",
        )

    def test_merge_failure_does_not_persist_crawled_ids_and_successful_rerun_persists_them(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            merge_codes = iter([5, 0])

            def fake_run(cmd, **kwargs):
                script_name = Path(cmd[1]).name
                if script_name == "arxiv_daily_search.py":
                    self.write_batch(root, ["2401.00001"])
                    return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
                if script_name == "merge_papers.py":
                    return subprocess.CompletedProcess(
                        cmd,
                        next(merge_codes),
                        stdout="",
                        stderr="merge failed",
                    )
                if script_name == "enrich.py":
                    return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
                raise AssertionError(f"unexpected subprocess call: {cmd}")

            with patch.object(daily_pipeline, "BASE_DIR", root), patch.object(
                sys, "argv", ["daily_pipeline.py"]
            ), patch.object(daily_pipeline.subprocess, "run", side_effect=fake_run):
                with self.assertRaises(SystemExit) as first_exit:
                    daily_pipeline.main()
                self.assertEqual(5, first_exit.exception.code)
                self.assertFalse((root / "crawled_ids.txt").exists())

                daily_pipeline.main()

            saved_lines = (root / "crawled_ids.txt").read_text(encoding="utf-8").splitlines()
            self.assertEqual(["2401.00001"], saved_lines)

    def test_persist_crawled_ids_from_batch_is_idempotent_and_deduplicates_ids(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            crawled_path = root / "crawled_ids.txt"
            payload = {
                "new_papers": [
                    {"arxiv_id": "2401.00001"},
                    {"arxiv_id": "2401.00001"},
                    {"arxiv_id": "2401.00002"},
                    {"arxiv_id": ""},
                ]
            }

            first_saved = daily_pipeline.persist_crawled_ids_from_batch(payload, crawled_path)
            second_saved = daily_pipeline.persist_crawled_ids_from_batch(payload, crawled_path)

            self.assertEqual(2, first_saved)
            self.assertEqual(0, second_saved)
            self.assertEqual(
                ["2401.00001", "2401.00002"],
                crawled_path.read_text(encoding="utf-8").splitlines(),
            )

    def test_enrich_failure_returns_nonzero_skips_email_and_keeps_current_crawled_id_timing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            calls = []

            def fake_run(cmd, **kwargs):
                calls.append(Path(cmd[1]).name)
                script_name = Path(cmd[1]).name
                if script_name == "arxiv_daily_search.py":
                    self.write_batch(root, ["2401.00001"])
                    return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
                if script_name == "merge_papers.py":
                    return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
                if script_name == "enrich.py":
                    return subprocess.CompletedProcess(cmd, 9, stdout="", stderr="enrich failed")
                if script_name == "email_digest.py":
                    raise AssertionError("email should not run after enrich failure")
                raise AssertionError(f"unexpected subprocess call: {cmd}")

            stderr = io.StringIO()
            with patch.object(daily_pipeline, "BASE_DIR", root), patch.object(
                sys, "argv", ["daily_pipeline.py", "--email"]
            ), patch.object(daily_pipeline.subprocess, "run", side_effect=fake_run), patch(
                "sys.stderr", stderr
            ):
                with self.assertRaises(SystemExit) as exit_info:
                    daily_pipeline.main()

            self.assertEqual(9, exit_info.exception.code)
            self.assertEqual(
                ["arxiv_daily_search.py", "merge_papers.py", "enrich.py"],
                calls,
            )
            self.assertEqual(
                ["2401.00001"],
                (root / "crawled_ids.txt").read_text(encoding="utf-8").splitlines(),
            )
            self.assertIn('"stage": "enrich"', stderr.getvalue())

    def test_enrich_timeout_returns_nonzero_and_skips_email(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            calls = []

            def fake_run(cmd, **kwargs):
                calls.append(Path(cmd[1]).name)
                script_name = Path(cmd[1]).name
                if script_name == "arxiv_daily_search.py":
                    self.write_batch(root, ["2401.00001"])
                    return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
                if script_name == "merge_papers.py":
                    return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
                if script_name == "enrich.py":
                    raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout"))
                if script_name == "email_digest.py":
                    raise AssertionError("email should not run after enrich timeout")
                raise AssertionError(f"unexpected subprocess call: {cmd}")

            stderr = io.StringIO()
            with patch.object(daily_pipeline, "BASE_DIR", root), patch.object(
                sys, "argv", ["daily_pipeline.py", "--email"]
            ), patch.object(daily_pipeline.subprocess, "run", side_effect=fake_run), patch(
                "sys.stderr", stderr
            ):
                with self.assertRaises(SystemExit) as exit_info:
                    daily_pipeline.main()

            self.assertEqual(1, exit_info.exception.code)
            self.assertEqual(
                ["arxiv_daily_search.py", "merge_papers.py", "enrich.py"],
                calls,
            )
            self.assertIn('"stage": "enrich"', stderr.getvalue())

    def test_successful_email_pipeline_keeps_stage_order_and_returns_normally(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            calls = []

            def fake_run(cmd, **kwargs):
                script_name = Path(cmd[1]).name
                calls.append(script_name)
                if script_name == "arxiv_daily_search.py":
                    self.write_batch(root, ["2401.00001"])
                    return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
                if script_name == "merge_papers.py":
                    self.assertFalse((root / "crawled_ids.txt").exists())
                    return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
                if script_name == "enrich.py":
                    self.assertEqual(
                        ["2401.00001"],
                        (root / "crawled_ids.txt").read_text(encoding="utf-8").splitlines(),
                    )
                    return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
                if script_name == "email_digest.py":
                    self.assertEqual(
                        ["2401.00001"],
                        (root / "crawled_ids.txt").read_text(encoding="utf-8").splitlines(),
                    )
                    return subprocess.CompletedProcess(cmd, 0, stdout="email ok", stderr="")
                raise AssertionError(f"unexpected subprocess call: {cmd}")

            stderr = io.StringIO()
            with patch.object(daily_pipeline, "BASE_DIR", root), patch.object(
                sys, "argv", ["daily_pipeline.py", "--email"]
            ), patch.object(daily_pipeline.subprocess, "run", side_effect=fake_run), patch(
                "sys.stderr", stderr
            ):
                daily_pipeline.main()

            self.assertEqual(
                ["arxiv_daily_search.py", "merge_papers.py", "enrich.py", "email_digest.py"],
                calls,
            )
            self.assertEqual(
                ["2401.00001"],
                (root / "crawled_ids.txt").read_text(encoding="utf-8").splitlines(),
            )
            self.assertIn("email ok", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
