# PaperCatch 全网检索与论文智能体计划

状态：本期已完成并验证（2026-07-14）

## 目标

把每日论文来源从单一 arXiv 扩展为可配置的公开聚合源，并让内置智能体基于已保存论文回答问题、生成学习笔记。

## 实施顺序

1. 新增统一论文模型和来源适配器：arXiv、OpenAlex、Crossref、Semantic Scholar、Europe PMC。
2. 对 DOI、arXiv ID、PMID、OpenAlex ID 和规范化标题去重；保留 `source_ids`、`landing_url`、`pdf_url`、`open_access` 与失败源明细。
3. 将 `search_config.json` 扩展为 `sources` 配置，保留旧 arXiv 流水线兼容；多源模式使用隔离 CLI 和原子输出。
4. 新增 `/hermes/ask` 与 `/hermes/notes`，默认使用本地摘要/全文上下文，不依赖外部 LLM；需要外部模型时由后续明确配置。
5. 前端在论文卡片和详情中提供“问这篇论文”“生成学习笔记”入口，并展示来源/开放获取状态。
6. 已实现合法 OA PDF 下载、校验、manifest 和前端保存入口；机构授权全文仍只允许使用用户已有授权会话。

## 验证要求

- 所有源请求使用 mock HTTP 响应；不调用真实 arXiv、OpenAlex、Crossref、Semantic Scholar、Europe PMC、Zotero、SMTP 或 LLM。
- 覆盖源失败降级、去重、日期/关键词过滤、配置兼容、问答无证据时拒答和笔记生成。
- 运行多源聚焦测试、服务器接口测试、前端契约测试和全量回归。

## 完成结果

- 每日流水线根据 `sources` 配置在旧 arXiv 模式与五源聚合模式之间选择，支持任意研究领域/关键词。
- 论文 Agent、Markdown 学习笔记、复制入口与合法 OA PDF 保存已接入网页和桌面共用前端。
- 全量回归 `193/193 OK`；Edge `1280x800`、`390x844` mock QA 无溢出、重叠或运行错误。
