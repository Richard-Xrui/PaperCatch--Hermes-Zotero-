#!/usr/bin/env python3
"""Daily PaperCatch pipeline: search configured sources, merge, and digest."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DAYS = 0
DEFAULT_MAX_PER_CAT = 25
DEFAULT_CATEGORIES = ["cs.AI", "cs.CL", "cs.CV", "cs.LG"]


def load_search_config(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as stream:
        data = json.load(stream)
    return data if isinstance(data, dict) else {}


def resolve_search_parameters(args: argparse.Namespace) -> tuple[int, int, list[str], str]:
    search_config = load_search_config(BASE_DIR / "search_config.json")
    days = args.days if args.days is not None else int(search_config.get("days", DEFAULT_DAYS))
    max_per_cat = (
        args.max_per_cat
        if args.max_per_cat is not None
        else int(search_config.get("max_per_cat", DEFAULT_MAX_PER_CAT))
    )
    categories = search_config.get("categories") or DEFAULT_CATEGORIES
    keywords = search_config.get("keywords", "") or ""
    return days, max_per_cat, categories, keywords


def resolve_sources(args: argparse.Namespace) -> list[str]:
    """Return explicitly configured sources, preserving old arXiv-only configs."""

    config = load_search_config(BASE_DIR / "search_config.json")
    raw = args.sources if getattr(args, "sources", None) else config.get("sources", [])
    if isinstance(raw, str):
        return [item.strip().lower() for item in raw.replace("，", ",").split(",") if item.strip()]
    if isinstance(raw, list):
        return [str(item).strip().lower() for item in raw if str(item).strip()]
    return []


def extract_new_arxiv_ids(data: dict) -> list[str]:
    ordered_ids = []
    seen = set()
    for paper in data.get("new_papers", []):
        arxiv_id = str(paper.get("paper_id") or paper.get("arxiv_id", "")).strip()
        if not arxiv_id or arxiv_id in seen:
            continue
        seen.add(arxiv_id)
        ordered_ids.append(arxiv_id)
    return ordered_ids


def load_crawled_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    with path.open("r", encoding="utf-8") as stream:
        return {line.strip() for line in stream if line.strip()}


def persist_crawled_ids(path: Path, arxiv_ids: list[str]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = load_crawled_ids(path)
    pending = []
    for arxiv_id in arxiv_ids:
        if not arxiv_id or arxiv_id in existing:
            continue
        existing.add(arxiv_id)
        pending.append(arxiv_id)
    if not pending:
        return 0
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        for arxiv_id in pending:
            stream.write(arxiv_id + "\n")
    return len(pending)


def persist_crawled_ids_from_batch(data: dict, crawled_path: Path) -> int:
    return persist_crawled_ids(crawled_path, extract_new_arxiv_ids(data))


def _stage_error(stage: str, status: str, **extra) -> None:
    payload = {"stage": stage, "status": status}
    payload.update(extra)
    print(f"STAGE_ERROR: {json.dumps(payload, ensure_ascii=False)}", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the PaperCatch daily pipeline")
    parser.add_argument("--days", type=int, default=None, help="days passed to arxiv_daily_search.py")
    parser.add_argument("--max-per-cat", type=int, default=None, help="max papers per category")
    parser.add_argument("--sources", default=None, help="comma-separated public sources; enables multi-source mode")
    parser.add_argument("--email", action="store_true", help="send email digest after merging")
    parser.add_argument("--email-limit", type=int, default=10)
    args = parser.parse_args()
    days, max_per_cat, categories, keywords = resolve_search_parameters(args)
    sources = resolve_sources(args)
    multi_source = bool(sources and any(source != "arxiv" for source in sources))

    print(
        "[PIPELINE] Searching configured public sources..." if multi_source else "[PIPELINE] Searching arXiv...",
        file=sys.stderr,
    )
    search_env = os.environ.copy()
    search_env["PAPERCATCH_SEARCH_CATEGORIES"] = json.dumps(categories, ensure_ascii=False)
    search_env["PAPERCATCH_SEARCH_KEYWORDS"] = keywords
    if multi_source:
        search_cmd = [
            sys.executable,
            str(BASE_DIR / "paper_sources.py"),
            "--days",
            str(days),
            "--max-results",
            str(min(100, max_per_cat * max(1, len(categories)))),
            "--sources",
            ",".join(sources),
            "--keywords",
            keywords,
        ]
    else:
        search_cmd = [
            sys.executable,
            str(BASE_DIR / "arxiv_daily_search.py"),
            "--days",
            str(days),
            "--max-per-cat",
            str(max_per_cat),
            "--categories",
            ",".join(categories),
            "--keywords",
            keywords,
        ]
    if sources:
        search_env["PAPERCATCH_SEARCH_SOURCES"] = json.dumps(sources, ensure_ascii=False)
    try:
        search = subprocess.run(
            search_cmd,
            cwd=str(BASE_DIR),
            capture_output=True,
            text=True,
            env=search_env,
            timeout=300,
        )
    except subprocess.TimeoutExpired as exc:
        _stage_error("search", "timeout", timeout=getattr(exc, "timeout", None))
        sys.exit(1)
    if search.returncode != 0:
        _stage_error("search", "failed", returncode=search.returncode, stderr=(search.stderr or "")[-800:])
        sys.exit(search.returncode)

    new_json = BASE_DIR / "new_papers.json"
    if not new_json.exists():
        print("NO_NEW_PAPERS")
        return

    with new_json.open("r", encoding="utf-8") as stream:
        data = json.load(stream)
    new_count = int(data.get("new_count", 0))
    if new_count == 0:
        print("NO_NEW_PAPERS")
        return

    print(f"[PIPELINE] {new_count} new papers, merging...", file=sys.stderr)
    try:
        merge = subprocess.run(
            [sys.executable, str(BASE_DIR / "merge_papers.py")],
            cwd=str(BASE_DIR),
            capture_output=True,
            text=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired as exc:
        _stage_error("merge", "timeout", timeout=getattr(exc, "timeout", None))
        sys.exit(1)
    if merge.returncode != 0:
        _stage_error("merge", "failed", returncode=merge.returncode, stderr=(merge.stderr or "")[-800:])
        sys.exit(merge.returncode)

    persisted_ids = persist_crawled_ids_from_batch(data, new_json.parent / "crawled_ids.txt")
    if persisted_ids:
        print(f"[PIPELINE] Persisted {persisted_ids} crawled ids", file=sys.stderr)

    print("[PIPELINE] Local enrich (tags + scores)...", file=sys.stderr)
    try:
        enrich = subprocess.run(
            [sys.executable, str(BASE_DIR / "enrich.py")],
            cwd=str(BASE_DIR),
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired as exc:
        _stage_error("enrich", "timeout", timeout=getattr(exc, "timeout", None))
        sys.exit(1)
    if enrich.returncode != 0:
        _stage_error("enrich", "failed", returncode=enrich.returncode, stderr=(enrich.stderr or "")[-800:])
        sys.exit(enrich.returncode)

    print_agent_context(data)

    if args.email:
        print("[PIPELINE] Sending email digest...", file=sys.stderr)
        try:
            email = subprocess.run(
                [
                    sys.executable,
                    str(BASE_DIR / "email_digest.py"),
                    "--source",
                    "new",
                    "--limit",
                    str(args.email_limit),
                ],
                cwd=str(BASE_DIR),
                capture_output=True,
                text=True,
                timeout=120,
            )
        except subprocess.TimeoutExpired as exc:
            _stage_error("email", "timeout", timeout=getattr(exc, "timeout", None))
            sys.exit(1)
        if email.stdout:
            print(email.stdout, file=sys.stderr)
        if email.returncode != 0:
            _stage_error("email", "failed", returncode=email.returncode, stderr=(email.stderr or "")[-800:])
            sys.exit(email.returncode)


def print_agent_context(data: dict) -> None:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    new_papers = data.get("new_papers", [])
    print(f"DATE: {today}")
    print(f"NEW_COUNT: {data.get('new_count', 0)}")
    print(f"TOTAL_AFTER_FILTER: {data.get('total_after_filter', 0)}")
    print()

    categories = {}
    for paper in new_papers:
        for category in paper.get("categories", []):
            categories[category] = categories.get(category, 0) + 1
    print("CATEGORY_STATS:", json.dumps(categories, ensure_ascii=False))
    print()

    print("=== NEW_PAPERS ===")
    for index, paper in enumerate(new_papers):
        print(f"--- Paper {index + 1}/{len(new_papers)} ---")
        print(f"arxiv_id: {paper.get('arxiv_id', '')}")
        print(f"title: {paper.get('title', '')}")
        print(f"authors: {'; '.join(paper.get('authors', [])[:8])}")
        print(f"published: {paper.get('published', '')}")
        print(f"categories: {', '.join(paper.get('categories', []))}")
        print(f"primary_cat: {paper.get('primary_cat', '')}")
        print(f"citations: {paper.get('citations', 'N/A')}")
        print(f"influential_citations: {paper.get('influential_citations', 'N/A')}")
        print(f"venue: {paper.get('venue', 'N/A')}")
        print(f"fields_of_study: {json.dumps(paper.get('fields_of_study', []), ensure_ascii=False)}")
        print(f"is_open_access: {paper.get('is_open_access', False)}")
        print(f"pdf_url: {paper.get('pdf_url', '')}")
        print(f"abs_url: {paper.get('abs_url', '')}")
        print(f"abstract: {paper.get('abstract_full', paper.get('abstract', ''))}")
        print(f"comment: {paper.get('comment', '')}")
        print()
    print("=== END ===")
    print()
    print(
        "INSTRUCTIONS: These papers have been merged into papers_database.json. "
        "If an LLM agent is available, generate abstract_cn, quality_score, "
        "quality_signals, and tags, then keep the top papers for the digest."
    )


if __name__ == "__main__":
    main()
