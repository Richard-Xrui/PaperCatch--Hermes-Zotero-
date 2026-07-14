from __future__ import annotations

import unittest

from paper_agent import answer_question, generate_learning_notes


PAPER = {
    "paper_id": "doi:10.1000/demo",
    "arxiv_id": "doi:10.1000/demo",
    "title": "Agent memory benchmark",
    "title_cn": "智能体记忆基准",
    "authors": ["Ada Lovelace"],
    "published": "2026-07-13",
    "sources": ["openalex", "crossref"],
    "abstract_full": (
        "We propose a memory benchmark for tool-using agents. "
        "The method evaluates long-horizon reasoning with controlled tasks. "
        "Experiments improve retrieval accuracy by 12 percent."
    ),
    "summary_cn": "论文提出面向工具智能体的记忆基准，并评估长程推理。",
    "tags": ["agent", "memory"],
}


class PaperAgentTests(unittest.TestCase):
    def test_answers_from_relevant_saved_evidence(self):
        result = answer_question(PAPER, "这篇论文的方法是什么？")
        self.assertTrue(result["grounded"])
        self.assertEqual("builtin", result["mode"])
        self.assertIn("method evaluates", result["answer"])
        self.assertTrue(result["evidence"])

    def test_refuses_when_saved_context_has_no_support(self):
        result = answer_question(PAPER, "作者的实验室地址是什么？")
        self.assertFalse(result["grounded"])
        self.assertIn("没有足够证据", result["answer"])

    def test_learning_notes_are_markdown_and_caveat_missing_full_text(self):
        result = generate_learning_notes(PAPER, "重点理解实验结果")
        self.assertTrue(result["grounded"])
        self.assertIn("# 智能体记忆基准 - 学习笔记", result["markdown"])
        self.assertIn("## 主要发现", result["markdown"])
        self.assertIn("待核实", result["markdown"])
        self.assertEqual("重点理解实验结果", result["focus"])

    def test_empty_question_is_rejected(self):
        with self.assertRaises(ValueError):
            answer_question(PAPER, "")


if __name__ == "__main__":
    unittest.main()
