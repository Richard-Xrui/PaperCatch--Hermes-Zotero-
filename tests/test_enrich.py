import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import enrich
import json_store


class EnrichmentTests(unittest.TestCase):
    def _write_database(self, path: Path, papers) -> None:
        path.write_text(
            json.dumps({"papers": papers, "total_count": len(papers)}, ensure_ascii=False),
            encoding="utf-8",
        )

    def test_local_enrich_accepts_temp_path_and_empty_tags_are_idempotent(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "papers_database.json"
            paper = {
                "arxiv_id": "blank",
                "title": "A paper without a matching topic",
                "abstract": "A short abstract.",
                "tags": [],
            }
            self._write_database(path, [paper])

            with patch.object(json_store, "write_json_atomic", wraps=json_store.write_json_atomic) as writer:
                first = enrich.local_enrich(db_path=path)
                first_calls = writer.call_count
                first_bytes = path.read_bytes()
                second = enrich.local_enrich(db_path=path)

            self.assertGreater(first, 0)
            self.assertEqual(0, second)
            self.assertEqual(first_bytes, path.read_bytes())
            self.assertEqual(first_calls, writer.call_count)

    def test_non_force_preserves_existing_manual_or_llm_enrichment(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "papers_database.json"
            paper = {
                "arxiv_id": "curated",
                "title": "Agent planning with a large language model",
                "abstract": "An agent uses an LLM.",
                "tags": ["Human curated"],
                "quality_score": 9.7,
                "quality_signals": {"source": "LLM", "reviewed": True},
            }
            self._write_database(path, [paper])
            original = path.read_bytes()

            with patch.object(json_store, "write_json_atomic", wraps=json_store.write_json_atomic) as writer:
                updated = enrich.local_enrich(db_path=path)

            self.assertEqual(0, updated)
            self.assertEqual(original, path.read_bytes())
            writer.assert_not_called()

    def test_non_force_fills_only_missing_quality_fields(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "papers_database.json"
            papers = [
                {
                    "arxiv_id": "missing-score",
                    "title": "Agent planning",
                    "abstract": "An agent learns a policy.",
                    "tags": ["Human curated"],
                    "quality_signals": {"source": "manual"},
                },
                {
                    "arxiv_id": "missing-signals",
                    "title": "A plain paper",
                    "abstract": "A short abstract.",
                    "quality_score": 9.2,
                },
            ]
            self._write_database(path, papers)

            updated = enrich.local_enrich(db_path=path)
            saved = json.loads(path.read_text(encoding="utf-8"))["papers"]

            self.assertGreaterEqual(updated, 1)
            self.assertEqual(["Human curated"], saved[0]["tags"])
            self.assertEqual({"source": "manual"}, saved[0]["quality_signals"])
            self.assertEqual(4.5, saved[0]["quality_score"])
            self.assertEqual([], saved[1]["tags"])
            self.assertEqual(9.2, saved[1]["quality_score"])
            self.assertEqual("medium", saved[1]["quality_signals"]["innovation"])

    def test_force_recomputes_all_local_enrichment_fields(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "papers_database.json"
            paper = {
                "arxiv_id": "force",
                "title": "Agent planning with a large language model",
                "abstract": "An agent uses an LLM.",
                "tags": ["Human curated"],
                "quality_score": 9.7,
                "quality_signals": {"source": "LLM"},
            }
            self._write_database(path, [paper])

            updated = enrich.local_enrich(force=True, db_path=path)
            saved = json.loads(path.read_text(encoding="utf-8"))["papers"][0]

            self.assertEqual(2, updated)
            self.assertEqual(enrich.extract_tags(paper), saved["tags"])
            expected_score, expected_signals = enrich.compute_quality(paper)
            self.assertEqual(expected_score, saved["quality_score"])
            self.assertEqual(expected_signals, saved["quality_signals"])

    def test_placeholder_empty_tags_are_recomputed_when_keywords_match(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "papers_database.json"
            self._write_database(
                path,
                [
                    {
                        "arxiv_id": "agent",
                        "title": "Agent planning",
                        "abstract": "An agent learns a policy.",
                        "tags": [],
                        "quality_score": None,
                        "quality_signals": {},
                    }
                ],
            )

            updated = enrich.local_enrich(db_path=path)
            saved = json.loads(path.read_text(encoding="utf-8"))

            self.assertGreaterEqual(updated, 1)
            self.assertIn("Agent", saved["papers"][0]["tags"])

    def test_empty_tags_with_existing_manual_quality_are_preserved(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "papers_database.json"
            paper = {
                "arxiv_id": "curated-empty",
                "title": "Agent planning",
                "abstract": "An agent learns a policy.",
                "tags": [],
                "quality_score": 9.4,
                "quality_signals": {"source": "manual", "reviewed": True},
            }
            self._write_database(path, [paper])
            original = path.read_bytes()

            with patch.object(json_store, "write_json_atomic", wraps=json_store.write_json_atomic) as writer:
                updated = enrich.local_enrich(db_path=path)

            self.assertEqual(0, updated)
            self.assertEqual(original, path.read_bytes())
            writer.assert_not_called()

    def test_malformed_database_is_not_replaced(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "papers_database.json"
            original = b'{"papers": ['
            path.write_bytes(original)

            with self.assertRaises(json_store.JsonStoreError):
                enrich.local_enrich(db_path=path)

            self.assertEqual(original, path.read_bytes())


if __name__ == "__main__":
    unittest.main()
