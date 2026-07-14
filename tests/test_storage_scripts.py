import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import classify_papers
import merge_papers


class StorageScriptTests(unittest.TestCase):
    def test_merge_uses_explicit_database_path_and_preserves_existing_fields(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "papers_database.json"
            new_path = root / "new_papers.json"
            db_path.write_text(
                json.dumps({
                    "papers": [{
                        "arxiv_id": "existing",
                        "title": "Existing",
                        "tags": ["Agent"],
                        "quality_score": 8.0,
                    }],
                    "total_count": 1,
                }),
                encoding="utf-8",
            )
            new_path.write_text(
                json.dumps({"new_papers": [{
                    "arxiv_id": "new",
                    "title": "New agent paper",
                    "abstract": "An agent method.",
                    "categories": ["cs.AI"],
                }]}),
                encoding="utf-8",
            )

            result = merge_papers.merge_papers(new_path=new_path, db_path=db_path)
            saved = json.loads(db_path.read_text(encoding="utf-8"))

            self.assertEqual(2, result["total_count"])
            self.assertEqual(["Agent"], saved["papers"][0]["tags"])
            self.assertEqual({"existing", "new"}, {p["arxiv_id"] for p in saved["papers"]})

    def test_classification_import_and_update_are_path_injectable(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "papers_database.json"
            categories_path = root / "papercatch_categories.json"
            db_path.write_text(
                json.dumps({"papers": [{"arxiv_id": "1", "title": "Agent benchmark", "abstract": ""}]}),
                encoding="utf-8",
            )
            categories_path.write_text(
                json.dumps([{"id": "llm", "label": "大语言模型"}, {"id": "benchmark", "label": "评测"}]),
                encoding="utf-8",
            )

            count = classify_papers.classify_database(db_path=db_path, categories_path=categories_path)
            saved = json.loads(db_path.read_text(encoding="utf-8"))

            self.assertEqual(1, count)
            self.assertEqual("llm", saved["papers"][0]["papercatch_cats"][0]["id"])

    def test_merge_accepts_non_arxiv_identity_and_deduplicates_by_paper_id(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "papers_database.json"
            new_path = root / "new_papers.json"
            db_path.write_text(
                json.dumps({
                    "papers": [{
                        "paper_id": "doi:10.1000/shared",
                        "arxiv_id": "doi:10.1000/shared",
                        "title": "Existing Crossref record",
                        "tags": ["manual"],
                    }]
                }),
                encoding="utf-8",
            )
            new_path.write_text(
                json.dumps({"new_papers": [{
                    "paper_id": "doi:10.1000/shared",
                    "doi": "10.1000/shared",
                    "title": "OpenAlex duplicate",
                }, {
                    "paper_id": "pmid:123",
                    "pmid": "123",
                    "title": "Biomedical paper",
                    "categories": [],
                }]}),
                encoding="utf-8",
            )

            merge_papers.merge_papers(new_path=new_path, db_path=db_path)
            saved = json.loads(db_path.read_text(encoding="utf-8"))

            self.assertEqual(2, len(saved["papers"]))
            self.assertEqual(["manual"], saved["papers"][0]["tags"])
            biomedical = next(p for p in saved["papers"] if p["paper_id"] == "pmid:123")
            self.assertEqual("pmid:123", biomedical["arxiv_id"])

    def test_merge_main_returns_nonzero_when_mark_pending_fails(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "papers_database.json"
            new_path = root / "new_papers.json"
            pending_path = root / "pending_enrichment.json"
            db_path.write_text(json.dumps({"papers": []}), encoding="utf-8")
            new_path.write_text(
                json.dumps({"new_papers": [{"arxiv_id": "2401.00001", "title": "Paper"}]}),
                encoding="utf-8",
            )

            real_merge = merge_papers.merge_papers
            with patch.object(merge_papers, "BASE_DIR", root), patch.object(
                merge_papers,
                "merge_papers",
                side_effect=lambda: real_merge(new_path=new_path, db_path=db_path),
            ), patch.object(
                merge_papers,
                "mark_pending",
                side_effect=RuntimeError("mark pending failed"),
            ):
                code = merge_papers.main()

            saved = json.loads(db_path.read_text(encoding="utf-8"))
            self.assertEqual(1, len(saved["papers"]))
            self.assertEqual(1, code)
            self.assertFalse(pending_path.exists())


if __name__ == "__main__":
    unittest.main()
