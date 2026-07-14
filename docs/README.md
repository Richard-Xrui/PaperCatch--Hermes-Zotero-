# PaperCatch 文档索引

本文档按用途整理项目资料。已有文档保持原路径，新增文档应先归入下列类别，再从这里补充链接。

## 使用与运行

面向日常使用、启动、配置和 Hermes 运维：

- [快速开始](QUICKSTART.md)：启动、配置、常用操作和常见问题。
- [Hermes Runbook](HERMES_RUNBOOK.md)：本地发现、hook、搜索、增强和排查顺序。
- [桌面端运行与构建](../desktop/README.md)：pywebview 启动、PyInstaller 构建、数据目录和迁移方式。
- [项目根 README](../README.md)：项目概览、API、文件结构和开发测试命令。

## 功能与规范

描述产品行为、数据字段和内容生成规则：

- [前端规格](FRONTEND_SPEC.md)：当前服务托管架构、页面行为、数据契约、API、响应式和验收标准。
- [中文增强提示词](ENRICHMENT_PROMPT.md)：中文标题、摘要、总结、标签和评分规范。

## 问题与变更

记录已经发生的事实、修复证据和历史变化：

- [问题与修复台账](ISSUE_FIX_LOG.md)：PC-001 至 PC-041 的状态、根因、修改和验证记录。
- [更新日志](CHANGELOG.md)：面向用户的功能和界面变化历史。

问题台账按领域分类，具体状态以台账总表为准：安全/API、存储一致性、抓取流水线、外部集成、测试可靠性、导入/文档、前端体验。

## 设计与实施

面向开发和代码修改：

- [全面修复设计](superpowers/specs/2026-07-12-papercatch-comprehensive-repair-design.md)：总体目标、边界、架构和阶段划分。
- [阶段 0+1 计划](superpowers/plans/2026-07-12-papercatch-stage-0-1-security-tests.md)：测试隔离与 HTTP 安全边界。
- [阶段 2 计划](superpowers/plans/2026-07-12-papercatch-stage-2-storage-consistency.md)：JSON 存储一致性、幂等增强和自动增强恢复。
- [前端与桌面端阶段计划](superpowers/plans/2026-07-13-papercatch-frontend-desktop.md)：响应式、批量选择、Modal、Zotero 图形配置、桌面生命周期和 EXE 验证。
- [阶段 3 PDF 自动下载计划](superpowers/plans/2026-07-13-papercatch-stage-3-pdf-auto-download.md)：去重、回退、检查、安全边界和 Zotero 前置阶段。
- [全网多源检索与论文智能体计划](superpowers/plans/2026-07-14-papercatch-global-search-agent.md)：公开多源聚合、跨源去重、论文问答、学习笔记和合法 PDF 边界。

`superpowers/specs/` 只放已经确认的设计，`superpowers/plans/` 只放可执行的实施计划；阶段完成后，结果回写到问题台账和项目记忆。

## 项目长期记忆

- [CODEX_PROJECT_MEMORY](../CODEX_PROJECT_MEMORY.md)：项目根目录固定记忆文件，记录技术栈、命令、风险、阶段结果和后续方向。

## 维护规则

1. 新的使用说明放在 `docs/` 根目录，并在“使用与运行”或“功能与规范”中登记。
2. 新的问题、修改和验证只追加到 `ISSUE_FIX_LOG.md`，不要另建分散台账。
3. 新的设计放入 `docs/superpowers/specs/`，新的执行步骤放入 `docs/superpowers/plans/`。
4. 以后会话仍先读取项目根目录的 `CODEX_PROJECT_MEMORY.md`，再按本索引进入细节。
