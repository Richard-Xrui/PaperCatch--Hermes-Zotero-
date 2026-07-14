#!/usr/bin/env python3
"""PaperCatch enrichment: tags, quality scores, and Chinese content management.

Usage:
  python enrich.py                  # Local enrichment (tags + scores, no LLM needed)
  python enrich.py --mark-pending   # Mark papers needing LLM Chinese content
  python enrich.py --apply <file>   # Apply LLM-generated batch to database
  python enrich.py --force          # Force re-generate all local fields
"""

from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from json_store import locked_update_json, read_json, write_json_atomic

MODULE_DIR = Path(__file__).resolve().parent
BASE_DIR = Path(os.environ.get("PAPERCATCH_DATA_DIR", MODULE_DIR)).expanduser().resolve()
DB_PATH = BASE_DIR / "papers_database.json"
PENDING_PATH = BASE_DIR / "pending_enrichment.json"

# ── Tag keywords ──────────────────────────────────────
TAG_KEYWORDS = {
    "LLM": ["large language model", "llm", "language model", "gpt", "llama"],
    "Agent": ["agent", "agentic", "multi-agent"],
    "RAG": ["retrieval-augmented", "rag", "retrieval augmented"],
    "RL": ["reinforcement learning", "rlhf", "policy gradient", "grpo", "ppo"],
    "Diffusion": ["diffusion", "denoising", "score-based"],
    "VLM": ["vision-language", "vlm", "multimodal", "multi-modal"],
    "3D": ["3d ", "3d-", "point cloud", "gaussian splatting", "nerf", "reconstruction"],
    "4D": ["4d ", "4d-", "spatio-temporal", "dynamic scene"],
    "Robotics": ["robot", "manipulation", "grasp", "vla", "embodied"],
    "Safety": ["safety", "alignment", "jailbreak", "harmful", "refusal"],
    "Watermark": ["watermark", "watermarking"],
    "Benchmark": ["benchmark", "dataset", "evaluation"],
    "Efficiency": ["efficient", "compression", "quantization", "pruning", "lightweight"],
    "Reasoning": ["reasoning", "chain-of-thought", "chain of thought"],
    "Transformer": ["transformer", "attention", "self-attention"],
    "Segmentation": ["segmentation", "segment anything", "sam"],
    "Code": ["code generation", "program synthesis", "software engineering"],
}


def extract_tags(paper: dict) -> list[str]:
    text = (paper.get("title", "") + " " + paper.get("abstract", "")).lower()
    tags = []
    for tag, keywords in TAG_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            tags.append(tag)
    return tags[:8]


def compute_quality(paper: dict) -> tuple[float | None, dict]:
    score = 5.0
    signals = {}
    abstract = paper.get("abstract", "").lower()
    title = paper.get("title", "").lower()

    # Venue bonus
    venue = paper.get("venue") or ""
    top_venues = ["neurips", "icml", "iclr", "cvpr", "iccv", "eccv", "acl", "emnlp", "naacl",
                  "aaai", "ijcai", "siggraph", "sigkdd", "www", "sigir", "isca", "osdi", "sosp"]
    if any(v in venue.lower() for v in top_venues):
        score += 2.0
        signals["venue"] = "top"

    # Citation bonus
    citations = paper.get("citations")
    if citations is not None:
        if citations > 100:
            score += 1.5
        elif citations > 20:
            score += 0.5

    # Abstract length indicates depth
    if len(abstract) > 800:
        score += 0.5
    elif len(abstract) < 200:
        score -= 0.5

    # Keywords indicating strong work
    strong_signals = ["state-of-the-art", "outperforms", "novel", "first", "extensive experiments"]
    if any(s in abstract for s in strong_signals):
        score += 0.5
        signals["claims"] = "strong"

    # Innovation signals
    if any(w in title for w in ["novel", "new", "first", "rethinking", "revisiting"]):
        signals["innovation"] = "high"
    else:
        signals["innovation"] = "medium"

    signals["experiments"] = "solid" if len(abstract) > 500 else "limited"
    signals["practicality"] = "high" if any(w in abstract for w in ["code", "open-source", "available", "release"]) else "medium"
    signals["writing"] = "clear"

    return round(min(10, max(0, score)), 1), signals


def local_enrich(force: bool = False, db_path: Path = DB_PATH) -> int:
    """Generate tags and quality scores for papers without LLM."""
    db_path = Path(db_path)
    if not db_path.exists():
        return 0
    updated = 0

    def update(db: dict) -> dict:
        nonlocal updated
        for paper in db.get("papers", []):
            old_tags = paper.get("tags")
            old_score = paper.get("quality_score")
            old_signals = paper.get("quality_signals")
            tags_missing = "tags" not in paper or old_tags is None
            signals_unset = old_signals is None or old_signals == {}
            tags_placeholder = old_tags == [] and old_score is None and signals_unset
            if force or tags_missing or tags_placeholder:
                tags = extract_tags(paper)
                if old_tags != tags:
                    paper["tags"] = tags
                    updated += 1

            score_missing = old_score is None
            signals_missing = old_signals is None
            if force or score_missing or signals_missing:
                score, signals = compute_quality(paper)
                quality_changed = False
                if (force or score_missing) and old_score != score:
                    paper["quality_score"] = score
                    quality_changed = True
                if (force or signals_missing) and old_signals != signals:
                    paper["quality_signals"] = signals
                    quality_changed = True
                if quality_changed:
                    updated += 1
        return db

    locked_update_json(
        db_path,
        {"updated_at": "", "total_count": 0, "categories": [], "papers": []},
        update,
    )
    return updated


def mark_pending(db_path: Path = DB_PATH, pending_path: Path = PENDING_PATH) -> int:
    """Mark papers needing LLM Chinese content."""
    db_path = Path(db_path)
    pending_path = Path(pending_path)
    if not db_path.exists():
        return 0
    db = read_json(db_path, {"papers": []})
    pending = []
    for p in db["papers"]:
        needs = []
        if not p.get("title_cn") or p.get("title_cn") == p.get("title", "")[:80]:
            needs.append("title_cn")
        if not p.get("abstract_cn") or p.get("abstract_cn") == p.get("abstract", "")[:200]:
            needs.append("abstract_cn")
        if not p.get("summary_cn") or p.get("summary_cn") == "待 LLM 生成":
            needs.append("summary_cn")
        if needs:
            pending.append({
                "arxiv_id": p["arxiv_id"],
                "title": p.get("title", ""),
                "abstract": p.get("abstract", "")[:500],
                "needs": needs,
                "marked_at": datetime.now(timezone.utc).isoformat(),
            })
    if pending:
        write_json_atomic(pending_path, pending)
    else:
        if pending_path.exists():
            pending_path.unlink()
    return len(pending)


def apply_batch(batch_path: str, db_path: Path = DB_PATH) -> int:
    """Apply LLM-generated Chinese content to database."""
    FIELDS = ["title_cn", "abstract_cn", "summary_cn", "background_cn",
              "affiliations", "tags", "quality_score", "quality_signals"]
    batch_path = Path(batch_path)
    db_path = Path(db_path)
    if not batch_path.exists():
        raise FileNotFoundError(batch_path)
    items = read_json(batch_path, [])
    if isinstance(items, dict):
        items = items.get("items", [])
    updated = 0

    def update(db: dict) -> dict:
        nonlocal updated
        index = {paper["arxiv_id"]: paper for paper in db.get("papers", [])}
        for item in items:
            paper = index.get(item.get("arxiv_id"))
            if not paper:
                continue
            changed = False
            for field in FIELDS:
                if field in item and item[field] not in (None, "") and paper.get(field) != item[field]:
                    paper[field] = item[field]
                    changed = True
            if changed:
                updated += 1
        return db

    locked_update_json(
        db_path,
        {"updated_at": "", "total_count": 0, "categories": [], "papers": []},
        update,
    )
    return updated


# ── CLI ────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(description="PaperCatch enrichment")
    parser.add_argument("--force", action="store_true", help="force re-generate all fields")
    parser.add_argument("--mark-pending", action="store_true", help="mark papers needing LLM content")
    parser.add_argument("--apply", type=str, metavar="FILE", help="apply LLM batch JSON to database")
    args = parser.parse_args()

    if args.apply:
        n = apply_batch(args.apply)
        print(f"Applied batch: {n} papers updated")
        return

    if args.mark_pending:
        n = mark_pending()
        print(f"Marked {n} papers for LLM enrichment")
        return

    n = local_enrich(force=args.force)
    print(f"Local enrichment: {n} fields updated (tags + scores)")


if __name__ == "__main__":
    main()
