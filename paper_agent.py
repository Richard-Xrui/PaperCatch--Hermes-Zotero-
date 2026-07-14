#!/usr/bin/env python3
"""Offline, source-grounded paper Q&A and learning-note generation."""

from __future__ import annotations

import re
from typing import Any


FIELD_LABELS = {
    "summary_cn": "中文总结",
    "abstract_cn": "中文摘要",
    "abstract_full": "英文摘要",
    "abstract": "摘要",
    "background_cn": "论文背景",
    "comment": "论文备注",
}
GENERIC_QUESTIONS = (
    "讲了什么",
    "主要内容",
    "总结",
    "概括",
    "核心贡献",
    "what is this paper",
    "summarize",
    "summary",
)
INTENT_TERMS = {
    "method": ("方法", "模型", "算法", "框架", "怎么", "如何", "method", "model", "approach", "framework"),
    "result": ("结果", "效果", "提升", "性能", "发现", "result", "performance", "improve", "finding"),
    "limit": ("局限", "不足", "限制", "风险", "limit", "limitation", "weakness", "risk"),
    "data": ("数据", "数据集", "样本", "实验结果", "dataset", "data", "experiment", "benchmark"),
}
STOPWORDS = {
    "the", "and", "for", "that", "this", "with", "from", "paper", "what", "how", "why",
    "does", "about", "into", "are", "was", "were", "has", "have", "请问", "论文", "这篇",
    "什么", "如何", "是否", "可以", "一下", "主要", "作者", "研究",
}


def paper_key(paper: dict[str, Any]) -> str:
    return str(paper.get("paper_id") or paper.get("arxiv_id") or "").strip()


def _sentences(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", str(text or "").strip())
    if not text:
        return []
    pieces = re.split(r"(?<=[。！？!?])\s*|(?<=[.])\s+(?=[A-Z0-9])", text)
    return [piece.strip() for piece in pieces if len(piece.strip()) >= 8]


def _tokens(text: str) -> set[str]:
    tokens = {
        token.casefold()
        for token in re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}|[\u4e00-\u9fff]{2,}", str(text or ""))
    }
    return {token for token in tokens if token not in STOPWORDS}


def _evidence(paper: dict[str, Any]) -> list[dict[str, str]]:
    result = []
    for field in FIELD_LABELS:
        value = str(paper.get(field) or "").strip()
        if not value or value in {"待 LLM 生成", "待生成"}:
            continue
        for sentence in _sentences(value):
            result.append({"field": field, "label": FIELD_LABELS[field], "text": sentence})
    return result


def _question_intents(question: str) -> set[str]:
    low = question.casefold()
    return {
        intent
        for intent, terms in INTENT_TERMS.items()
        if any(term.casefold() in low for term in terms)
    }


def _rank_evidence(paper: dict[str, Any], question: str, limit: int = 3) -> list[dict[str, str]]:
    evidence = _evidence(paper)
    if not evidence:
        return []
    low = question.casefold()
    generic = any(term in low for term in GENERIC_QUESTIONS)
    query_tokens = _tokens(question)
    intents = _question_intents(question)
    ranked = []
    for index, item in enumerate(evidence):
        text_low = item["text"].casefold()
        overlap = sum(1 for token in query_tokens if token in text_low)
        intent_hits = sum(
            1
            for intent in intents
            if any(term.casefold() in text_low for term in INTENT_TERMS[intent])
        )
        field_bonus = {"summary_cn": 3, "abstract_cn": 2, "abstract_full": 1}.get(item["field"], 0)
        score = overlap * 5 + intent_hits * 3 + (field_bonus if generic else 0)
        ranked.append((score, -index, item))
    ranked.sort(reverse=True, key=lambda row: (row[0], row[1]))
    if ranked[0][0] <= 0 and not generic:
        return []
    selected = []
    seen = set()
    for _, _, item in ranked:
        signature = item["text"].casefold()
        if signature in seen:
            continue
        seen.add(signature)
        selected.append(item)
        if len(selected) >= limit:
            break
    return selected


def answer_question(paper: dict[str, Any], question: str) -> dict[str, Any]:
    question = str(question or "").strip()
    if not question:
        raise ValueError("question must not be empty")
    if len(question) > 2000:
        raise ValueError("question must be at most 2000 characters")
    selected = _rank_evidence(paper, question)
    key = paper_key(paper)
    title = str(paper.get("title_cn") or paper.get("title") or key)
    if not selected:
        return {
            "paper_id": key,
            "title": title,
            "question": question,
            "answer": "当前保存的标题、摘要和笔记没有足够证据回答这个问题。请先获取全文，或换成摘要能够支持的问题。",
            "grounded": False,
            "mode": "builtin",
            "evidence": [],
        }
    answer = " ".join(item["text"] for item in selected)
    evidence = [
        {"field": item["field"], "label": item["label"], "quote": item["text"]}
        for item in selected
    ]
    return {
        "paper_id": key,
        "title": title,
        "question": question,
        "answer": answer,
        "grounded": True,
        "mode": "builtin",
        "evidence": evidence,
    }


def _pick_by_intent(paper: dict[str, Any], intent: str, fallback: str) -> str:
    question = " ".join(INTENT_TERMS[intent])
    selected = _rank_evidence(paper, question, limit=2)
    return " ".join(item["text"] for item in selected) if selected else fallback


def generate_learning_notes(paper: dict[str, Any], focus: str = "") -> dict[str, Any]:
    focus = str(focus or "").strip()
    if len(focus) > 2000:
        raise ValueError("focus must be at most 2000 characters")
    key = paper_key(paper)
    title = str(paper.get("title_cn") or paper.get("title") or key)
    summary_items = _rank_evidence(paper, focus or "总结这篇论文的主要内容", limit=2)
    summary = " ".join(item["text"] for item in summary_items) or "当前仅有元数据，尚缺少可用于总结的摘要或全文。"
    method = _pick_by_intent(paper, "method", "摘要未明确给出方法细节。")
    result = _pick_by_intent(paper, "result", "摘要未明确给出定量结果。")
    limitation = _pick_by_intent(paper, "limit", "摘要通常不足以判断完整局限，需要结合全文核实。")
    tags = [str(tag) for tag in paper.get("tags", []) if str(tag).strip()][:8]
    fields = [str(item) for item in paper.get("fields_of_study", []) if str(item).strip()][:5]
    keywords = list(dict.fromkeys(tags + fields))
    authors = "、".join(str(author) for author in paper.get("authors", [])[:6]) or "未知"
    source = ", ".join(paper.get("sources") or [paper.get("source") or "local"])
    focus_line = focus or "理解论文的研究问题、方法、主要发现与局限"
    markdown = f"""# {title} - 学习笔记

## 基本信息

- 作者：{authors}
- 发表时间：{paper.get('published') or '未知'}
- 来源：{source}
- DOI/arXiv/PMID：{paper.get('doi') or paper.get('arxiv_id') or paper.get('pmid') or key}
- 本次关注：{focus_line}

## 一句话理解

{summary}

## 研究方法

{method}

## 主要发现

{result}

## 局限与待核实

{limitation}

## 关键词

{('、'.join(keywords) if keywords else '待阅读全文后补充')}

## 下一步学习问题

1. 论文的核心假设在什么条件下成立？
2. 方法相对最强基线的改进来自哪个组件？
3. 数据集、评价指标和消融实验是否足以支持结论？
4. 该方法能否迁移到自己的研究场景？

> 证据范围：以上内容仅基于 PaperCatch 当前保存的论文元数据、摘要和已有中文增强；未被原文支持的内容已标注为待核实。
"""
    evidence_fields = list(dict.fromkeys(item["field"] for item in summary_items))
    return {
        "paper_id": key,
        "title": title,
        "focus": focus,
        "mode": "builtin",
        "grounded": bool(summary_items),
        "evidence_fields": evidence_fields,
        "markdown": markdown,
    }
