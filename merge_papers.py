#!/usr/bin/env python3
"""Merge new_papers.json into the shared papers database."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from enrich import mark_pending
from json_store import locked_update_json, read_json


BASE_DIR = Path(__file__).resolve().parent
NEW_JSON = BASE_DIR / "new_papers.json"
DB_JSON = BASE_DIR / "papers_database.json"


def paper_identity(paper: dict) -> str:
    """Return a stable cross-source identity while keeping arXiv compatibility."""

    return str(
        paper.get("paper_id")
        or paper.get("arxiv_id")
        or paper.get("doi")
        or paper.get("pmid")
        or paper.get("title")
        or ""
    ).strip()


def merge_papers(new_path: Path = NEW_JSON, db_path: Path = DB_JSON):
    """Merge a batch into a database using one locked read-modify-write."""

    new_path = Path(new_path)
    db_path = Path(db_path)
    if not new_path.exists():
        print("No new_papers.json found, nothing to merge.")
        return None

    new_data = read_json(new_path, {"new_papers": []})
    new_papers = new_data.get("new_papers", [])
    added = 0

    def update(db):
        nonlocal added
        papers = db.setdefault("papers", [])
        existing_ids = {paper_identity(paper) for paper in papers}
        for paper in new_papers:
            identity = paper_identity(paper)
            if not identity:
                continue
            paper.setdefault("paper_id", identity)
            paper.setdefault("arxiv_id", identity)
            if identity in existing_ids:
                continue
            paper.setdefault("title_cn", paper.get("title", "")[:80])
            paper.setdefault("abstract_cn", paper.get("abstract", "")[:200])
            paper.setdefault("summary_cn", "待 LLM 生成")
            paper.setdefault("background_cn", "")
            paper.setdefault("affiliations", "")
            paper.setdefault("quality_score", None)
            paper.setdefault("quality_signals", {})
            paper.setdefault("zotero_status", None)
            paper.setdefault("crawled_date", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
            paper.setdefault("tags", [])
            paper.setdefault("venue", None)
            paper.setdefault("citations", None)
            paper.setdefault("influential_citations", None)
            paper.setdefault("fields_of_study", [])
            paper.setdefault("is_open_access", False)
            papers.append(paper)
            existing_ids.add(identity)
            added += 1

        db["total_count"] = len(papers)
        db["updated_at"] = datetime.now(timezone.utc).isoformat()
        db["categories"] = sorted({
            category
            for paper in papers
            for category in paper.get("categories", [])
        })
        return db

    result = locked_update_json(
        db_path,
        {"updated_at": "", "total_count": 0, "categories": [], "papers": []},
        update,
    )
    print(f"Merged: {added} new papers added. Total: {result['total_count']}")
    return result


def main() -> int:
    result = merge_papers()
    if result is None:
        return 1
    try:
        mark_pending(
            db_path=DB_JSON,
            pending_path=BASE_DIR / "pending_enrichment.json",
        )
    except Exception as exc:
        print(
            f"PENDING_ERROR: {json.dumps({'stage': 'mark_pending', 'status': 'partial_failure', 'error': str(exc)}, ensure_ascii=False)}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
