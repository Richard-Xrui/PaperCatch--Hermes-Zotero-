# PaperCatch Hermes Runbook

这份文档给 Hermes 或其他 agent 使用。目标是尽量少问用户，让系统自己发现、检查、启动、抓取和推送论文。

## 首选流程

```bash
cd D:\Codex\papercatch
python start.py --bootstrap
```

`--bootstrap` 会：

- 自动发现 Zotero/Hermes。
- 保存 `config.local.json`。
- 安装 Hermes `on_session_start` hook，让每次 Hermes 新会话自动确保 PaperCatch 后台运行。

如果需要分步排查：

```bash
python start.py --discover
python start.py --doctor
python start.py
```

如果 `--doctor` 发现 Zotero、Hermes 或邮件未配置，也可以单独运行：

```bash
python start.py --setup
```

配置向导会用 `--discover` 的结果预填路径。用户通常只需要回车确认。

如果用户要求“自动确认”或当前任务不适合交互，运行：

```bash
python start.py --setup --yes
```

这会把发现到的 Zotero/Hermes 本地路径写入 `config.local.json`，但不会伪造 API key、邮箱密码等敏感凭据。

只安装 Hermes 自启动 hook：

```bash
python start.py --install-hermes-autostart
```

hook 命令会调用 `papercatch_autostart.py --ensure`。它是幂等的：PaperCatch 已运行时不重复启动，未运行时后台启动。

## 本地发现规则

`python start.py --discover` 会只读寻找：

- Zotero 可执行文件。
- Zotero profile 目录。
- Zotero 数据目录和 `zotero.sqlite`。
- Zotero 本地 user id，能从本地库读到时。
- Zotero Connector 本地服务：`http://127.0.0.1:23119/connector/ping`。
- Hermes 可执行文件。
- Hermes home 目录。

注意：PaperCatch 不会直接写 Zotero 的本地 sqlite 数据库。真实自动入库优先使用 Zotero Web API，因为它能保持同步状态安全。

## Zotero 行为

真实入库需要 Zotero 配置完整：

- `ZOTERO_API_KEY`
- `ZOTERO_USER_ID`

也可以写入 `config.local.json`，或在网页/桌面端进入“设置 → Zotero 集成”。如果本地发现到了 user id，`python start.py --setup` 会自动预填。页面不会回填已保存的 API Key，密钥框留空保存会保留原值。

当请求里包含 collection 或前端分类规则时：

- Zotero 已有这个文件夹：直接放入。
- Zotero 没有这个文件夹：自动创建。
- 支持路径，例如 `PaperCatch/LLM & Agents`。

## Hermes 搜索行为

前端的 Hermes 对话框调用：

```http
POST /hermes/search
```

后端解析顺序：

1. 优先读取 `config.local.json` 的 `llm.api_key/base_url`。
2. 其次读取 `DEEPSEEK_API_KEY/DEEPSEEK_BASE_URL`。
3. LLM 未配置、返回无效结果或调用失败时，使用内置中文/英文规则解析器。

`HERMES_API_URL` 和 `HERMES_COMMAND` 目前用于本地发现与状态配置，尚未接入 `/hermes/search` 调用链。LLM 解析结果应符合类似结构：

```json
{
  "categories": ["cs.AI", "cs.CL"],
  "keywords": ["LLM", "agent"],
  "days": 7,
  "max_results": 10,
  "auto_zotero": true,
  "collection": "PaperCatch/LLM & Agents"
}
```

LLM 解析失败时系统会自动回落到内置解析器，响应中的 `llm_used` 为 `false`；`warnings` 当前用于论文合并后的本地增强失败，不代表查询解析回落。

## 每日自动抓取和邮件

手动跑一次：

```bash
python daily_pipeline.py --email
```

预览邮件内容，不发送：

```bash
python email_digest.py --dry-run
```

Hermes cron 或系统任务可以运行：

```bash
python cron_wrapper.py
```

`cron_wrapper.py` 会运行 `daily_pipeline.py --email`。如果邮件未启用，会跳过邮件发送。

## 排查顺序

1. 先运行 `python start.py --discover` 看本机发现情况。
2. 再运行 `python start.py --doctor` 看 PaperCatch 当前配置。
3. 如果 Zotero local found 但 Zotero not configured，运行 `python start.py --setup`，确认路径并补 API key。
4. “问 Hermes”显示 `llm_used=false` 时，检查 `llm.api_key/base_url` 或 `DEEPSEEK_API_KEY/DEEPSEEK_BASE_URL`；不配置也可继续使用内置规则解析器。
5. 如果邮件是 off，运行 `python start.py --setup` 填 SMTP。
6. 如果前端打不开，确认 `python start.py` 仍在运行，并访问 `http://localhost:8765/health`。

## 中文内容增强（重要）

论文进入系统后，Hermes 负责生成中文标题、中文摘要（忠实翻译）、中文总结和论文背景。

具体提示词规范和写回接口见 [ENRICHMENT_PROMPT.md](ENRICHMENT_PROMPT.md)。

快速流程：

```
GET  /api/enrich/pending   # 拿到缺中文内容的论文
POST /api/enrich           # 生成后写回 {"items": [...]}
```

