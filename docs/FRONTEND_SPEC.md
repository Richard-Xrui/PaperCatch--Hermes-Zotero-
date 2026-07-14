# PaperCatch 前端规格

状态：当前实现基线（2026-07-14）
事实来源：`viewer/index.html`、`viewer/app.js`、`zotero_server.py`

本文描述当前网页端和 Windows 桌面端共同使用的前端行为。它是实现与验收规范，不是早期功能愿望清单。

## 1. 运行方式与边界

- 前端为 `viewer/` 下的原生 HTML、CSS、JavaScript，无前端运行时依赖。
- 源码模式由 `python start.py` 提供 `http://127.0.0.1:8765`。
- 桌面模式由 `python -m desktop` 或 `PaperCatch.exe` 在系统分配的随机 loopback 端口启动同一后端，并用 pywebview/WebView2 展示同一套 `viewer/`。
- 前端必须通过 PaperCatch HTTP 服务运行，不支持直接用 `file://` 打开，也不使用 `python -m http.server` 单独托管。
- 页面与 API 同源；服务只允许 loopback Host，不应暴露到局域网或公网。

```text
start.py / desktop.app
  -> zotero_server.py（127.0.0.1，源码固定端口或桌面随机端口）
  -> viewer/index.html + viewer/app.js
  -> /api/*、/hermes/*、/zotero/*
  -> 本地 JSON 数据与 Zotero Web API
```

## 2. 论文数据契约

页面通过 `GET /api/papers` 读取论文，不直接读取磁盘 JSON 文件。

响应外层：

```json
{
  "updated_at": "2026-07-13T08:00:00+08:00",
  "total_count": 1,
  "papers": []
}
```

论文对象常用字段：

| 字段 | 类型 | 页面用途 |
| --- | --- | --- |
| `paper_id` / `arxiv_id` | string | 跨来源唯一标识；兼容选择、删除、下载和 Zotero 入库 |
| `title` | string | 英文标题、搜索和引用文本 |
| `title_cn` | string，可选 | 优先显示的中文标题 |
| `authors` | string[] | 卡片、详情和搜索 |
| `published` | string | 日期筛选、排序和展示，格式 `YYYY-MM-DD` |
| `categories` | string[] | 卡片元数据和搜索 |
| `abstract` / `abstract_full` | string，可选 | 英文摘要 |
| `abstract_cn` | string，可选 | 卡片优先摘要和中文完成状态 |
| `summary_cn` / `background_cn` | string，可选 | 详情和中文完成状态 |
| `affiliations` | string 或 string[]，可选 | 详情页作者单位 |
| `tags` | string[] | 卡片标签、方向筛选和搜索 |
| `quality_score` | number 或 null | 徽标、评分筛选和排序 |
| `quality_signals` | object，可选 | 详情页评分信号 |
| `citations` | number 或 null | 卡片、详情和排序 |
| `source` / `sources` | string / string[]，可选 | 论文来源与跨源聚合来源 |
| `landing_url` / `abs_url` / `pdf_url` | string，可选 | 来源详情页、arXiv 与开放 PDF 外链 |
| `open_access` / `is_open_access` | boolean 或 null | 是否有明确合法的开放获取 PDF；只有明确为真时允许保存 |
| `download_status` / `pdf_path` / `download_reason` | string，可选 | 本地 PDF 保存状态、路径和失败原因 |
| `zotero_status` | string 或 null | `added` 表示已入库，其余值按未入库展示 |
| `zotero_collection` | string，可选 | 已入库 Collection |

“已有中文”要求 `title_cn`、`abstract_cn`、`summary_cn` 三项同时非空。缺失的数组字段在加载时规范化为空数组，缺失评分规范化为 `null`。

## 3. 页面与交互

### 3.1 顶栏

- 展示 PaperCatch 品牌、数据更新时间、刷新、设置和“问 Hermes”入口。
- 搜索框以 250ms debounce 过滤标题、作者、摘要、中文内容、arXiv 分类和标签。
- `/` 在没有打开 Modal 且焦点不在输入控件时聚焦搜索框；搜索框内 `Escape` 清空搜索。
- 搜索只过滤并显示结果数量，当前不做匹配文本高亮。

### 3.2 筛选栏

- 日期：今天、近 3 天、近 7 天、近 30 天、全部，以及自定义开始/结束日期。
- 研究方向：按用户定义的逗号分隔关键词匹配论文文本；方向保存在 `localStorage` 的 `papercatch.cats.v6`，不等同于服务端 arXiv 抓取分类。
- 质量评分：0 至 10，步长 0.5；无评分论文在最低分大于 0 时被排除。
- 排序：最新发表、质量评分、引用数、标题。
- Zotero 状态：全部、未入库、已入库。
- 中文内容：全部、已有中文、待生成。
- 自动刷新：勾选后每 5 分钟重新请求 `/api/papers`；关闭时取消计时器。
- 筛选状态保存在 `localStorage` 的 `papercatch.filters.v6`；“重置”恢复默认值。

### 3.3 论文卡片

- 显示中文优先标题、可选英文标题、作者、日期、最多 3 个分类、引用数、评分、Zotero 状态、中文待生成状态和最多 6 个标签。
- 摘要默认截断；仅在确实发生截断时显示展开/收起按钮。
- 支持详情、复制引用、来源页/PDF 外链、问这篇论文、生成学习笔记、保存开放 PDF、删除和加入 Zotero。
- “保存 PDF”只对 `open_access=true` 且有 `pdf_url` 的论文可执行；保存中禁止重复提交，成功后卡片和详情同步显示已保存状态。
- 所有插入 HTML 的论文文本必须先转义；外链使用 `target="_blank"` 和 `rel="noreferrer"`。

### 3.4 批量操作

- 可全选当前筛选结果、取消选择、批量删除或批量加入 Zotero。
- 任何筛选变化后，选择集合必须收敛到当前可见论文，禁止对隐藏论文继续执行批量操作。
- 删除必须经用户确认；成功后重新渲染本地状态。

### 3.5 详情、Hermes、论文 Agent 与设置 Modal

- 四个 Modal 均使用 `role="dialog"`、`aria-modal="true"` 和标题关联。
- 打开后焦点进入对话框，Tab/Shift+Tab 在可见控件间循环；`Escape`、关闭按钮或背景点击关闭，关闭后焦点返回触发控件。
- 每次打开先把 backdrop 的 `scrollTop` 重置为 0。
- Hermes 支持示例提示、Ctrl+Enter 发送和 `POST /hermes/search`；返回新增论文后重新加载列表。
- 论文 Agent 基于当前论文调用 `POST /hermes/ask` 或 `POST /hermes/notes`，展示 grounded、证据和 Markdown 学习笔记；笔记可复制为 Markdown，剪贴板失败必须提示错误。
- 设置 Modal 分开保存每日研究领域/关键词、公开论文来源和 Zotero 设置；来源选项由 `GET /api/sources` 提供。

### 3.6 通知

- 成功通知使用 `role=status`/polite live region；错误通知切换为 `role=alert`/assertive。
- 桌面和平板通知位于右下角。
- 小于等于 620px 时通知使用顶部状态条，并按实际高度给 sticky 顶栏和已打开 Modal 预留空间，不得遮挡主操作按钮。

## 4. 前端使用的 HTTP API

| 方法 | 路径 | 用途 | 请求正文 |
| --- | --- | --- | --- |
| GET | `/api/papers` | 加载论文 | 无 |
| DELETE | `/api/papers` | 删除论文 | `{"arxiv_ids":["ID"]}` |
| GET | `/api/config` | 读取抓取设置 | 无 |
| POST | `/api/config` | 保存抓取设置 | `categories/keywords/sources/max_per_cat/days` |
| GET | `/api/sources` | 读取可用公开论文来源 | 无 |
| GET | `/api/integrations` | 读取脱敏 Zotero 状态 | 无 |
| POST | `/api/integrations` | 保存本地 Zotero 设置 | `{"zotero":{...}}` |
| POST | `/hermes/search` | 自然语言多源搜索与合并论文 | `{"message":"...","sources":["arxiv",...]}`；`sources` 可省略 |
| POST | `/hermes/ask` | 基于单篇论文证据回答问题 | `{"paper_id":"...","question":"..."}` |
| POST | `/hermes/notes` | 生成单篇论文 Markdown 学习笔记 | `{"paper_id":"...","focus":"..."}` |
| POST | `/api/papers/download` | 保存明确开放获取的论文 PDF | `{"paper_ids":["..."]}` |
| POST | `/zotero/add` | 单篇或批量入库 | `arxiv_ids/collection` |

服务还提供 `/api/categories`、`/api/enrich`、`/api/status`、`/zotero/status`、`/zotero/collections` 和 `/health`，当前 `viewer/app.js` 不直接使用其中大部分端点。

变更请求必须同源、使用 loopback Host，并带 `Content-Type: application/json`。错误响应使用：

```json
{
  "success": false,
  "error": {
    "code": "invalid_request",
    "message": "human-readable message"
  }
}
```

前端同时兼容旧式字符串 `error`，但新接口应使用结构化错误。

## 5. Zotero 设置与隐私

`GET /api/integrations` 只允许返回：

```json
{
  "zotero": {
    "configured": true,
    "user_id": "1234567",
    "default_collection": "PaperCatch/Hermes Search"
  }
}
```

- 响应和 DOM 中不得出现已保存的 API Key。
- API Key 输入必须是密码框；成功或重新打开设置后始终清空。
- POST 中 `api_key` 为空表示保留文件中的已有密钥。
- 非空 `ZOTERO_API_KEY`、`ZOTERO_USER_ID`、`ZOTERO_DEFAULT_COLLECTION` 环境变量仍拥有运行时优先级。
- 源码模式写项目数据目录；打包桌面端写 `%LOCALAPPDATA%\PaperCatch\config.local.json`。

## 6. 响应式与可访问性

- 大于 1000px：固定宽度筛选侧栏和论文主列。
- 小于等于 1000px：单列布局，筛选内容默认折叠；checkbox 同步 `aria-expanded` 和展开/收起文案。
- 小于等于 620px：卡片标题占完整可用列，状态徽标移至标题下方，操作区纵向排列。
- 页面不得产生横向滚动；长英文标题允许自然换行，不得被徽标压成逐词窄列。
- 控件、Modal、toast 和动态状态必须可通过键盘和辅助技术识别。

## 7. 当前不提供的功能

- 不提供收藏、搜索词高亮、分页、服务端筛选或离线 `file://` 模式。
- 自定义“研究方向”只保存在当前浏览器/WebView 的 localStorage，不会同步到其他设备或浏览器配置。
- UI 自动测试不调用真实 Zotero、arXiv 或 LLM；真实外部账号与网络需单独验收。

## 8. 验收与验证

- [x] 同源加载论文并显示非空主界面。
- [x] 搜索、日期、方向、评分、排序、Zotero 和中文状态筛选可用。
- [x] 隐藏论文不会保留在批量选择中。
- [x] 详情、Hermes、论文 Agent、设置 Modal 的语义、焦点循环、Escape 和焦点恢复可用。
- [x] 每日研究领域/关键词和多来源选择可读取、保存并用于抓取配置。
- [x] 单篇论文问答、Markdown 学习笔记和复制入口可用，证据不足时不伪造 grounded 结果。
- [x] 明确开放获取的论文可保存 PDF；非 OA 论文不会触发下载请求。
- [x] Zotero 设置脱敏读取、空密钥保留和严格保存可用。
- [x] `1440x900`、`1024x768`、`390x844` 无横向溢出、控制台错误或失败请求。
- [x] 手机长标题保持可读，设置重开回顶，toast 不遮挡保存按钮。

常用验证命令：

```powershell
python -m unittest tests.test_frontend_contract tests.test_server_integrations -v
python -m unittest discover -v
node --check viewer/app.js
git diff --check
```
