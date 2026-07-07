# PaperCatch

PaperCatch 是一个本地优先的论文抓取、浏览、分类和 Zotero 入库工具。它默认假设用户会安装 Zotero 和 Hermes，所以启动器会先自动搜寻本机环境，再让用户确认少量必要信息。

## GitHub 拉下来后的推荐流程

```bash
cd D:\Codex\papercatch
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

`python start.py` 默认启用自动重载。后端或前端改动保存后，服务会自动重启。

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

也可以在 `python start.py --setup` 里填写。PaperCatch 能自动发现本地 user id 时会预填，API key 通常仍需要用户授权生成。

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

解析顺序：

1. 配置了 `HERMES_API_URL`：调用外部 Hermes/LLM API。
2. 配置了 `HERMES_COMMAND`：调用本地命令。
3. 都没有：使用内置中文/英文规则解析器。

所以即使 Hermes 暂时没接好，前端“问 Hermes”也可以先工作。

## 每日抓取和邮件

抓取、合并并发送邮件：

```bash
python daily_pipeline.py --email
```

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
- `GET /api/config/status`
- `POST /hermes/search`
- `POST /zotero/add`
- `GET /zotero/collections`
- `GET /zotero/status?arxiv_id=ID`
- `GET /health`

## 文件结构

```text
start.py                启动器、体检、配置向导、自动重载、bootstrap
local_discovery.py      本地 Zotero/Hermes 自动发现
hermes_integration.py   Hermes hook 安装器
papercatch_autostart.py Hermes hook 调用的后台启动脚本
zotero_server.py        HTTP 服务、Hermes 搜索、Zotero 入库
config.py               本地配置读取
daily_pipeline.py       每日抓取和合并
email_digest.py         邮件日报
cron_wrapper.py         Hermes cron 包装入口
viewer/index.html       前端
papers_database.json    本地论文库
HERMES_RUNBOOK.md       给 Hermes/agent 的运行文档
```

## 开发与测试

测试脚本需要额外安装 `requests`：

```bash
pip install requests
python test_features.py
python test_delete.py
```

注意：测试脚本不是项目运行必需的，核心功能零外部依赖。
