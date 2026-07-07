#!/usr/bin/env python3
"""
合并 new_papers.json 到 papers_database.json
保留已有论文的中文摘要和评分，只追加新论文
"""
import json, sys, os
from pathlib import Path
from datetime import datetime, timezone

BASE_DIR = Path(__file__).resolve().parent
NEW_JSON = BASE_DIR / "new_papers.json"
DB_JSON = BASE_DIR / "papers_database.json"

def main():
    if not NEW_JSON.exists():
        print("No new_papers.json found, nothing to merge.")
        return

    with open(NEW_JSON, "r", encoding="utf-8") as f:
        new_data = json.load(f)

    # Load existing DB
    if DB_JSON.exists():
        with open(DB_JSON, "r", encoding="utf-8") as f:
            db = json.load(f)
    else:
        db = {"updated_at": "", "total_count": 0, "categories": [], "papers": []}

    existing_ids = {p["arxiv_id"] for p in db["papers"]}
    new_papers = new_data.get("new_papers", [])

    added = 0
    for paper in new_papers:
        if paper["arxiv_id"] not in existing_ids:
            # Add fields expected by frontend
            paper.setdefault("abstract_cn", "")
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
            db["papers"].append(paper)
            existing_ids.add(paper["arxiv_id"])
            added += 1

    db["total_count"] = len(db["papers"])
    db["updated_at"] = datetime.now(timezone.utc).isoformat()
    db["categories"] = sorted(set(
        c for p in db["papers"] for c in p.get("categories", [])
    ))

    with open(DB_JSON, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)

    print(f"Merged: {added} new papers added. Total: {db['total_count']}")
    return db

if __name__ == "__main__":
    import subprocess, sys
    result = main()
    # Auto-mark papers for enrichment
    subprocess.run([sys.executable, str(BASE_DIR / "auto_enrich.py")],
                   cwd=str(BASE_DIR), capture_output=True, timeout=30)
    exit(0 if result else 1)
    main()
