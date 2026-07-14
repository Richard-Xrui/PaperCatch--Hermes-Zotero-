# PaperCatch

PaperCatch 是一个本地优先的多源论文抓取、浏览、分类、问答、学习笔记和 Zotero 入库工具。公开元数据可来自 arXiv、OpenAlex、Crossref、Semantic Scholar 与 Europe PMC；无法确认开放获取权限的链接不会被标记为可直接下载。

文档按用途分类，入口见 [docs/README.md](docs/README.md)。

## GitHub 拉下来后的推荐流程

```bash
cd D:\PaperCatch-Hermes-Zotero
python start.py --bootstrap
```

`--bootstrap` 会自动做三件事：

- 发现本机 Zotero 和 Hermes。
- 写入 `config.local.json`，预填能自动确认的本地路径。
- 给 Hermes 安装 `on_session_start` 自启动 hook，以后每次开启 Hermes 新会话都会确保 PaperCatch 后台已启动。

这个命令不会伪造 Zotero API key、邮箱密码、微信授权这类敏感内容。它会把这些列为需要用户确认的事项。

## 一键运行

```bash
python start.py
```

打开：`http://localhost:8765`

服务默认只监听本机 `127.0.0.1`，不会接受局域网或公网连接；前端和 API 使用同源请求。

`python start.py` 默认启用自动重载。后端或前端改动保存后，服务会自动重启。

## Windows 桌面端

桌面端代码独立放在 `desktop/`，通过 pywebview 复用同一套 Python 后端和 `viewer/`，不复制业务逻辑：

```powershell
python -m pip install -r desktop/requirements.txt
python -m desktop
```

构建 Windows EXE：

```powershell
powershell -ExecutionPolicy Bypass -File desktop/build.ps1
```

桌面壳使用系统分配的随机 loopback 端口，关闭窗口时同步停止后端。打包版的可写数据保存在 `%LOCALAPPDATA%\PaperCatch`；右上角“设置”可直接配置 Zotero User ID、API Key 和默认 Collection。运行、构建和现有数据迁移说明见 [desktop/README.md](desktop/README.md)。

## 分步配置

自动发现：

```bash
python start.py --discover
```

交互配置：

```bash
python start.py --setup
```

自动接受发现结果：

```bash
python start.py --setup --yes
```

只安装 Hermes 自启动：

```bash
python start.py --install-hermes-autostart
```

自启动 hook 会调用 `papercatch_autostart.py`。它先检查 `http://localhost:8765/health`，如果 PaperCatch 已经在运行就什么都不做；如果没运行，就后台启动。

## Zotero

PaperCatch 会只读检测 Zotero 本地文件，不会直接写 Zotero 的 sqlite 数据库。原因是直接改本地数据库风险很高，容易破坏 Zotero 同步状态。

自动入库的推荐方式是 Zotero Web API：

- `ZOTERO_API_KEY`
- `ZOTERO_USER_ID`

也可以在 `python start.py --setup` 里填写，或在网页/桌面端右上角进入“设置 → Zotero 集成”。PaperCatch 能自动发现本地 user id 时会预填，API key 通常仍需要用户授权生成。

设置接口只返回“是否已配置”、User ID 和默认 Collection，不会把 API Key 回填到页面；密钥输入留空保存会保留原值。非空的 `ZOTERO_API_KEY`、`ZOTERO_USER_ID` 和 `ZOTERO_DEFAULT_COLLECTION` 环境变量仍拥有最高运行时优先级。

Zotero collection 支持路径，例如：

```text
PaperCatch/LLM & Agents
PaperCatch/Vision
PaperCatch/Safety
```

Zotero 中已有文件夹时会直接使用，没有时会自动创建。

## Hermes

PaperCatch 会自动寻找本地 Hermes：

- PATH 里的 `hermes` / `hermes.exe`
- 用户目录下的 `.hermes`
- 项目同级目录里的 `hermes` / `Hermes`

当前前端“问 Hermes”的查询解析会优先使用 `config.local.json` 中的 `llm.api_key/base_url`，其次读取 `DEEPSEEK_API_KEY/DEEPSEEK_BASE_URL`，调用失败时回落到内置中文/英文规则解析器。单篇论文问答和学习笔记默认使用本地已保存的标题、摘要与增强内容，证据不足时明确拒答，不要求外部 LLM。

## 每日抓取和邮件

抓取、合并并发送邮件：

```bash
python daily_pipeline.py --email
```

每日抓取来源和研究方向保存在 `search_config.json`：

```json
{
  "sources": ["arxiv", "openalex", "crossref", "semantic_scholar", "europe_pmc"],
  "keywords": "agent memory, retrieval augmented generation",
  "categories": ["cs.AI", "cs.CL"],
  "max_per_cat": 25,
  "days": 7
}
```

`keywords` 可填写任意学科方向或相关主题；`categories` 只用于约束 arXiv，其他来源按关键词和日期检索。多源请求允许单源失败降级，并按 DOI、arXiv ID、PMID、OpenAlex ID 和规范化标题去重。

预览邮件：

```bash
python email_digest.py --dry-run
```

给 Hermes 或自动任务使用：

```bash
python cron_wrapper.py
```

更详细的 agent 操作说明见 [HERMES_RUNBOOK.md](HERMES_RUNBOOK.md)。

## API

启动后可用：

- `GET /api/papers`
- `DELETE /api/papers`
- `GET /api/categories`
- `POST /api/categories`
- `GET /api/config`
- `POST /api/config`
- `GET /api/integrations`
- `POST /api/integrations`
- `GET /api/enrich/pending`
- `POST /api/enrich`
- `GET /api/status`
- `GET /api/sources`
- `POST /api/papers/download`
- `POST /hermes/search`
- `POST /hermes/ask`
- `POST /hermes/notes`
- `POST /zotero/add`
- `GET /zotero/collections`
- `GET /zotero/status?arxiv_id=ID`
- `GET /health`

`POST /hermes/search` 会读取当前 `sources` 配置；旧的四字段配置仍保持 arXiv 兼容。成功合并后会同步执行本地标签/评分增强，并在响应中返回各来源计数、失败源和 `enrichment`。

`POST /hermes/ask` 接受 `paper_id`/`arxiv_id` 与 `question`，只根据已保存论文上下文回答并返回证据字段；`POST /hermes/notes` 接受论文 ID 与可选 `focus`，返回 Markdown 学习笔记。摘要没有覆盖的问题会返回 `grounded=false`，不能当作全文结论。

`POST /api/papers/download` 只保存明确标记为开放获取且带合法 `pdf_url` 的论文。下载先写同目录 `.part` 并校验 PDF 后原子替换；401/403/404 不绕过权限。网页和桌面端可从卡片或详情保存，结果位于当前数据目录的 `PDFs/`。

`GET /api/integrations` 只返回脱敏后的 Zotero 状态；`POST /api/integrations` 只更新本机 `config.local.json` 中允许编辑的三个 Zotero 字段，并在共享锁内原子替换文件。

## 文件结构

```text
start.py                启动器、体检、配置向导、自动重载、bootstrap
local_discovery.py      本地 Zotero/Hermes 自动发现
hermes_integration.py   Hermes hook 安装器
papercatch_autostart.py Hermes hook 调用的后台启动脚本
zotero_server.py        HTTP 服务、Hermes 搜索、Zotero 入库
json_store.py           JSON 原子写入和跨进程读改写锁
config.py               本地配置读取
daily_pipeline.py       每日抓取和合并
paper_sources.py        公开多源检索、规范化、去重和失败降级
paper_agent.py          离线论文问答与学习笔记生成
paper_download.py       合法 OA PDF 校验、原子保存、去重和 manifest
email_digest.py         邮件日报
cron_wrapper.py         Hermes cron 包装入口
viewer/index.html       前端
desktop/                Windows 桌面壳、运行时和 PyInstaller 构建入口
tests/                  测试脚本
docs/                   项目文档（快速开始、运行手册等）
```

## 开发与测试

测试只使用 Python 标准库，并在临时目录和随机本机端口运行，不会删除真实论文：

```bash
python -m unittest discover -v

# 也可以单独运行
python tests/test_features.py
python tests/test_delete.py
```

测试覆盖损坏 JSON、原子替换、线程/多进程并发和隔离 HTTP 服务；测试和核心功能均不需要额外安装第三方依赖。
