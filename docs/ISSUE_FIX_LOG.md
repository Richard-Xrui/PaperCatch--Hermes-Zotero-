# PaperCatch 问题与修复台账

本文档持续记录项目中发现、修改和验证的问题。新增问题必须先登记，再修改代码；完成修复后必须附验证命令和结果。

## 状态约定

- `已发现`：静态检查发现，尚未完成动态复现。
- `已复现`：已有稳定复现证据。
- `修复中`：已经开始修改。
- `已修复`：代码已修改，尚未完成完整回归。
- `已验证`：覆盖测试和相关回归均通过。
- `暂缓`：明确记录原因和恢复条件。

## 问题总表

| ID | 级别 | 状态 | 问题 | 主要证据 |
| --- | --- | --- | --- | --- |
| PC-001 | Critical | 已验证 | 静态文件路径穿越可读取 `config.local.json` | `zotero_server.py` 静态路径 `unquote + resolve + relative_to`；原始、编码、反斜杠和 NUL 路径均返回 404 |
| PC-002 | Critical | 已验证 | 服务监听全部网卡、无鉴权且允许任意 Origin | 默认绑定 `127.0.0.1`；读写请求校验 loopback Host/Origin，变更请求要求 JSON，已移除 wildcard CORS |
| PC-003 | Critical | 已验证 | JSON 原地写入且没有跨进程锁，并发时会丢论文 | 共享 sidecar 锁覆盖完整读改写；线程/多进程和 enrich/merge 交错测试均不丢数据 |
| PC-004 | High | 已验证 | 搜索后的自动增强使用未导入的 `subprocess`，异常被吞掉 | 服务直接调用本地增强；成功、warning 降级和后续重试均有隔离 HTTP 覆盖 |
| PC-005 | High | 已验证 | 所有 arXiv 请求失败仍返回成功和“没有新论文” | 分类结果区分失败与合法空 feed；全部失败时退出 1 并在输出目录写入错误状态，部分失败仍保留成功结果 |
| PC-006 | High | 已验证 | 抓取 ID 在结果写入和数据库合并前落盘，失败后可能永久漏论文 | 搜索阶段不再写 `crawled_ids.txt`；结果写入或 merge 失败均不提交 ID，成功重跑会在 merge 后幂等提交 |
| PC-007 | High | 已验证 | 搜索分类和关键词配置没有传给抓取脚本 | `daily_pipeline.py` 现已显式传递 `--categories/--keywords`；`arxiv_daily_search.py` 规范化关键词并生成结构化 arXiv 查询 |
| PC-008 | High | 已验证 | 显式 CLI 默认值会被配置覆盖 | `daily_pipeline.py` 已恢复显式 CLI > 配置 > 内置默认；`--days 0 --max-per-cat 25` 保持显式值 |
| PC-009 | Medium | 已验证 | 自定义 `--output` 时 `run_status.json` 仍读取默认输出 | 结果、`run_status.json` 与 `crawled_ids.txt` 查询统一使用解析后的输出目录；相对/绝对路径和旧默认结果隔离测试通过 |
| PC-010 | High | 已验证 | 损坏 JSON 的配置请求返回成功并清空两份配置 | malformed UTF-8、JSON、Content-Length、空体和 schema 错误均返回 400 且文件不变 |
| PC-011 | Medium | 已验证 | 未知 API 和文档中的 `/api/config/status` 返回 `200 HTML` | 未知 GET/POST/DELETE API 返回结构化 JSON 404；静态缺失资源返回 404 |
| PC-012 | High | 已确认 | `HERMES_API_URL/HERMES_COMMAND` 可配置但搜索链路没有消费者 | `config.py:43-53` 与 `zotero_server.py:133-219` 不一致 |
| PC-013 | High | 已复现 | 邮件读取未增强的 `new_papers.json`，丢失评分、标签和中文字段 | `daily_pipeline.py:92-102` 与 `enrich.py:101-120` |
| PC-014 | High | 已验证 | daily pipeline 忽略 enrich 子进程失败 | enrich 非零/超时返回结构化 `STAGE_ERROR` 并阻断邮件和成功报告；失败及成功顺序回归通过 |
| PC-015 | Medium | 已验证 | merge 忽略 `enrich --mark-pending` 失败 | 保留已合并数据库并返回非零 `PENDING_ERROR`；隔离回归通过 |
| PC-016 | High | 已验证 | `test_features.py` 全部失败时仍退出 0 | 标准 `unittest` 断言失败返回非零；直接入口回归测试覆盖 |
| PC-017 | High | 已验证 | `test_delete.py` 直接删除真实论文且不恢复 | 所有删除测试使用临时目录、随机 loopback 端口和假论文 |
| PC-018 | Medium | 已验证 | 服务端配置加载绕开共享加载器，空本地字段阻断环境变量回退 | 服务统一使用共享加载器；隔离 subprocess 验证非空环境变量覆盖空文件字段并跟随桌面数据目录 |
| PC-019 | Medium | 已验证 | `classify_papers.py` 和 `cron_wrapper.py` 导入即执行写操作 | 两个入口均已使用显式 `main()`/守卫；导入零副作用、退出码和超时回归通过 |
| PC-020 | Low | 已验证 | 桌面端日期结束输入框超出侧栏约 28px | 日期输入改为纵向排列；1440x900 Edge DOM 实测溢出 `0px` |
| PC-021 | Low | 已验证 | 手机首屏被完整筛选面板占据，主要论文内容需要长距离滚动 | 小于等于 1000px 默认折叠筛选；390x844 首卡顶部从约 `1285px` 降至 `456px` |
| PC-022 | Medium | 已验证 | README、前端规格和实际 API/行为存在多处不一致 | 使用文档与当前服务端/前端行为对齐；契约测试覆盖前端实际使用的全部 fetch 端点并拒绝旧静态运行说明 |
| PC-023 | Medium | 已确认 | Hermes hook 超时 10 秒，小于首次 setup 和健康检查上限 | `hermes_integration.py:51-53`、`papercatch_autostart.py` |
| PC-024 | Low | 已验证 | 无标签论文每次 enrich 都会重复写数据库 | 按计算结果差异写入；合法空标签第二次增强返回 0 且不替换数据库 |
| PC-025 | Medium | 已验证 | 筛选后隐藏论文仍保留在批量选择集合中，批量操作可能作用于当前不可见论文 | 筛选后按可见 ID 收敛选择集合；Node 行为测试覆盖隐藏选择清理 |
| PC-026 | Medium | 已验证 | 三个 Modal 缺少对话框语义和一致的焦点进入/恢复管理 | 三个 dialog 已有语义、初始焦点、Escape/背景关闭、焦点恢复及 Tab/Shift+Tab 循环，契约测试覆盖 |
| PC-027 | Medium | 已验证 | 项目只有浏览器入口，缺少独立桌面窗口、随机端口和关闭时回收后端的生命周期 | pywebview/PyInstaller onedir 已构建并启动；窗口响应正常、随机 loopback `/health` 成功，启动失败可写日志并弹窗 |
| PC-028 | High | 已验证 | 冻结打包后若沿用源码路径，可写 JSON 会落入只读或临时 bundle，升级/重启后数据不可靠 | 实包从 bundle 读取 viewer，在 `%LOCALAPPDATA%\PaperCatch` 非覆盖 seed 配置；数据/资源路径隔离测试通过 |
| PC-029 | Low | 已验证 | 页面未声明 favicon，浏览器每次加载都会请求 `/favicon.ico` 并产生 404 噪声 | HTML 使用 data favicon，不再需要静态 `/favicon.ico` 请求；前端契约与全量回归通过 |
| PC-030 | High | 已验证 | 非强制本地增强会覆盖人工或 LLM 已写入的标签、评分和评分信号 | 保留已有增强和合法空标签，仅补缺失/新论文占位字段；人工结果、新论文、force 和幂等测试通过 |
| PC-031 | Medium | 已验证 | 独立桌面端没有图形化 Zotero 配置入口，用户只能手工编辑 `%LOCALAPPDATA%\PaperCatch\config.local.json` | 新增脱敏 `/api/integrations` 与设置表单；5 项隔离 API 测试及三视口 mock 保存通过，密钥未回填 DOM |
| PC-032 | Low | 已验证 | 移动端筛选折叠控件只有视觉开关，没有同步 `aria-expanded` 和展开/收起文案 | 初始化与 change 均同步状态；390x844 实测 `false → true`，展开/收起文案和契约测试通过 |
| PC-033 | Medium | 已验证 | 手机论文卡片的状态徽标与标题横向争抢空间，长英文标题被压成接近一词一行 | 徽标移至标题下一行；390x844 标题列宽约 295px，最长样例 2 行且页面无横向溢出 |
| PC-034 | Medium | 已验证 | 设置 Modal 滚动到底部后关闭再打开会保留旧滚动位置，顶部标题和抓取设置被裁掉 | `openModal()` 在显示后重置 backdrop；1440/1024/390 三视口重开 `scrollTop=0` |
| PC-035 | Low | 已验证 | 手机端 toast 固定在右下角，会短暂遮挡设置弹窗底部的“保存 Zotero 设置”按钮 | 窄屏通知改为动态高度顶部状态条；390x844 toast 完整可见，与保存按钮重叠面积为 0 |
| PC-036 | Low | 已验证 | Windows 桌面窗口仍使用通用标题和不一致的启动背景，任务栏品牌缺失且首帧可能闪色 | 窗口标题/背景已与 viewer 对齐；入口契约通过，重建实包 `MainWindowTitle=纸上得来 · PaperCatch` 且 `/health=ok` |
| PC-037 | High | 已验证 | Windows 多进程 JSON 更新偶发在 `os.replace` 返回 `WinError 5`，该 worker 更新失败 | 仅对 Windows 临时访问/共享冲突做有界重试；确定性测试、连续 12 轮压力和 `106/106` 全量回归通过 |
| PC-038 | Medium | 已验证 | 顶栏搜索图标与占位文字重叠，且搜索框圆角、背景和字号退化为普通输入框样式 | 通用文本输入排除 `.search-input`；实包 Edge 两视口图标文字间距 10.61px、圆角 999px、无溢出或运行错误 |
| PC-039 | High | 已验证 | `BackendService.start()` 在线程已退出后仍复用旧 URL，桌面壳可能继续指向失效后端 | 隔离 RED 测试确认失活后端会被回收并重新绑定新 loopback URL；桌面运行时与全量回归通过 |
| PC-040 | High | 已验证 | 每日抓取仅覆盖 arXiv，且内置智能体不能针对论文问答或生成学习笔记 | 五源聚合、跨源/跨次去重、论文问答、Markdown 笔记、合法 OA PDF 保存 API/UI 与完整回归通过 |
| PC-041 | Medium | 已验证 | 保存 OA PDF 时卡片没有显示 loading 且卡片/详情按钮未禁用，用户可能误以为点击无效并重复操作 | 卡片/详情均跟随 `state.downloading` 显示“保存中…”并禁用；运行期契约和两视口 Edge smoke 通过 |

## 问题分类索引

以下索引只负责按领域归类，状态和证据以“问题总表”为准：

| 领域 | 问题 ID | 覆盖内容 |
| --- | --- | --- |
| 安全与 HTTP API | PC-001、PC-002、PC-010、PC-011 | 路径边界、loopback、CORS、请求校验和 API 404 |
| 存储与数据一致性 | PC-003、PC-024、PC-037 | JSON 原子写、跨进程锁、Windows 替换稳定性和 enrich 幂等性 |
| 内容增强 | PC-030、PC-040 | 本地启发式增强不得覆盖人工或 LLM 结果；基于论文证据回答问题和生成学习笔记 |
| 抓取与每日流水线 | PC-005 至 PC-009、PC-014、PC-015、PC-040 | arXiv 失败传播、参数、状态文件、抓取 ID、步骤退出码和公开多源聚合 |
| 外部集成与配置 | PC-004、PC-012、PC-013、PC-018、PC-023 | 自动增强、Hermes/DeepSeek、邮件数据、配置优先级和 hook 超时 |
| 测试可靠性与数据隔离 | PC-016、PC-017 | 测试退出码、临时数据和真实论文保护 |
| 导入边界与文档 | PC-019、PC-022 | 导入副作用、README/API/运行手册一致性 |
| 前端体验与可访问性 | PC-020、PC-021、PC-025、PC-026、PC-029、PC-032 至 PC-035、PC-038、PC-041 | 响应式布局、移动筛选、隐藏选择、Modal 访问语义、静态资源噪声、控件状态、卡片标题宽度、弹窗滚动恢复、通知遮挡、搜索框级联和 PDF 保存反馈 |
| 桌面运行与打包 | PC-027、PC-028、PC-036、PC-039 | pywebview 生命周期、随机 loopback 端口、PyInstaller、可写数据目录、窗口品牌和后端失活恢复 |
| 桌面配置与集成 | PC-031 | 脱敏 Zotero 配置读取、保存和桌面端可用入口 |

## 修改记录

修改时按以下格式追加，不覆盖历史记录：

```text
### YYYY-MM-DD HH:mm - PC-XXX

- 状态：修复中 / 已修复 / 已验证
- 根因：
- 修改文件：
- 修改内容：
- 验证命令：
- 验证结果：
- 剩余风险：
```

### 2026-07-12 - 初始问题归档

- 状态：已完成
- 内容：根据隔离后端、流水线、浏览器和安全测试建立 PC-001 至 PC-024。
- 数据安全：所有写入、删除和抓取测试均在临时副本或内存 fixture 中完成。
- 清理结果：测试服务、Edge 调试进程、截图、日志、脚本和 `codex-work/` 已删除。

### 2026-07-12 - 详细浏览器回归（基线，无业务代码修改）

- 状态：已复现
- 测试环境：隔离 PaperCatch 服务 `http://127.0.0.1:18766`，无头 Edge，视口 `1440x900`、`1024x768`、`768x1024`、`390x844`；内置 Browser 控制接口在本会话未暴露，因此使用本地 CDP 脚本完成同等 DOM、交互、截图和网络检查。
- 验证命令：`node codex-work/scripts/detailed-ui-test.cjs`
- 页面加载：标题为“纸上得来 · PaperCatch”，首屏有 15 篇论文，框架错误覆盖层不存在；控制台错误/警告、页面异常和失败请求均为 0。
- 交互结果：关键词筛选、恢复筛选、评分滑块、详情/Hermes/设置三个弹窗均能打开；Hermes 弹窗能把焦点放入输入框；Escape 能关闭弹窗。
- 新增问题：PC-025（隐藏选择）和 PC-026（Modal 可访问性）稳定复现。
- 已确认问题：PC-020 的 1440px 日期结束框向侧栏外溢 `27.96875px`；PC-021 的 390x844 首屏中首张论文卡片顶部为 `1284.59375px`，完整筛选面板占据首屏。
- 响应式：四个视口均无横向页面溢出；`1024px` 首张论文卡片可见，`768px` 和 `390px` 因侧栏堆叠需长距离滚动；移动端没有筛选折叠按钮。
- 备注：一条隔离 fixture 的中文标题在截图中显示为问号，已通过 Unicode 转义复核为测试 harness 编码问题，未登记为项目缺陷。
- 清理：沙箱服务、Edge 调试进程、截图、日志、fixture、脚本和整个 `codex-work/` 已删除；未访问真实 Zotero、SMTP 或 LLM。

### 2026-07-12 - 阶段 0+1 启动

- 状态：修复中
- 范围：PC-001、PC-002、PC-010、PC-011、PC-016、PC-017。
- 顺序：先把现有脚本测试改为标准库 `unittest` 和临时数据，再写安全回归失败测试，最后修改 HTTP 服务。
- 隔离：只使用临时目录、随机 loopback 端口和假论文数据；不读取或覆盖真实论文库，不调用 Zotero、SMTP、arXiv 或 LLM。
- 计划：`docs/superpowers/plans/2026-07-12-papercatch-stage-0-1-security-tests.md`。
- RED 证据：`python -m unittest tests.test_server_security -v` 运行 13 个用例，得到 `failures=13, errors=0`；每个失败均由当前缺陷触发，没有语法、导入或测试基座错误。

### 2026-07-12 - 阶段 0+1 实施完成并验证

- 状态：已验证
- 修改文件：`zotero_server.py`、`viewer/app.js`、`tests/__init__.py`、`tests/server_harness.py`、`tests/test_features.py`、`tests/test_delete.py`、`tests/test_server_security.py`、`tests/test_test_entrypoints.py`、`tests/test_frontend_contract.py`、`README.md`。
- 安全边界：静态文件只允许 `viewer/` 内真实文件；未知 API 统一 JSON 404；默认只监听 loopback；所有 GET/POST/DELETE/OPTIONS 校验 loopback Host；POST/DELETE 需 `application/json` 且拒绝非本机 Origin。
- 请求校验：拒绝损坏 UTF-8/JSON/Content-Length、空正文、错误顶层类型、未知配置字段、无效 arXiv 分类/数字范围，以及 Hermes/enrich/Zotero/delete 的错误嵌套字段；失败不写文件、不调用外部服务。
- 错误契约：API 顶层错误统一为 `error.code/message`；前端保留旧字符串兼容并支持嵌套错误显示。
- 当前验证：`python -m unittest discover -v` 为 `50/50 OK`；20 个 Python 文件通过 AST/compile；`node --check viewer/app.js`、两个直接脚本入口、loopback server factory 和 `git diff --check` 均通过。
- 剩余风险：PC-003 至 PC-009、PC-012 至 PC-015、PC-018 至 PC-026 的存储并发、流水线、集成和前端体验修复仍未开始；本阶段没有访问真实 Zotero、SMTP、arXiv 或 LLM。

### 2026-07-12 - 阶段 2 存储一致性启动

- 状态：修复中
- 范围：PC-003、PC-004、PC-024；同时迁移阶段内触及的 JSON 写入并为 `classify_papers.py` 建立可测试导入边界。
- 基线验证：`python -m unittest discover -v` 为 `50/50 OK`，`git diff --check` 无空白错误。
- 实施顺序：先用失败测试定义严格读取、原子替换和跨进程锁，再迁移论文库写路径与幂等增强，最后恢复搜索后直接增强。
- 隔离：仅使用临时目录、假论文和随机 loopback 端口；不读取或覆盖真实论文库，不调用 Zotero、SMTP、arXiv、Hermes 或 LLM。
- 计划：`docs/superpowers/plans/2026-07-12-papercatch-stage-2-storage-consistency.md`。

### 2026-07-12 - 阶段 2 存储一致性完成并验证

- 状态：已验证
- 根因：服务端 `threading.Lock` 不能覆盖 `enrich/merge/classify` 独立进程；原地写会先截断文件；损坏 JSON 又被静默当作空库。空标签 `[]` 同时被误判为“尚未计算”，搜索后增强的 `NameError` 被 `except Exception: pass` 吞掉。
- 修改文件：新增 `json_store.py`；修改 `zotero_server.py`、`enrich.py`、`merge_papers.py`、`classify_papers.py`、`config.py`、`arxiv_daily_search.py`、`.gitignore`；新增 5 个阶段 2 测试文件。
- 存储修复：严格读取只对缺失文件使用独立默认值；同目录临时文件执行 flush/fsync/replace；Windows 使用稳定字节锁 sidecar，POSIX 使用 flock；相等更新不替换文件。
- 写路径迁移：服务合并、增强回写、Zotero 状态、删除、每日 merge、local/apply enrich 和分类全部在共享锁内完成读改写；配置、搜索输出、状态和 pending JSON 使用原子写。
- 自动增强：HTTP 搜索直接调用 `local_enrich` 和 `mark_pending`；失败不回滚已合并论文，返回结构化 warning，并在后续相同搜索中重试。
- RED 证据：`tests.test_json_store` 初次运行因缺少 `json_store` 导入失败；`tests.test_enrich` 初次运行 3 个用例均因不支持 `db_path` 报错，确认原接口无法隔离且空标签逻辑尚未修复。
- 验证命令：`python -m unittest discover -v`、内存 AST/compile、`git diff --check`。
- 验证结果：`68/68 OK`；26 个 Python 文件编译通过；无空白错误。线程、多进程、损坏 JSON、replace 失败、交错 enrich/merge、空标签幂等、自动增强成功/失败/重试均覆盖。
- 隔离与外部调用：仅使用 `TemporaryDirectory`、假论文和随机 loopback 端口；未调用真实 Zotero、SMTP、arXiv、Hermes 或 LLM。
- 剩余风险：`crawled_ids.txt` 的提交时机和自定义 output/status 属阶段 3；Hermes allowlist JSON 的读改写将在阶段 4 迁移；单文件原子写不提供多文件事务，也不承诺断电后的目录项持久性。

### 2026-07-13 - 前端与独立桌面端完成并验证

- 状态：已验证。
- 范围：PC-018、PC-020、PC-021、PC-025 至 PC-030。
- 前端：日期输入无侧栏溢出；单栏布局默认折叠筛选；隐藏论文选择自动清理；三个 Modal 补齐 dialog 语义、进入/恢复焦点和 Tab 循环；data favicon 消除静态 404。
- 桌面：新增 `desktop/` pywebview 壳、随机 loopback 后端、关闭回收、PyInstaller onedir、启动失败日志/MessageBox，以及源码数据迁移说明。静态资源和 `%LOCALAPPDATA%\PaperCatch` 可写数据已分离。
- 数据修复：服务配置统一共享加载器，环境变量不再被空文件字段覆盖；非强制本地增强不再覆盖人工/LLM 字段。
- 验证命令：`python -m unittest discover -v`、`node --check viewer/app.js`、32 个 Python 文件内存编译、`git diff --check`、`desktop/build.ps1` 和实包 `/health`。
- 验证结果：`92/92 OK`；前端契约 8 项、桌面运行时 11 项均包含在全量回归；PyInstaller 6.21.0 构建成功；`dist/PaperCatch/PaperCatch.exe` 启动后窗口响应且随机端口健康。
- 浏览器说明：内置 Browser 控制工具在本会话未暴露；已有真实 Edge DOM 几何验证覆盖 1440x900 和 390x844。额外 Playwright 脚本因工作区缺少 `playwright-core` 未运行，未据此声称截图验收。
- 外部边界：未调用真实 Zotero、SMTP、arXiv、Hermes 或 LLM；未提交或推送。

### 2026-07-13 - PC-035 移动端通知遮挡复现

- 状态：已复现。
- 根因：全局 toast 在所有视口都固定于右下角；窄屏设置弹窗滚动到底部后，最后一个主按钮也位于同一区域，没有为通知层预留空间。
- 复现环境：系统 Edge，`390x844`，打开设置并滚动到 Zotero 集成，保存 mock 配置后观察成功通知。
- 复现结果：toast 覆盖约半个“保存 Zotero 设置”按钮，持续约 3.2 秒；桌面与平板视口未见同等程度遮挡。
- 数据边界：只使用隔离 mock 配置 `qa-only-key / 9876543 / PaperCatch/QA`，没有读取或写入真实 Zotero 配置。

### 2026-07-13 - PC-031 至 PC-035 完成并验证

- 状态：已验证。
- 修改文件：`zotero_server.py`、`viewer/index.html`、`viewer/app.js`、`tests/test_server_integrations.py`、`tests/test_frontend_contract.py`、`README.md`、`desktop/README.md`、文档索引与阶段计划。
- 配置与安全：新增 `/api/integrations` GET/POST；读取只返回 `configured/user_id/default_collection`，保存严格校验并在共享锁内原子替换；空 API Key 保留已有密钥，非空环境变量继续覆盖文件运行值。
- 前端：设置 Modal 可填写 Zotero User ID、密码型 API Key 和默认 Collection；移动筛选同步可访问状态；手机徽标不再挤压标题；Modal 重开回顶；窄屏 toast 改为动态高度顶部状态条并补充 live region 语义。
- Edge QA：`1440x900`、`1024x768`、`390x844` 三视口均无横向溢出、控制台错误、页面异常、失败请求或 HTTP 4xx/5xx；三类 Modal 的语义、焦点循环、Escape 和焦点恢复通过。
- 几何结果：手机长标题宽约 `295px`、最长样例 2 行；设置重开 `scrollTop=0`；toast 完整可见，与“保存 Zotero 设置”按钮重叠面积为 `0`。
- 验证命令：`python -m unittest discover -v`、33 个 Python 文件内存编译、`node --check viewer/app.js`、`git diff --check`、`node codex-work/scripts/detailed-ui-qa.cjs`。
- 验证结果：全量 `103/103 OK`；前端契约 `14/14 OK`；语法和空白检查通过；UI mock 写入共 3 次，均未触及真实配置。
- 桌面实包：最新 onedir 已重建；`PaperCatch.exe` 启动后窗口响应，随机 loopback `/health` 返回 `ok/PaperCatch`，首页加载 `app.js?v=20260713.3`，`/api/integrations` 仅暴露三个脱敏字段且不含 `api_key`。
- 剩余风险：未调用真实 Zotero Web API；本地 `config.local.json` 仍由操作系统账户权限保护，发布包尚无安装器、代码签名和自定义图标。

### 2026-07-13 - PC-022 使用文档部分校正

- 状态：已确认（部分修复，未关闭）。
- 修改文件：`README.md`、`docs/HERMES_RUNBOOK.md`、`docs/QUICKSTART.md`、`desktop/README.md`、服务 docstring 和文档索引。
- 修改内容：新增桌面 Zotero 图形配置和 `/api/integrations` 说明；把 Hermes 搜索的实际解析顺序改为 `llm.* → DEEPSEEK_* → 内置规则`，明确 `HERMES_API_URL/HERMES_COMMAND` 尚未接入该调用链。
- 保留状态原因：`docs/FRONTEND_SPEC.md` 仍把前端描述为直接读取静态 JSON，并包含未实现或已变化的功能与验收项，需要单独按当前产品行为重写后才能关闭 PC-022。

### 2026-07-13 - PC-022 前端规格重写启动

- 状态：修复中。
- 根因：`docs/FRONTEND_SPEC.md` 仍是早期需求草稿，错误描述静态 JSON/`file://` 运行方式，并把收藏、高亮、自动刷新等未实现项写成当前功能。
- 修改范围：以 `viewer/index.html`、`viewer/app.js` 和 `zotero_server.py` 为事实来源，重写数据来源、页面行为、API、安全边界、响应式规则和验收标准。
- 边界：只修改规范与相关索引，不改变业务代码，不调用任何真实外部服务。

### 2026-07-13 - PC-022 前端规格完成并验证

- 状态：已验证。
- 修改文件：`docs/FRONTEND_SPEC.md`、`tests/test_frontend_contract.py`、`docs/README.md`、前端与桌面阶段计划、项目记忆。
- 修改内容：按当前服务托管架构重写运行方式、论文字段、搜索/筛选/批量操作、三类 Modal、通知、HTTP API、Zotero 脱敏规则、响应式断点、已知限制和验收项。
- 防回归：从 `viewer/app.js` 提取实际 `fetch()` 路径，要求每个端点都在前端规格中出现；同时拒绝早期 `viewer/run_viewer.py`、静态 JSON 和独立静态托管表述。
- 验证命令：`python -m unittest tests.test_frontend_contract -v`、`python -m unittest discover -v`、`node --check viewer/app.js`、`git diff --check`、旧表述静态扫描。
- 验证结果：前端契约 `15/15 OK`，全量 `104/104 OK`，旧架构关键词匹配 0，JavaScript 与空白检查通过。
- 外部边界：只读取源代码并运行隔离测试；没有调用真实 Zotero、SMTP、arXiv、Hermes 或 LLM。

### 2026-07-13 - PC-036 桌面窗口品牌复现

- 状态：已复现。
- 现象：已启动实包的 Windows 主窗口标题为 `PaperCatch`，没有页面使用的“纸上得来”品牌；WebView 内容就绪前的背景色与页面首帧底色不同。
- 根因：`desktop/app.py` 在 `create_window()` 中硬编码通用标题和旧背景色，没有与 `viewer/index.html` 的标题及 `--xuan-white` 保持一致。
- 计划：增加不依赖真实 GUI 的桌面入口契约测试，再统一窗口标题和背景；尺寸、随机端口与关闭回收行为保持不变。

### 2026-07-13 - PC-037 Windows 原子替换偶发拒绝访问

- 状态：已复现。
- 触发环境：Windows、`spawn` 多进程、4 个 worker 竞争同一 JSON 计数器。
- 失败证据：一个 worker 在 `os.replace(temp, target)` 收到 `[WinError 5] 拒绝访问` 并退出 1；全量结果为 `104 passed / 1 failed`。
- 数据影响：原文件没有被截断或写坏，但失败 worker 的更新没有提交，调用方只能收到 `JsonStoreError`。
- 下一步：先重复运行竞争测试确认频率，再检查 Windows sidecar 锁范围、文件句柄关闭和可安全重试的错误边界；不得用吞异常掩盖失败。

### 2026-07-13 - PC-036、PC-037 完成并验证

- 状态：已验证。
- PC-036 修改：`desktop/app.py` 的窗口标题统一为“纸上得来 · PaperCatch”，启动背景统一为页面 `--xuan-white` 的 `#faf8f3`；窗口尺寸、最小尺寸、随机端口和关闭回收保持不变。
- PC-036 验证：新增桌面入口契约；桌面运行时 `12/12 OK`；重建实包的 Windows `MainWindowTitle` 与品牌一致，窗口响应且随机 loopback `/health=ok`。
- PC-037 根因边界：sidecar 锁能串行应用进程，但 Windows 仍可能因外部扫描或共享状态短暂拒绝替换；本次证据不能归因到某个具体进程，`os.replace` 的临时 `WinError 5/32/33` 原先会直接上抛。
- PC-037 修改：对 Windows `EACCES` 及 `WinError 5/32/33` 使用 10ms 至 320ms 的有界退避；非 Windows、非临时错误和重试耗尽仍原样上抛并清理临时文件。
- RED 证据：修复前确定性测试报 `JsonStoreError`；相同多进程竞争测试 8 轮失败 2 轮，失败率 25%。
- 验证结果：确定性重试/永久错误测试通过；修复后多进程压力连续 `12/12` 通过；全量 `106/106 OK`；`git diff --check` 通过。
- 数据与外部边界：全部使用 `TemporaryDirectory` 和假计数器；没有读取或修改真实论文、Zotero、SMTP、arXiv、Hermes 或 LLM 数据。

### 2026-07-13 - PC-038 搜索框样式重叠复现

- 状态：已复现。
- 用户可见现象：搜索框左侧放大镜与“搜索标题、作者、摘要、标签…”占位文字发生重叠，控件也不再呈现设计中的胶囊形态。
- 根因：`.search-input` 先声明专用 `padding/background/border-radius/font-size`，后续通用 `input[type="text"]` 具有同等层级并因源码顺序覆盖这些属性。
- 计划：从通用文本输入选择器中显式排除 `.search-input`，增加级联契约测试，并用真实 Edge 在桌面和手机视口测量图标与文字起始位置的间距。

### 2026-07-13 - PC-038 搜索框样式完成并验证

- 状态：已验证。
- RED 证据：新增级联契约测试在旧代码上失败，确认通用 `input[type="text"]` 选择器没有排除 `.search-input`。
- 修改文件：`viewer/index.html`、`tests/test_frontend_contract.py`、问题台账、项目记忆和前端/桌面计划。
- 修改内容：通用文本输入规则改为 `input[type="text"]:not(.search-input)`，恢复搜索框专用的 40px 左内边距、胶囊圆角、暖色背景和 14.4px 字号。
- Edge QA：系统 Edge 直接访问重建实包的随机 loopback 地址；`1440x900` 与 `390x844` 的图标到文字起点间距均为 `10.609375px`，圆角 `999px`，横向溢出为 0。
- 交互与运行：输入关键词后结果计数为 1，清空按钮恢复空值；页面非空、标题正确，无框架错误层、控制台错误、页面异常、失败请求或 HTTP 4xx/5xx。
- 验证结果：前端契约 `16/16 OK`，全量 `107/107 OK`，最新 onedir EXE 已重建并通过实包 UI 验证。
- 外部边界：只使用 mock 论文数据；没有调用真实 Zotero、SMTP、arXiv、Hermes 或 LLM。

### 2026-07-13 - PC-039 桌面后端失活后复用旧 URL

- 状态：已验证。
- 根因：`BackendService.start()` 只要 `_server` 和 `_url` 已存在就直接返回缓存地址，没有校验工作线程是否仍存活；一旦后台线程提前退出，后续调用会继续复用失效 loopback URL。
- 修改文件：`desktop/runtime.py`、`tests/test_desktop_runtime.py`、`docs/ISSUE_FIX_LOG.md`、`docs/README.md`、`docs/superpowers/plans/2026-07-13-papercatch-frontend-desktop.md`、`CODEX_PROJECT_MEMORY.md`。
- 修改内容：新增隔离 RED 测试，复现 `serve_forever()` 退出后第二次 `start()` 仍返回旧地址；运行时在检测到陈旧 `server/thread/url` 组合时先回收旧实例，再重新绑定新的 loopback 端口；`stop()` 复用同一回收逻辑。
- 验证命令：`python -m unittest tests.test_desktop_runtime.DesktopRuntimeTests.test_backend_start_replaces_stale_server_after_worker_thread_exits -v`、`python -m unittest tests.test_desktop_runtime -v`、`python -m unittest discover -v`、`git diff --check`。
- 验证结果：RED 用例先失败后通过；桌面运行时 `13/13 OK`；全量 `108/108 OK`；`git diff --check` 通过，未触及 `viewer/`、真实 Zotero、SMTP、arXiv 或 LLM。
- 剩余风险：当前修复覆盖“后端线程已退出或启动状态陈旧后重新启动”的桌面壳路径；未额外引入 GUI 实包长时稳定性巡检，后续若出现真实 `pywebview` 进程级别异常，仍需结合实包日志继续排查。

### 2026-07-13 - PC-039 实包收尾验证

- 状态：已验证。
- 范围：只验证最新 onedir `dist\PaperCatch` 是否已包含 PC-039 修复，不继续扩展到新问题。
- 构建方式：按项目记忆使用 `uv run --no-project --python 3.11 --with pywebview --with pyinstaller -- powershell -ExecutionPolicy Bypass -File desktop/build.ps1 -Python python` 重建。
- 进程与端口：先确认并关闭旧的本项目 `dist\PaperCatch\PaperCatch.exe` 实例，再启动新包；本次新实例 PID `39152`，随机 loopback 端口 `62194` 仅作当次证据，不写入固定配置。
- 实包验证：窗口标题为“纸上得来 · PaperCatch”且 `Responding=True`；`GET /health` 返回 `200` 和 `{"status":"ok","service":"PaperCatch"}`；首页返回 `200`，包含 `<title>纸上得来 · PaperCatch</title>`、`app.js?v=` 与 `id="searchInput"`。
- 冒烟命令：`python -m unittest tests.test_desktop_runtime.DesktopRuntimeTests.test_backend_start_replaces_stale_server_after_worker_thread_exits -v`、`python -m unittest tests.test_desktop_runtime -v`。
- 冒烟结果：focused `1/1 OK`，桌面运行时 `13/13 OK`；新实包保持运行，`build/` 和仓库内 `__pycache__/` 已清理，保留 `dist\PaperCatch` 作为可分发产物。

### 2026-07-13 - PC-007、PC-008 参数透传与优先级完成并验证

- 状态：已验证。
- 根因：`daily_pipeline.py` 只把关键词写进未被消费的环境变量，没有显式传给 `arxiv_daily_search.py`；同时显式 `--days 0 --max-per-cat 25` 曾被 `search_config.json` 覆盖。
- 修改文件：`daily_pipeline.py`、`arxiv_daily_search.py`、`tests/test_daily_pipeline.py`、`tests/test_arxiv_daily_search.py`。
- 修改内容：`daily_pipeline.py` 现显式传递 `--categories` 与 `--keywords`；`arxiv_daily_search.py` 新增 `--keywords`，对逗号/中文逗号分隔词组做去空去重，保留词组内部空格，并用 `urllib.parse.urlencode()` 生成 `cat:<category> AND (all:<keyword1> OR all:<phrase2>)` 查询；空关键词保持纯分类查询。
- 验证命令：`python -m unittest tests.test_daily_pipeline tests.test_arxiv_daily_search -v`、`python -m unittest discover -v`、`git diff --check`。
- 验证结果：聚焦 `8/8 OK`；全量 `116/116 OK`；`git diff --check` 通过，仅有工作树既存 LF/CRLF warning。
- 剩余风险：本批仅收口 PC-007/008；未扩展到 PC-005/006/009、PC-014/015、PC-019 或 PDF 下载。

### 2026-07-13 - PC-005、PC-006、PC-009 抓取稳定性修复启动

- 状态：修复中。
- 范围：仅修复 arXiv 全部请求失败的失败传播、`crawled_ids.txt` 的提交时机，以及自定义 `--output` 对应状态文件的路径一致性。
- 隔离：使用临时目录和 mock HTTP/子进程，不调用真实 arXiv、Zotero、SMTP、Hermes 或 LLM。
- 边界：不扩展到 PC-014、PC-015、PC-019 或 PDF 下载实现。

### 2026-07-13 - PC-005、PC-006、PC-009 抓取稳定性完成并验证

- 状态：已验证。
- 根因：搜索请求异常被折叠成合法空结果；搜索脚本在批次结果和数据库 merge 前追加抓取 ID；CLI 状态生成固定读取默认 `new_papers.json`，没有跟随实际 `--output`。
- 修改文件：`arxiv_daily_search.py`、`daily_pipeline.py`、`tests/test_arxiv_daily_search.py`、`tests/test_daily_pipeline.py`、问题台账、阶段计划和项目记忆。
- 失败传播：每个分类显式记录成功或错误；全部分类失败时 `run_cli()` 返回 1 并写错误状态，至少一个分类成功时保留成功结果及失败分类明细；合法空 feed 仍返回成功。
- 提交时机：搜索阶段只原子写批次结果，不再修改 `crawled_ids.txt`；流水线仅在 merge 子进程成功后，从当批 `new_papers` 幂等提交 ID。结果写入失败或 merge 失败均不标记，下一次运行可重新抓取并提交。
- 路径一致性：相对或绝对 `--output` 都先解析为规范路径；结果、成功/失败 `run_status.json` 和抓取 ID 查询使用同一输出目录；状态直接取本次内存结果，不再读取可能陈旧的默认输出。
- 验证命令：`python -m unittest tests.test_arxiv_daily_search tests.test_daily_pipeline -v`、`python -m unittest discover -v`、`python -m py_compile arxiv_daily_search.py daily_pipeline.py tests/test_arxiv_daily_search.py tests/test_daily_pipeline.py`、`git diff --check`。
- 验证结果：聚焦 `17/17 OK`；全量 `132/132 OK`；编译与空白检查通过。覆盖全失败、部分失败、合法空 feed、结果写失败、merge 失败后重跑、ID 幂等、自定义相对/绝对输出和旧默认结果隔离。
- 外部边界：全部使用 `TemporaryDirectory`、mock HTTP 响应和 mock 子进程；未调用真实 arXiv、Semantic Scholar、Zotero、SMTP、Hermes 或 LLM。
- 剩余风险：PC-014、PC-015、PC-019 仍未处理；直接运行搜索脚本只产生待 merge 批次，抓取 ID 的正式提交仍由每日流水线负责。

### 2026-07-14 - PC-040 全网多源检索与内置论文智能体

- 状态：已验证。
- 甲方需求：每日抓取不能只依赖 arXiv；需要按研究领域/关键词配置，并支持在项目内针对单篇论文问答、生成学习笔记。
- 完成范围：新增 arXiv、OpenAlex、Crossref、Semantic Scholar、Europe PMC 统一适配层；按 DOI/arXiv/PMID/OpenAlex/标题去重并覆盖跨批次身份；每日流水线按 `sources` 配置选择多源 CLI。
- 智能体：新增 `/hermes/ask` 与 `/hermes/notes`；默认只使用已保存标题、摘要和增强内容，证据不足时返回 `grounded=false`；前端支持提问、证据展示、Markdown 笔记和复制。
- PDF：新增 `/api/papers/download` 与本地 OA 下载核心；只有明确 `open_access=true` 且有 `pdf_url` 才下载，使用 `PDFs/` 安全路径、`.part` 原子落盘、PDF 校验、有界重试、锁内 manifest 和多身份去重；卡片/详情提供保存入口。
- 合规边界：只读取公开元数据和明确的开放获取链接；不绕过付费墙、不调用真实 Zotero/SMTP/LLM；机构全文下载继续走用户授权的浏览器会话。
- 服务边界：旧 arXiv 单源结果显式标记 OA；请求体非法来源返回结构化 400；全部来源失败返回 502，部分失败保留成功结果。
- 验证结果：`python -m unittest discover -v` 为 `193/193 OK`；`node --check viewer/app.js` 与 `git diff --check` 通过。系统 Edge mock QA 在 `1280x800` 和 `390x844` 下均为 0 溢出、0 操作重叠、0 控制台/PageError/失败请求，双触发只产生一次下载请求。
- 剩余风险：没有调用真实外部论文源或出版社；自动每日批量下载、Range 断点续传、跨进程同一 PDF 全局互斥和 Zotero 附件写入仍不在本期完成范围。

### 2026-07-14 - PC-014、PC-015、PC-019 阶段 3 依赖收口

- 状态：已验证。
- `daily_pipeline.py` 对 search/merge/enrich/email 的非零和超时统一传播失败；成功路径顺序固定为 search → merge → crawled IDs → enrich → email。
- `merge_papers.py` 在 mark-pending 失败时保留已完成的数据库 merge，但返回结构化部分失败和非零退出码。
- `cron_wrapper.py` 导入不再启动流水线；`run()/main()` 保留 Windows 隐藏窗口意图、输出转发、退出码与超时失败。
- 聚焦测试和 `193/193` 全量回归通过；未启动真实每日任务、邮件或外部服务。

### 2026-07-14 - PC-041 OA PDF 保存反馈

- 状态：已验证。
- 根因：卡片下载按钮文案硬编码，卡片与详情的禁用态只判断“已保存”，没有读取 `state.downloading`。
- 修改：新增统一下载中判断；等待期间卡片和详情均显示“保存中…”并禁用，成功后显示“PDF 已保存”，失败后恢复可点击“保存 PDF”；逻辑去重、OA 权限和请求体不变。
- 验证：前端契约 `31/31 OK`，桌面运行时 `14/14 OK`；Edge 两视口 2 秒 mock 响应均观察到“保存中…”，双触发每视口只发 1 次请求，9 个卡片动作重叠数为 0。
