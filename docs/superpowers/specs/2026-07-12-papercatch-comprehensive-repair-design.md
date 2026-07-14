# PaperCatch 全面修复设计

日期：2026-07-12
状态：已批准，阶段 0+1、阶段 2 已完成，阶段 3 待实施
问题台账：[`docs/ISSUE_FIX_LOG.md`](../../ISSUE_FIX_LOG.md)

## 1. 背景

PaperCatch 当前能够完成本地启动、论文浏览、arXiv 搜索和基础 Zotero 操作，但隔离测试确认了安全暴露、并发丢数据、流水线静默成功、配置失效、测试假通过和前端布局问题。单独修补某一行会启用更多并发写入，可能放大数据损坏，因此需要按依赖顺序全面修复。

## 2. 目标

1. 本地配置和密钥不能通过 HTTP 静态路由读取。
2. 默认服务仅能从本机访问，浏览器前端继续正常工作。
3. 所有 JSON 更新均为原子写入；论文数据库的读改写支持跨进程互斥。
4. 抓取、合并、增强、邮件任一关键步骤失败时，调用方能得到非零退出码或明确 HTTP 错误。
5. 搜索配置、CLI 参数、Hermes/DeepSeek 配置与实际行为一致。
6. 论文只在成功写入数据库后标记为已抓取。
7. 测试使用临时数据和模拟外部服务，不删除真实论文、不调用真实 Zotero/SMTP/LLM。
8. 修复已确认的桌面溢出和移动端首屏可用性问题。
9. README、运行手册、API 列表和代码保持一致。
10. 每次发现、修改、验证都同步更新问题台账。

## 3. 非目标

- 不迁移到 Django、FastAPI、React 等新框架。
- 不引入常驻数据库服务；继续兼容现有 JSON 数据文件。
- 不在测试中发送真实邮件、写入真实 Zotero 或消耗真实 LLM 配额。
- 不在本轮提供公网部署能力。需要远程访问时应另行设计认证、TLS 和权限模型。
- 不改变现有论文 JSON 字段含义，避免破坏用户已有数据。

## 4. 总体方案

采用“保持轻量架构、收紧边界、集中存储、结构化失败”的方案：

```text
CLI / Browser / Hermes hook
        |
        v
Validated commands and HTTP routes
        |
        +--> Search adapters: Hermes API / Hermes command / DeepSeek / builtin
        +--> Zotero adapter
        +--> Email adapter
        |
        v
Shared application functions
        |
        v
Safe JSON store: atomic replace + cross-process lock
```

业务函数不再依赖导入即执行或静默子进程。CLI 只负责解析参数和映射退出码，HTTP handler 只负责校验请求、调用业务函数和生成响应。

## 5. 设计细节

### 5.1 问题台账

`docs/ISSUE_FIX_LOG.md` 是唯一问题记录入口：

- 新问题先分配 `PC-XXX`，记录证据和严重级别。
- 开始修改前改为 `修复中`。
- 代码完成后记录根因、文件和验证命令，改为 `已修复`。
- 覆盖测试与相关回归均通过后才能改为 `已验证`。
- 暂不处理的问题必须标记 `暂缓`，说明原因和恢复条件。

### 5.2 安全和 HTTP API（PC-001、PC-002、PC-010、PC-011）

- `zotero_server.py` 默认绑定 `127.0.0.1`，不再监听 `0.0.0.0`。
- 当前前端与 API 同源，删除 `Access-Control-Allow-Origin: *`。本机非浏览器客户端不受影响。
- 静态文件请求先 URL 解码，再 `resolve()`；目标必须位于 `viewer/` 内。
- 只有 `/` 可以回落到 `viewer/index.html`。未知 `/api/*`、`/zotero/*`、`/hermes/*` 返回 JSON 404。
- 请求体解析失败返回 JSON 400，不再转换成 `{}`。
- 分类和搜索配置增加结构校验、范围限制和未知字段处理。
- 所有 API 错误使用统一结构：`{"success": false, "error": {"code": "...", "message": "..."}}`。

### 5.3 共享 JSON 存储（PC-003、PC-024）

新增轻量存储模块，提供：

- `read_json(path, default)`：读取失败时抛出带路径的明确异常，不静默返回空数据库。
- `write_json_atomic(path, data)`：同目录临时文件、flush、fsync、`os.replace()`。
- `locked_update_json(path, default, updater)`：围绕完整读改写持有跨进程锁。
- Windows 使用 `msvcrt.locking`，POSIX 使用 `fcntl.flock`；锁文件与数据文件分离。
- 临时文件和锁文件加入 `.gitignore`，异常退出后临时文件可安全清理。

所有 `papers_database.json` 写路径迁移到该模块，包括服务、merge、enrich、classify 和 Zotero 状态回写。普通配置、状态和批次 JSON 至少使用原子写入。

`enrich.py` 通过“字段是否已计算”的明确条件判断更新；合法空标签不再导致每次重复写库。

### 5.4 抓取与每日流水线（PC-005 至 PC-009、PC-014、PC-015）

- `daily_pipeline.py` 的 CLI 默认值改为 `None`：显式参数优先，其次搜索配置，最后内置默认值。
- 把 categories、keywords、days、max-per-cat 全部传给搜索脚本。
- keywords 采用逗号分隔的 OR 词组；词组内部保留空格并作为 arXiv phrase 查询。
- 搜索脚本记录每个分类的成功/失败。全部失败返回非零；部分失败输出 warnings 并保留成功结果。
- 搜索结果和 `run_status.json` 使用实际 `--output` 路径，均原子写入。
- 搜索阶段不再提前修改 `crawled_ids.txt`。
- 合并数据库成功后，由流水线一次性提交本批 arXiv ID；失败时不标记，下一次可重试。
- merge、local enrich、mark pending、email 的 return code 全部检查，失败立即停止后续有副作用步骤。
- 脚本输出同时保留适合人读的文本和稳定的最终状态码。

### 5.5 自动增强和集成（PC-004、PC-012、PC-013、PC-018、PC-023）

#### 自动增强

- HTTP 搜索不再通过缺失导入的子进程隐式调用。
- 把 enrich 的核心逻辑改为可传入数据库路径的普通函数，服务端直接调用。
- 增强失败不影响已成功合并的论文，但 HTTP 响应必须包含 warning，台账和日志可追踪。

#### Hermes / DeepSeek

明确解析顺序：

1. `HERMES_API_URL`：POST `{"message": "..."}`，接收标准搜索计划 JSON。
2. `HERMES_COMMAND`：无 shell 执行，JSON 通过 stdin 输入，stdout 必须是标准搜索计划 JSON。
3. `llm.api_key/base_url` 或 `DEEPSEEK_*`：使用 OpenAI-compatible chat completions。
4. 内置中英文规则解析器。

所有适配器输出统一经过 schema 归一化和范围校验。失败时按顺序回退并返回 warnings，不再静默吞掉所有原因。

#### 配置

- 服务、CLI、doctor 统一调用 `config.load_config()`，保持默认值 → 本地文件 → 环境变量的优先级。
- 运行时读取配置，避免模块 import 时把凭据永久固化。

#### 邮件

- `--source new` 只从 `new_papers.json` 取得当批 ID，再从已增强数据库读取最终论文记录。
- 当批评分、标签和中文字段会进入邮件，排序基于增强后数据。
- 邮件禁用仍是正常跳过，但输出结构化 `skipped` 状态，与发送成功区分。

#### Hermes hook

- 首次启动 timeout 调整到覆盖 setup、启动和健康检查的上限。
- hook 保持幂等，失败写入明确日志并返回非零。

### 5.6 导入边界（PC-019）

- `classify_papers.py` 和 `cron_wrapper.py` 的执行逻辑移入 `main()`。
- 所有模块导入不得读写数据库、发送邮件、抓网或调用 `sys.exit()`。
- 业务函数接受路径和配置参数，便于临时目录测试。

### 5.7 测试体系（PC-016、PC-017）

使用 Python 标准库 `unittest`，避免给核心运行新增依赖：

- `test_storage.py`：原子写、损坏 JSON、跨进程/交错更新、空标签幂等。
- `test_server_security.py`：路径穿越、loopback 绑定、CORS、未知 API、损坏 JSON。
- `test_server_api.py`：论文 CRUD、配置 schema、增强 warning、状态码。
- `test_pipeline.py`：CLI 优先级、参数传递、步骤失败传播、抓取 ID 提交时机。
- `test_arxiv_search.py`：全失败、部分失败、关键词查询、自定义 output/status。
- `test_integrations.py`：Hermes API/command/DeepSeek 回退、Zotero/SMTP mock。
- `test_email_digest.py`：按当批 ID 从增强 DB 取数据和排序。
- 现有 feature/delete 测试改成临时目录和随机 loopback 端口；任一断言失败必须返回非零。

所有外部 HTTP、SMTP 和命令调用均 mock。集成 smoke 可额外启动随机端口服务，但不使用真实配置文件。

### 5.8 前端和可访问性（PC-020、PC-021）

- 日期 grid 子项增加 `min-width: 0` 和稳定宽度，桌面侧栏内不溢出。
- 手机端筛选器默认折叠，提供明确的筛选按钮和已启用条件数量。
- 筛选条件变化时清理隐藏选择，避免批量删除当前不可见论文。
- Modal 增加 `role="dialog"`、`aria-modal`、焦点进入/恢复和 Escape 关闭。
- API 结构化错误统一显示，不把 HTML 404 当 JSON 解析。

不做视觉重设计，保留当前中式界面和信息架构。

### 5.9 文档（PC-022）

- README 更新真实路径、API、配置优先级、监听边界和测试命令。
- QUICKSTART 与 HERMES_RUNBOOK 使用相同的解析顺序和 hook 行为。
- FRONTEND_SPEC 标注当前实现，不再声称可直接 `file://` 运行。
- API 列表由测试覆盖，避免再次出现不存在的端点。

## 6. 错误处理原则

- 不允许 `except Exception: pass` 隐藏关键失败。
- 可回退的外部集成错误进入 warnings；数据损坏、配置无效、全部抓取失败必须失败退出。
- HTTP handler 不暴露堆栈和密钥，只返回稳定 code/message；详细信息写本地日志。
- 数据文件损坏时停止写入，保留原文件，不用空默认值覆盖。

## 7. 兼容和迁移

- 继续使用现有 `papers_database.json`、`new_papers.json` 和配置结构。
- 首次使用安全存储前不主动重写数据库；第一次真实修改时采用原子替换。
- 不创建批量 `.bak`。涉及配置 schema 迁移时只保留一份带时间戳备份到 `codex-work/backups/`，验证后按用户清理规则处理。
- 新增的 lock/temp 文件不进入 Git，也不会改变论文 schema。

## 8. 实施阶段

### 阶段 0：测试基线和台账

- 把已复现问题转成失败测试。
- 修正测试退出码和真实数据隔离。

### 阶段 1：安全和 API 边界

- 修复路径穿越、loopback、CORS、请求校验和 API 404。

### 阶段 2：存储一致性

- 引入安全存储模块并迁移所有数据库写路径。
- 验证原子写和跨进程互斥后，再启用自动增强。

### 阶段 3：抓取与流水线

- 修复参数、失败传播、状态文件、已抓取提交时机和邮件数据层。

### 阶段 4：外部集成

- 接通 Hermes API/command/DeepSeek 回退链，统一配置和 hook 行为。
- 使用 mock 验证 Zotero、SMTP 和 LLM，不执行真实写操作。

### 阶段 5：前端和文档

- 修复布局、移动筛选、隐藏选择和 Modal 可访问性。
- 同步 README、QUICKSTART、RUNBOOK、FRONTEND_SPEC。

### 阶段 6：完整回归

- 运行全部单元/集成测试、语法检查、隔离 HTTP smoke 和桌面/移动浏览器检查。
- 清理测试服务、日志、截图、fixture 和 `codex-work/`。
- 逐项把台账状态更新为 `已验证` 或记录剩余风险。

## 9. 验收标准

- PC-001 至 PC-024 每项都有测试、修复或明确暂缓原因。
- 原始路径穿越请求不能读取 `viewer/` 外文件。
- 服务默认只监听 loopback，前端同源请求正常。
- 并发/交错写入测试不丢论文，损坏 JSON 不被空库覆盖。
- 全部 arXiv 请求失败时返回非零，合并失败后论文仍可重试。
- 显式 CLI 参数优先，分类/关键词真实进入搜索请求。
- Hermes、DeepSeek、邮件、Zotero 的 mock 行为和文档一致。
- 服务关闭时 feature tests 必须失败；delete tests 不碰真实数据。
- 前端桌面无日期溢出，手机可直接看到并控制筛选折叠。
- `git diff --check`、Python 测试、隔离 API smoke 和浏览器回归均通过。

## 10. 回滚策略

- 每个阶段保持独立、可审查的改动范围，不混入无关重构。
- 不提交、不推送，直到用户明确要求。
- 如果某阶段回归失败，只撤销该阶段新改动；不删除用户原有文件或真实数据。
- 数据层修改必须先通过临时目录和并发测试，禁止直接用真实论文库试错。
