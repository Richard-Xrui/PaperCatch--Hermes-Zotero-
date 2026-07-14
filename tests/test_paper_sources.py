from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import daily_pipeline
import paper_sources


class PaperSourceNormalizationTests(unittest.TestCase):
    def test_normalize_keywords_deduplicates_chinese_delimiters(self):
        self.assertEqual(
            ["large language model", "agent", "memory"],
            paper_sources.normalize_keywords("large language model, agent，memory；agent"),
        )

    def test_deduplicate_prefers_doi_and_preserves_all_sources(self):
        first = paper_sources._paper(
            source="openalex",
            title="A shared paper",
            doi="https://doi.org/10.1000/Test",
            abstract="short",
            landing_url="https://example.test/landing",
        )
        second = paper_sources._paper(
            source="crossref",
            title="A shared paper",
            doi="10.1000/test",
            abstract="longer abstract",
            pdf_url="https://example.test/paper.pdf",
            open_access=True,
        )
        result = paper_sources.deduplicate_papers([first, second])
        self.assertEqual(1, len(result))
        self.assertEqual(["openalex", "crossref"], result[0]["sources"])
        self.assertTrue(result[0]["open_access"])
        self.assertEqual("https://example.test/paper.pdf", result[0]["pdf_url"])


class PaperSourceAdapterTests(unittest.TestCase):
    def test_openalex_adapter_maps_oa_pdf_and_author(self):
        payload = {
            "results": [{
                "id": "https://openalex.org/W123",
                "doi": "https://doi.org/10.1000/demo",
                "title": "Open paper",
                "publication_date": "2026-07-13",
                "authorships": [{"author": {"display_name": "Ada Lovelace"}}],
                "best_oa_location": {
                    "landing_page_url": "https://example.test/article",
                    "pdf_url": "https://example.test/article.pdf",
                },
                "open_access": {"is_oa": True},
                "concepts": [{"display_name": "Machine learning"}],
            }]
        }
        rows = paper_sources.search_openalex(["agent"], 5, 0, fetcher=lambda _: payload)
        self.assertEqual(1, len(rows))
        self.assertEqual("doi:10.1000/demo", rows[0]["paper_id"])
        self.assertEqual(["Ada Lovelace"], rows[0]["authors"])
        self.assertEqual("https://example.test/article.pdf", rows[0]["pdf_url"])
        self.assertTrue(rows[0]["open_access"])

    def test_semantic_scholar_adapter_maps_external_ids_and_oa_pdf(self):
        payload = {"data": [{
            "paperId": "S2-1",
            "title": "Semantic paper",
            "authors": [{"name": "Alan Turing"}],
            "abstract": "A semantic abstract.",
            "publicationDate": "2026-07-13",
            "externalIds": {"DOI": "10.1000/s2", "ArXiv": "2607.00002"},
            "openAccessPdf": {"url": "https://example.test/s2.pdf"},
            "url": "https://semanticscholar.org/paper/S2-1",
            "citationCount": 7,
        }]}
        rows = paper_sources.search_semantic_scholar(["agent"], 5, 0, fetcher=lambda _: payload)
        self.assertEqual("doi:10.1000/s2", rows[0]["paper_id"])
        self.assertEqual("2607.00002", rows[0]["arxiv_id"])
        self.assertTrue(rows[0]["open_access"])
        self.assertEqual(7, rows[0]["citations"])

    def test_europe_pmc_adapter_maps_pmid_and_pdf(self):
        payload = {"resultList": {"result": [{
            "pmid": "12345678",
            "title": "Clinical paper",
            "authorString": "Ada Lovelace, Alan Turing",
            "firstPublicationDate": "2026-07-13",
            "isOpenAccess": True,
            "fullTextUrlList": {"fullTextUrl": [{
                "documentStyle": "pdf",
                "url": "https://europepmc.test/paper.pdf",
            }]},
        }]}}
        rows = paper_sources.search_europe_pmc(["oncology"], 5, 0, fetcher=lambda _: payload)
        self.assertEqual("pmid:12345678", rows[0]["paper_id"])
        self.assertEqual(["Ada Lovelace", "Alan Turing"], rows[0]["authors"])
        self.assertTrue(rows[0]["open_access"])

    def test_crossref_adapter_keeps_metadata_without_pdf_as_not_oa(self):
        payload = {"message": {"items": [{
            "DOI": "10.1000/no-pdf",
            "title": ["Metadata only"],
            "author": [{"given": "Grace", "family": "Hopper"}],
            "issued": {"date-parts": [[2026, 7, 13]]},
            "URL": "https://doi.org/10.1000/no-pdf",
        }]}}
        rows = paper_sources.search_crossref(["agent"], 5, 0, fetcher=lambda _: payload)
        self.assertEqual(1, len(rows))
        self.assertFalse(rows[0]["open_access"])
        self.assertEqual("", rows[0]["pdf_url"])

    def test_crossref_pdf_link_is_not_claimed_as_open_access(self):
        payload = {"message": {"items": [{
            "DOI": "10.1000/maybe-restricted",
            "title": ["Publisher link"],
            "link": [{"URL": "https://publisher.test/file.pdf", "content-type": "application/pdf"}],
        }]}}
        rows = paper_sources.search_crossref(["agent"], 5, 0, fetcher=lambda _: payload)
        self.assertEqual("https://publisher.test/file.pdf", rows[0]["pdf_url"])
        self.assertFalse(rows[0]["open_access"])

    def test_arxiv_adapter_can_be_fed_with_mock_atom(self):
        atom = b'''<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">
          <entry><id>https://arxiv.org/abs/2607.00001v1</id>
          <published>2026-07-13T00:00:00Z</published><updated>2026-07-13T00:00:00Z</updated>
          <title>Agent paper</title><summary>Agent summary.</summary>
          <author><name>Ada</name></author><category term="cs.AI" /></entry></feed>'''
        rows = paper_sources.search_arxiv(["agent"], 5, 0, fetcher=lambda _: atom)
        self.assertEqual("2607.00001", rows[0]["arxiv_id"])
        self.assertTrue(rows[0]["open_access"])

    def test_search_all_sources_degrades_and_deduplicates(self):
        shared = paper_sources._paper(
            source="openalex",
            title="Shared",
            doi="10.1000/shared",
        )
        with patch.object(paper_sources, "SOURCE_SEARCHERS", {
            "openalex": lambda *args, **kwargs: [shared],
            "crossref": lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("offline")),
        }):
            result = paper_sources.search_all_sources(
                ["agent"], sources=["openalex", "crossref"], max_results=5
            )
        self.assertEqual(1, len(result["papers"]))
        self.assertEqual(["crossref"], result["failed_sources"])
        self.assertEqual("offline", result["source_errors"]["crossref"])

    def test_search_all_sources_balances_sources_before_global_limit(self):
        def rows(source, count):
            return [
                paper_sources._paper(
                    source=source,
                    title=f"{source} paper {index}",
                    published=f"2026-07-{10 + index:02d}",
                )
                for index in range(count)
            ]

        calls = {}

        def searcher(source):
            def run(keywords, limit, days, fetcher=None):
                calls[source] = limit
                return rows(source, limit)
            return run

        with patch.object(paper_sources, "SOURCE_SEARCHERS", {
            "arxiv": searcher("arxiv"),
            "openalex": searcher("openalex"),
        }):
            result = paper_sources.search_all_sources(
                ["agent"], sources=["arxiv", "openalex"], max_results=4
            )

        self.assertEqual({"arxiv": 5, "openalex": 5}, calls)
        self.assertEqual(4, len(result["papers"]))
        self.assertEqual({"arxiv", "openalex"}, {p["source"] for p in result["papers"]})


class PaperSourceCliTests(unittest.TestCase):
    def test_cli_reuses_persisted_doi_identity_across_batches(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output = root / "batch" / "new_papers.json"
            first_paper = paper_sources._paper(
                source="openalex",
                title="Cross-batch DOI paper",
                doi="10.1000/oa-cross-batch",
                openalex_id="https://openalex.org/W999",
                landing_url="https://example.test/landing",
            )
            second_paper = paper_sources._paper(
                source="crossref",
                title="Cross-batch DOI paper",
                doi="https://doi.org/10.1000/oa-cross-batch",
                landing_url="https://doi.org/10.1000/oa-cross-batch",
            )
            payload = {
                "papers": paper_sources.deduplicate_papers([first_paper, second_paper]),
                "sources": ["openalex", "crossref"],
                "source_counts": {"openalex": 1, "crossref": 1},
                "source_errors": {},
                "failed_sources": [],
                "keywords": ["agent"],
            }

            with patch.object(paper_sources, "search_all_sources", return_value=payload) as search_mock, patch.object(
                paper_sources.urllib.request,
                "urlopen",
                side_effect=AssertionError("real network must not be used"),
            ):
                first_code = paper_sources.run_cli([
                    "--keywords", "agent", "--sources", "openalex,crossref", "--output", str(output)
                ])
                self.assertEqual(0, first_code)
                self.assertEqual(1, search_mock.call_count)

                first_batch = json.loads(output.read_text(encoding="utf-8"))
                self.assertEqual(1, first_batch["new_count"])
                self.assertEqual("doi:10.1000/oa-cross-batch", first_batch["new_papers"][0]["paper_id"])
                self.assertEqual(
                    first_batch["new_papers"][0]["paper_id"],
                    first_batch["new_papers"][0]["arxiv_id"],
                )

                persisted = daily_pipeline.persist_crawled_ids_from_batch(
                    first_batch,
                    output.parent / "crawled_ids.txt",
                )
                self.assertEqual(1, persisted)
                self.assertEqual(
                    ["doi:10.1000/oa-cross-batch"],
                    (output.parent / "crawled_ids.txt").read_text(encoding="utf-8").splitlines(),
                )

                second_code = paper_sources.run_cli([
                    "--keywords", "agent", "--sources", "openalex,crossref", "--output", str(output)
                ])
                self.assertEqual(0, second_code)
                self.assertEqual(2, search_mock.call_count)

            second_batch = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(1, second_batch["total_count"])
            self.assertEqual(0, second_batch["new_count"])
            self.assertEqual([], second_batch["new_papers"])
            self.assertEqual("doi:10.1000/oa-cross-batch", second_batch["all_papers"][0]["paper_id"])
            self.assertEqual(
                second_batch["all_papers"][0]["paper_id"],
                second_batch["all_papers"][0]["arxiv_id"],
            )

    def test_cli_reuses_persisted_pmid_identity_without_doi(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output = root / "batch" / "new_papers.json"
            paper = paper_sources._paper(
                source="europe_pmc",
                title="Clinical follow-up paper",
                pmid="12345678",
                open_access=True,
                pdf_url="https://example.test/clinical.pdf",
                landing_url="https://europepmc.org/article/MED/12345678",
            )
            payload = {
                "papers": [paper],
                "sources": ["europe_pmc"],
                "source_counts": {"europe_pmc": 1},
                "source_errors": {},
                "failed_sources": [],
                "keywords": ["clinical"],
            }

            with patch.object(paper_sources, "search_all_sources", return_value=payload) as search_mock:
                first_code = paper_sources.run_cli([
                    "--keywords", "clinical", "--sources", "europe_pmc", "--output", str(output)
                ])
                self.assertEqual(0, first_code)
                first_batch = json.loads(output.read_text(encoding="utf-8"))
                self.assertEqual("pmid:12345678", first_batch["new_papers"][0]["paper_id"])
                self.assertEqual("pmid:12345678", first_batch["new_papers"][0]["arxiv_id"])

                persisted = daily_pipeline.persist_crawled_ids_from_batch(
                    first_batch,
                    output.parent / "crawled_ids.txt",
                )
                self.assertEqual(1, persisted)

                second_code = paper_sources.run_cli([
                    "--keywords", "clinical", "--sources", "europe_pmc", "--output", str(output)
                ])
                self.assertEqual(0, second_code)
                self.assertEqual(2, search_mock.call_count)

            second_batch = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(0, second_batch["new_count"])
            self.assertEqual([], second_batch["new_papers"])

    def test_cli_writes_new_papers_and_status_without_network(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output = root / "batch" / "result.json"
            payload = {
                "papers": [paper_sources._paper(source="openalex", title="CLI paper")],
                "sources": ["openalex"],
                "source_counts": {"openalex": 1},
                "source_errors": {},
                "failed_sources": [],
                "keywords": ["agent"],
            }
            with patch.object(paper_sources, "search_all_sources", return_value=payload):
                code = paper_sources.run_cli([
                    "--keywords", "agent", "--sources", "openalex", "--output", str(output)
                ])
            self.assertEqual(0, code)
            data = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(1, data["new_count"])
            self.assertEqual("ok", json.loads((output.parent / "run_status.json").read_text(encoding="utf-8"))["status"])

    def test_cli_fails_when_every_configured_source_fails(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output = root / "batch" / "result.json"
            payload = {
                "papers": [],
                "sources": ["openalex", "crossref"],
                "source_counts": {"openalex": 0, "crossref": 0},
                "source_errors": {"openalex": "offline", "crossref": "timeout"},
                "failed_sources": ["crossref", "openalex"],
                "keywords": ["agent"],
            }
            with patch.object(paper_sources, "search_all_sources", return_value=payload):
                code = paper_sources.run_cli([
                    "--keywords", "agent", "--sources", "openalex,crossref", "--output", str(output)
                ])
            self.assertEqual(1, code)
            self.assertFalse(output.exists())
            status = json.loads((output.parent / "run_status.json").read_text(encoding="utf-8"))
            self.assertEqual("error", status["status"])
            self.assertEqual(payload["source_errors"], status["source_errors"])


if __name__ == "__main__":
    unittest.main()
