#!/usr/bin/env python3
"""Search arXiv by category and emit a structured JSON batch."""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from json_store import write_json_atomic


BASE_DIR = Path(__file__).resolve().parent
OUTPUT_JSON = BASE_DIR / "new_papers.json"

DEFAULT_CATS = ["cs.AI", "cs.CL", "cs.CV", "cs.LG"]
MAX_PER_CAT = 30
SS_DELAY = 1.05
ARXIV_DELAY = 3.5

NS = {"a": "http://www.w3.org/2005/Atom"}


@dataclass
class CategorySearchResult:
    total: int
    papers: list[dict]
    error: str | None = None


def resolve_output_path(output_value: str | Path) -> Path:
    output_path = Path(output_value).expanduser()
    if not output_path.is_absolute():
        output_path = Path.cwd() / output_path
    return output_path.resolve()


def build_runtime_paths(output_value: str | Path) -> dict[str, Path]:
    output_path = resolve_output_path(output_value)
    output_root = output_path.parent
    return {
        "output_path": output_path,
        "output_root": output_root,
        "crawled_ids_path": output_root / "crawled_ids.txt",
        "run_status_path": output_root / "run_status.json",
    }


def load_crawled_ids(path: str | Path) -> set[str]:
    target = Path(path).expanduser().resolve()
    if not target.exists():
        return set()
    with target.open("r", encoding="utf-8") as stream:
        return {line.strip() for line in stream if line.strip()}


def normalize_keywords(raw_keywords: str) -> list[str]:
    if not raw_keywords:
        return []
    normalized = []
    seen = set()
    for part in raw_keywords.replace("，", ",").split(","):
        keyword = part.strip()
        if not keyword or keyword in seen:
            continue
        seen.add(keyword)
        normalized.append(keyword)
    return normalized


def build_search_query(category: str, keywords: list[str]) -> str:
    if not keywords:
        return f"cat:{category}"
    keyword_query = " OR ".join(f"all:{keyword}" for keyword in keywords)
    return f"cat:{category} AND ({keyword_query})"


def build_category_url(category: str, keywords: list[str], max_results: int) -> str:
    params = {
        "search_query": build_search_query(category, keywords),
        "sortBy": "submittedDate",
        "sortOrder": "descending",
        "max_results": str(max_results),
    }
    return "https://export.arxiv.org/api/query?" + urllib.parse.urlencode(params)


def search_category(category: str, max_results: int, keywords: list[str] | None = None) -> CategorySearchResult:
    url = build_category_url(category, keywords or [], max_results)
    req = urllib.request.Request(url, headers={"User-Agent": "HermesAgent/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            data = response.read()
    except Exception as exc:
        error = str(getattr(exc, "reason", exc))
        print(f"  [WARN] arXiv {category}: {error}", file=sys.stderr)
        return CategorySearchResult(total=0, papers=[], error=error)

    root = ET.fromstring(data)
    entries = root.findall("a:entry", NS)
    total_el = root.find("{http://a9.com/-/spec/opensearch/1.1/}totalResults")
    total = int(total_el.text) if total_el is not None else len(entries)

    papers = []
    for entry in entries:
        title = entry.find("a:title", NS).text.strip().replace("\n", " ")
        raw_id = entry.find("a:id", NS).text.strip()
        full_id = raw_id.split("/abs/")[-1] if "/abs/" in raw_id else raw_id
        arxiv_id = full_id.split("v")[0]
        published = entry.find("a:published", NS).text[:10]
        updated = entry.find("a:updated", NS).text[:10]
        authors = [author.find("a:name", NS).text for author in entry.findall("a:author", NS)]
        summary = entry.find("a:summary", NS).text.strip().replace("\n", " ")
        categories = [category_el.get("term") for category_el in entry.findall("a:category", NS)]
        comment_el = entry.find("a:comment", NS)
        comment = comment_el.text.strip() if comment_el is not None else ""
        papers.append(
            {
                "arxiv_id": arxiv_id,
                "version": full_id[len(arxiv_id):] if full_id.startswith(arxiv_id) else "",
                "title": title,
                "authors": authors,
                "published": published,
                "updated": updated,
                "categories": categories,
                "primary_cat": categories[0] if categories else "",
                "abstract": summary[:800],
                "abstract_full": summary,
                "comment": comment,
                "pdf_url": f"https://arxiv.org/pdf/{arxiv_id}",
                "abs_url": f"https://arxiv.org/abs/{arxiv_id}",
            }
        )
    return CategorySearchResult(total=total, papers=papers)


def query_ss(arxiv_id: str) -> dict:
    url = (
        f"https://api.semanticscholar.org/graph/v1/paper/arXiv:{arxiv_id}"
        "?fields=title,citationCount,influentialCitationCount,"
        "publicationVenue,year,isOpenAccess,openAccessPdf,"
        "fieldsOfStudy,referenceCount,authors"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "HermesAgent/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            return json.loads(response.read())
    except Exception as exc:
        return {"error": str(exc), "citationCount": None, "influentialCitationCount": None}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Search arXiv for recent papers")
    parser.add_argument("--categories", default=",".join(DEFAULT_CATS))
    parser.add_argument("--keywords", default="")
    parser.add_argument("--max-per-cat", type=int, default=MAX_PER_CAT)
    parser.add_argument("--days", type=int, default=1, help="Only keep papers from the last N days; 0 disables the cutoff")
    parser.add_argument("--no-ss", action="store_true", help="Skip Semantic Scholar enrichment")
    parser.add_argument("--output", default=str(OUTPUT_JSON))
    return parser


def main(argv: list[str] | None = None) -> tuple[dict, dict[str, Path]]:
    args = build_parser().parse_args(argv)
    runtime_paths = build_runtime_paths(args.output)
    categories = [category.strip() for category in args.categories.split(",") if category.strip()]
    keywords = normalize_keywords(args.keywords)
    crawled_ids = load_crawled_ids(runtime_paths["crawled_ids_path"])

    cutoff = None
    if args.days > 0:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=args.days)).strftime("%Y-%m-%d")

    all_papers: dict[str, dict] = {}
    total_all = 0
    failed_categories = []
    category_errors = {}

    for index, category in enumerate(categories):
        print(f"[SEARCH] {category} ...", file=sys.stderr)
        result = search_category(category, max_results=args.max_per_cat, keywords=keywords)
        if result.error:
            failed_categories.append(category)
            category_errors[category] = result.error
        else:
            total_all += result.total
            new_count = 0
            for paper in result.papers:
                paper_id = paper["arxiv_id"]
                if paper_id not in all_papers:
                    all_papers[paper_id] = paper
                    if paper_id not in crawled_ids:
                        new_count += 1
                else:
                    for existing_category in paper["categories"]:
                        if existing_category not in all_papers[paper_id]["categories"]:
                            all_papers[paper_id]["categories"].append(existing_category)
            print(
                f"        {result.total} total, {len(result.papers)} fetched, {new_count} new",
                file=sys.stderr,
            )
        if index < len(categories) - 1:
            time.sleep(ARXIV_DELAY)

    if failed_categories and len(failed_categories) == len(categories):
        details = "; ".join(f"{category}: {category_errors[category]}" for category in failed_categories)
        raise RuntimeError(f"All arXiv category requests failed: {details}")

    if cutoff:
        all_papers = {
            paper_id: paper
            for paper_id, paper in all_papers.items()
            if paper["published"] >= cutoff
        }

    new_ids = [paper_id for paper_id in all_papers if paper_id not in crawled_ids]
    paper_list = sorted(
        all_papers.values(),
        key=lambda paper: (paper["published"], paper["title"]),
        reverse=True,
    )

    print(f"[SUMMARY] {len(all_papers)} papers ({len(new_ids)} new)", file=sys.stderr)

    if not args.no_ss and new_ids:
        print(f"[ENRICH] Semantic Scholar for {len(new_ids)} new papers...", file=sys.stderr)
        for index, paper_id in enumerate(new_ids):
            paper = all_papers[paper_id]
            ss = query_ss(paper_id)
            paper["citations"] = ss.get("citationCount")
            paper["influential_citations"] = ss.get("influentialCitationCount")
            paper["reference_count"] = ss.get("referenceCount")
            paper["year"] = ss.get("year")
            paper["venue"] = ss.get("publicationVenue", {}).get("name") if ss.get("publicationVenue") else None
            paper["is_open_access"] = ss.get("isOpenAccess")
            paper["fields_of_study"] = ss.get("fieldsOfStudy", [])
            paper["ss_error"] = ss.get("error")
            if (index + 1) % 10 == 0:
                print(f"        {index + 1}/{len(new_ids)} ...", file=sys.stderr)
            time.sleep(SS_DELAY)

    result = {
        "searched_at": datetime.now(timezone.utc).isoformat(),
        "categories": categories,
        "keywords": keywords,
        "total_found": total_all,
        "total_after_filter": len(all_papers),
        "new_count": len(new_ids),
        "cutoff_date": cutoff,
        "failed_categories": failed_categories,
        "category_errors": category_errors,
        "new_papers": [all_papers[paper_id] for paper_id in new_ids],
        "all_papers": paper_list,
    }

    write_json_atomic(runtime_paths["output_path"], result)
    print(
        f"[OUTPUT] {runtime_paths['output_path']} ({len(new_ids)} new / {len(all_papers)} total)",
        file=sys.stderr,
    )

    if new_ids:
        print("\nLLM_SUMMARIZATION_REQUIRED")
        print(f"new_count={len(new_ids)}")
        print(f"output={runtime_paths['output_path']}")
    else:
        print("\nNo new papers today.")

    return result, runtime_paths


def resolve_requested_output(argv: list[str] | None = None) -> str:
    raw_args = list(sys.argv[1:] if argv is None else argv)
    for index, arg in enumerate(raw_args):
        if arg == "--output" and index + 1 < len(raw_args):
            return raw_args[index + 1]
        if arg.startswith("--output="):
            return arg.split("=", 1)[1]
    return str(OUTPUT_JSON)


def run_cli(argv: list[str] | None = None) -> int:
    import traceback

    runtime_paths = build_runtime_paths(resolve_requested_output(argv))
    try:
        result, runtime_paths = main(argv)
        status = {
            "status": "ok",
            "new_count": result.get("new_count", 0),
            "total_count": result.get("total_after_filter", 0),
            "output_file": str(runtime_paths["output_path"]),
        }
        if result.get("failed_categories"):
            status["failed_categories"] = result["failed_categories"]
            status["category_errors"] = result.get("category_errors", {})
        write_json_atomic(runtime_paths["run_status_path"], status)
        return 0
    except Exception as exc:
        write_json_atomic(
            runtime_paths["run_status_path"],
            {"status": "error", "error": str(exc), "traceback": traceback.format_exc()},
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(run_cli())
