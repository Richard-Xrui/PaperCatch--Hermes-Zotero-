# PaperCatch 论文中文增强 — Hermes 提示词规范

> 本文档给 Hermes（或任何 LLM agent）使用。目标：为 `papers_database.json` 中缺少中文内容的论文生成结构化中文字段并写回。

## 工作流

1. 获取待处理论文：

```http
GET http://localhost:8765/api/enrich/pending
```

返回 `{count, pending: [{arxiv_id, title, abstract, authors, comment, needs}]}`。

2. 对每篇论文，按下方【生成规范】生成 JSON。

3. 写回（两种方式任选）：

```http
POST http://localhost:8765/api/enrich
Content-Type: application/json

{"items": [ {...}, {...} ]}
```

或者写成文件后运行：

```bash
python apply_enrichment.py <batch.json>
```

格式示例见 `enrich_batch_1.json`。

## 生成规范

每篇论文生成一个 JSON 对象，字段如下：

```json
{
  "arxiv_id": "2607.05377",
  "title_cn": "…",
  "abstract_cn": "…",
  "summary_cn": "…",
  "background_cn": "…",
  "tags": ["…"],
  "quality_score": 7.5,
  "quality_signals": {"innovation": "high", "experiments": "solid", "practicality": "high", "writing": "clear"}
}
```

### title_cn — 中文标题
- 忠实翻译英文标题，信达雅。
- 方法名/系统名（如 Cortex、REDDIT）保留英文原文，格式如：`Cortex：面向长时序操作任务的双向对齐具身智能体框架`。

### abstract_cn — 中文摘要
- **完全按照英文摘要逐句翻译**，不删减、不概括、不加评论。
- 专有名词处理：
  - 通用术语翻译并在首次出现时括注英文，如 `视觉-语言-动作（VLA）模型`。
  - 模型名、数据集名、基准名保留英文（Libero-long、Whisper-tiny、mIoU 等）。
  - 数字、百分比、指标值原样保留。

### summary_cn — 中文总结
- 结构化总结，用以下小标题组织（可按需增减，但至少包含前三项）：
  - `【讲了什么】` 论文研究的问题和核心思路，用通俗语言。
  - `【方法】` 用了什么方法，按 ①②③ 分点。
  - `【解决了什么问题】` 相比已有工作解决了什么痛点。
  - `【结果】` 关键实验数字。
- 面向读者是"决定要不要精读这篇论文"的研究者，写得比摘要更口语、更有信息密度。

### background_cn — 论文背景
- 什么人、什么项目组、什么公司/学校发表的。
- arXiv 元数据通常没有单位信息，允许基于作者署名、公开学术记录做**标注来源的推断**，并加一句"请以论文 PDF 为准"。
- 不确定就写不确定，禁止编造具体头衔或单位。
- 末尾附发表日期和 arXiv 主分类。

### tags — 标签
- 3-6 个英文技术标签（如 LLM、Agent、Diffusion、3D、Safety、Benchmark）。

### quality_score — 质量评分（0-10）
- 综合创新性、实验扎实度、实用价值、写作清晰度评估。
- 参考基准：顶会级完整工作 7-8.5；扎实但增量 5.5-7；初步/单薄 4-5.5；有顶会接收记录或高引用可 8+。

### quality_signals — 质量信号
- 四个维度：`innovation` / `experiments` / `practicality` / `writing`，取值 `high` / `medium` / `solid` / `clear` / `low` 等简短词。

## 注意事项

- 一次批量处理不超过 10 篇，避免超时。
- 只生成 `needs` 里列出的缺失字段也可以，但建议全量生成保证一致性。
- 写回接口只覆盖非空字段，不会清掉已有内容。
