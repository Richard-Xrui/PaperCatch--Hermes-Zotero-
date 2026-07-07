#!/usr/bin/env python3
"""Daily PaperCatch pipeline: search arXiv, merge results, and optionally email a digest."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the PaperCatch daily pipeline")
    parser.add_argument("--days", default="0", help="days passed to arxiv_daily_search.py")
    parser.add_argument("--max-per-cat", default="25", help="max papers per category")
    parser.add_argument("--email", action="store_true", help="send email digest after merging")
    parser.add_argument("--email-limit", type=int, default=10)
    args = parser.parse_args()

    # Load search config (overrides defaults, CLI args take precedence)
    search_config_path = BASE_DIR / "search_config.json"
    if search_config_path.exists():
        with open(search_config_path, "r", encoding="utf-8") as f:
            sc = json.load(f)
        if not args.days or args.days == "0":
            args.days = str(sc.get("days", args.days))
        if not args.max_per_cat or args.max_per_cat == "25":
            args.max_per_cat = str(sc.get("max_per_cat", args.max_per_cat))
        categories = sc.get("categories", [])
        keywords = sc.get("keywords", "")
    else:
        categories = []
        keywords = ""

    print("[PIPELINE] Searching arXiv...", file=sys.stderr)
    search = subprocess.run(
        [
            sys.executable,
            str(BASE_DIR / "arxiv_daily_search.py"),
            "--days",
            str(args.days),
            "--max-per-cat",
            str(args.max_per_cat),
        ],
        cwd=str(BASE_DIR),
        capture_output=True,
        text=True,
        timeout=300,
    )
    if search.returncode != 0:
        print(f"SEARCH_ERROR: {search.stderr[-800:]}", file=sys.stderr)
        print("ERROR: arXiv search failed")
        sys.exit(search.returncode)

    new_json = BASE_DIR / "new_papers.json"
    if not new_json.exists():
        print("NO_NEW_PAPERS")
        return

    with open(new_json, "r", encoding="utf-8") as f:
        data = json.load(f)
    new_count = int(data.get("new_count", 0))
    if new_count == 0:
        print("NO_NEW_PAPERS")
        return

    print(f"[PIPELINE] {new_count} new papers, merging...", file=sys.stderr)
    merge = subprocess.run(
        [sys.executable, str(BASE_DIR / "merge_papers.py")],
        cwd=str(BASE_DIR),
        capture_output=True,
        text=True,
        timeout=60,
    )
    if merge.returncode != 0:
        print(f"MERGE_ERROR: {merge.stderr[-800:]}", file=sys.stderr)
        print("ERROR: merge failed")
        sys.exit(merge.returncode)

    # Local enrichment: generate tags and quality scores (no external LLM needed)
    print("[PIPELINE] Local enrich (tags + scores)...", file=sys.stderr)
    subprocess.run([sys.executable, str(BASE_DIR / "enrich.py")],
                   cwd=str(BASE_DIR), capture_output=True, timeout=30)

    print_agent_context(data)

    if args.email:
        print("[PIPELINE] Sending email digest...", file=sys.stderr)
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
        if email.stdout:
            print(email.stdout, file=sys.stderr)
        if email.returncode != 0:
            print(f"EMAIL_ERROR: {email.stderr[-800:]}", file=sys.stderr)
            sys.exit(email.returncode)


def print_agent_context(data: dict) -> None:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    new_papers = data.get("new_papers", [])
    print(f"DATE: {today}")
    print(f"NEW_COUNT: {data.get('new_count', 0)}")
    print(f"TOTAL_AFTER_FILTER: {data.get('total_after_filter', 0)}")
    print()

    cats = {}
    for paper in new_papers:
        for category in paper.get("categories", []):
            cats[category] = cats.get(category, 0) + 1
    print("CATEGORY_STATS:", json.dumps(cats, ensure_ascii=False))
    print()

    print("=== NEW_PAPERS ===")
    for i, paper in enumerate(new_papers):
        print(f"--- Paper {i + 1}/{len(new_papers)} ---")
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
