#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
本地论文增强器 - 无需外部 LLM 即可生成标签和质量评分。

功能:
  - 从标题/摘要提取关键词标签
  - 基于启发式规则计算质量评分
  - 标记仍需 LLM 处理的中文摘要

用法:
  python local_enrich.py           # 增强所有论文
  python local_enrich.py --force   # 强制重新生成
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "papers_database.json"

# 技术关键词 -> 标签映射（用于自动打标签）
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
    "Generation": ["generation", "generative", "synthesis"],
    "Segmentation": ["segmentation", "semantic seg"],
    "Detection": ["detection", "object detection"],
    "ASR": ["speech recognition", "asr", "audio"],
    "Video": ["video generation", "video diffusion", "video understanding"],
    "Fine-tuning": ["fine-tuning", "fine tuning", "finetuning", "sft", "lora"],
    "Tabular": ["tabular", "table", "structured data"],
    "Interpretability": ["interpretability", "explainability", "probing", "neuron"],
}

# 顶级机构（提升评分）
TOP_VENUES = ["neurips", "icml", "iclr", "cvpr", "iccv", "eccv", "acl", "emnlp", "naacl", "aaai", "kdd"]


def extract_tags(paper: dict, max_tags: int = 6) -> list[str]:
    """从标题和摘要中提取技术标签。"""
    text = (paper.get("title", "") + " " + paper.get("abstract", "")).lower()
    tags = []
    for tag, keywords in TAG_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            tags.append(tag)
    return tags[:max_tags]


def compute_quality_score(paper: dict) -> float:
    """
    基于启发式规则计算质量评分 (0-10)。

    评分维度:
      - 引用数 (最高 3 分)
      - 发表场所 (最高 2 分)
      - 摘要质量/长度 (最高 1.5 分)
      - 作者数量/合作 (最高 1 分)
      - 代码开源 (最高 1 分)
      - 基础分 (1.5 分)
    """
    score = 1.5  # 基础分

    # 引用信号 (0-3)
    citations = paper.get("citations")
    if citations is not None:
        if citations >= 100:
            score += 3.0
        elif citations >= 50:
            score += 2.5
        elif citations >= 20:
            score += 2.0
        elif citations >= 5:
            score += 1.5
        elif citations >= 1:
            score += 1.0

    # 发表场所信号 (0-2)
    venue = (paper.get("venue") or "").lower()
    comment = (paper.get("comment") or "").lower()
    venue_text = venue + " " + comment
    if any(v in venue_text for v in TOP_VENUES):
        score += 2.0
    elif venue and venue != "none":
        score += 1.0

    # 摘要质量 (0-1.5)
    abstract = paper.get("abstract", "")
    if len(abstract) > 1200:
        score += 1.5
    elif len(abstract) > 800:
        score += 1.0
    elif len(abstract) > 400:
        score += 0.5

    # 作者合作 (0-1)
    authors = paper.get("authors", [])
    if len(authors) >= 6:
        score += 1.0
    elif len(authors) >= 3:
        score += 0.5

    # 代码开源信号 (0-1)
    text = abstract.lower()
    if "github.com" in text or "code is available" in text or "code will be" in text or "project page" in text:
        score += 1.0

    # 影响力引用加成
    inf_citations = paper.get("influential_citations")
    if inf_citations and inf_citations > 0:
        score += min(inf_citations * 0.2, 1.0)

    return round(min(score, 10.0), 1)


def enrich(force: bool = False) -> None:
    if not DB_PATH.exists():
        print("papers_database.json 不存在")
        return

    with open(DB_PATH, "r", encoding="utf-8") as f:
        db = json.load(f)

    papers = db.get("papers", [])
    enriched_count = 0

    for paper in papers:
        changed = False

        # 生成标签
        if force or not paper.get("tags"):
            tags = extract_tags(paper)
            if tags:
                paper["tags"] = tags
                changed = True

        # 生成质量评分
        if force or paper.get("quality_score") is None:
            paper["quality_score"] = compute_quality_score(paper)
            changed = True

        if changed:
            enriched_count += 1

    with open(DB_PATH, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)

    print(f"已增强 {enriched_count} / {len(papers)} 篇论文")
    print("  - 生成标签（基于关键词）")
    print("  - 计算质量评分（基于引用/场所/摘要等）")

    # 统计
    scored = [p for p in papers if p.get("quality_score") is not None]
    if scored:
        avg = sum(p["quality_score"] for p in scored) / len(scored)
        print(f"  - 平均评分: {avg:.2f}")


def main() -> None:
    parser = argparse.ArgumentParser(description="本地论文增强器")
    parser.add_argument("--force", action="store_true", help="强制重新生成所有字段")
    args = parser.parse_args()
    enrich(force=args.force)


if __name__ == "__main__":
    main()
