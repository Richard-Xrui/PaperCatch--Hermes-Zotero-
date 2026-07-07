#!/usr/bin/env python3
"""
Auto-enrich papers in the database with Chinese content.
Called after any new paper is added to papers_database.json.
Generates: title_cn, abstract_cn, summary_cn, quality_score, tags

This is a template processor - the actual LLM enrichment is done
by the Hermes agent. This script marks papers as needing enrichment.
"""
import json
from pathlib import Path
from datetime import datetime, timezone

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "papers_database.json"
PENDING_PATH = BASE_DIR / "pending_enrichment.json"

def mark_pending():
    """Find papers needing Chinese content and mark them for processing."""
    if not DB_PATH.exists():
        return
    
    with open(DB_PATH, "r", encoding="utf-8") as f:
        db = json.load(f)
    
    pending = []
    for p in db["papers"]:
        needs = []
        if not p.get("title_cn"): needs.append("title_cn")
        if not p.get("abstract_cn"): needs.append("abstract_cn")
        if not p.get("summary_cn"): needs.append("summary_cn")
        if p.get("quality_score") is None: needs.append("quality_score")
        if not p.get("tags"): needs.append("tags")
        if needs:
            pending.append({
                "arxiv_id": p["arxiv_id"],
                "title": p.get("title", ""),
                "abstract": p.get("abstract", "")[:500],
                "needs": needs,
                "marked_at": datetime.now(timezone.utc).isoformat()
            })
    
    if pending:
        with open(PENDING_PATH, "w", encoding="utf-8") as f:
            json.dump(pending, f, ensure_ascii=False, indent=2)
        print(f"Marked {len(pending)} papers for enrichment")
    else:
        if PENDING_PATH.exists():
            PENDING_PATH.unlink()
        print("All papers enriched - nothing pending")

if __name__ == "__main__":
    mark_pending()
