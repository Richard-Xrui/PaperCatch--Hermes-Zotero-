#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 Hermes/LLM 生成的中文内容写回 papers_database.json。

数据格式与 POST /api/enrich 一致。此文件由 LLM agent 生成后运行：
    python apply_enrichment.py enrichment_batch.json
"""
import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "papers_database.json"

FIELDS = ["title_cn", "abstract_cn", "summary_cn", "background_cn",
          "affiliations", "tags", "quality_score", "quality_signals"]


def main():
    if len(sys.argv) < 2:
        print("用法: python apply_enrichment.py <batch.json>")
        sys.exit(1)
    batch_path = Path(sys.argv[1])
    with open(batch_path, "r", encoding="utf-8") as f:
        items = json.load(f)
    if isinstance(items, dict):
        items = items.get("items", [])

    with open(DB_PATH, "r", encoding="utf-8") as f:
        db = json.load(f)
    index = {p["arxiv_id"]: p for p in db.get("papers", [])}

    updated = 0
    for item in items:
        paper = index.get(item.get("arxiv_id"))
        if not paper:
            print(f"  跳过（不在库中）: {item.get('arxiv_id')}")
            continue
        for field in FIELDS:
            if field in item and item[field] not in (None, ""):
                paper[field] = item[field]
        updated += 1

    with open(DB_PATH, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)
    print(f"已更新 {updated} / {len(items)} 篇论文的中文内容")


if __name__ == "__main__":
    main()
