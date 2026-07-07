# arXiv 论文追踪系统 — 前端需求功能书

## 1. 系统概述

arXiv 论文每日自动追踪系统，由**后端（小瑞1号）**和**前端（你）**分工协作：

```
┌─────────────────────────────────────────────────────────┐
│  后端（小瑞1号）                                          │
│  ┌──────────┐   ┌──────────┐   ┌──────────┐            │
│  │ arXiv搜索 │ → │ LLM筛选  │ → │ 微信推送  │            │
│  │ +SS引用   │   │ +中文摘要 │   │ 日报     │            │
│  └──────────┘   └──────────┘   └──────────┘            │
│        ↓              ↓                                 │
│  ┌──────────────────────────────┐  ┌─────────────────┐  │
│  │     papers_database.json     │  │  Zotero API     │  │
│  │     (前后端共享数据源)         │  │  (一键入库)      │  │
│  └──────────────┬───────────────┘  └─────────────────┘  │
│                 │ 静态文件，前端直接读取                    │
├─────────────────┼───────────────────────────────────────┤
│  前端（你）       │                                       │
│  ┌──────────────┴───────────────┐                        │
│  │   Web 论文浏览器               │                        │
│  │   • 论文列表 + 卡片视图         │                        │
│  │   • 多维筛选（类别/日期/评分/引用）│                        │
│  │   • 搜索（标题/作者/摘要）       │                        │
│  │   • 详情弹窗（摘要+中文总结+PDF链接）│                      │
│  │   • "加入 Zotero" 按钮          │                        │
│  └──────────────────────────────┘                        │
└─────────────────────────────────────────────────────────┘
```

## 2. 数据源

### 2.1 数据文件

前端从以下 JSON 文件读取数据（后端每日更新）：

- **文件路径**: 由后端提供绝对路径，例如 `项目根目录\papers_database.json`
- **更新频率**: 每天早上 8:00 更新
- **读取方式**: 静态 JSON 文件（无需 API 服务器），直接用 `fetch()` 或内嵌 `<script src="...">` 加载

### 2.2 数据 Schema

```json
{
  "updated_at": "2026-07-08T08:00:00+08:00",
  "total_count": 156,
  "categories": ["cs.AI", "cs.CL", "cs.CV", "cs.LG"],
  "papers": [
    {
      "arxiv_id": "2402.03300",
      "title": "Vision-Language Models Are Zero-Shot Reward Models",
      "authors": ["John Doe", "Jane Smith"],
      "published": "2026-07-07",
      "categories": ["cs.CV", "cs.AI"],
      "primary_cat": "cs.CV",
      "abstract": "The original English abstract...",
      "abstract_cn": "本文提出了一种利用视觉语言模型作为零样本奖励模型的方法...",
      "affiliations": "MIT; Stanford University",
      "citations": 42,
      "influential_citations": 15,
      "reference_count": 58,
      "venue": "NeurIPS 2026",
      "fields_of_study": ["Computer Vision", "Machine Learning"],
      "is_open_access": true,
      "quality_score": 8.5,
      "quality_signals": {
        "citation_signal": "high",
        "venue_signal": "top_conference",
        "author_signal": "established",
        "novelty_signal": "high"
      },
      "pdf_url": "https://arxiv.org/pdf/2402.03300",
      "abs_url": "https://arxiv.org/abs/2402.03300",
      "zotero_status": null,
      "crawled_date": "2026-07-08",
      "tags": ["VLM", "segmentation", "zero-shot"]
    }
  ]
}
```

### 2.3 字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `arxiv_id` | string | arXiv ID，唯一标识 |
| `title` | string | 论文标题（英文） |
| `authors` | string[] | 作者列表 |
| `published` | string | 发布日期 YYYY-MM-DD |
| `categories` | string[] | arXiv 分类 |
| `primary_cat` | string | 主分类 |
| `abstract` | string | 英文摘要 |
| `abstract_cn` | string | 中文摘要（90-150字） |
| `affiliations` | string | 作者单位，分号分隔 |
| `citations` | int\|null | 引用数（Semantic Scholar） |
| `influential_citations` | int\|null | 高影响力引用数 |
| `venue` | string\|null | 发表场所（如 "NeurIPS 2026"） |
| `fields_of_study` | string[] | 研究领域 |
| `is_open_access` | bool | 是否开放获取 |
| `quality_score` | float | 综合质量评分 0-10 |
| `quality_signals` | object | 各维度质量信号 |
| `pdf_url` | string | PDF 直链 |
| `abs_url` | string | arXiv 摘要页 |
| `zotero_status` | string\|null | Zotero 状态：null=未入库, "pending"=等待入库, "added"=已入库 |
| `crawled_date` | string | 抓取日期 |
| `tags` | string[] | 自动标签（从标题/摘要提取） |

## 3. 前端功能需求

### 3.1 核心页面：论文浏览器

**布局建议**: 左侧筛选栏 + 右侧论文列表

#### A. 筛选栏（左侧 ~280px）

1. **日期范围选择器**
   - 快捷按钮：今天、近3天、近7天、近30天、全部
   - 或日期范围选择器

2. **分类筛选（多选 checkbox）**
   - cs.AI, cs.CL, cs.CV, cs.LG
   - 每个显示论文数量

3. **质量筛选**
   - 评分滑块 0-10 或星级
   - 快捷：⭐8+（高含金量）、⭐5-8（中等）、⭐0-5（低）

4. **排序方式**
   - 默认：质量评分降序
   - 可选：日期最新、引用数最多、标题 A-Z

5. **标签筛选**
   - 云标签或 checkbox 列表
   - 从 `tags` 字段动态生成

6. **Zotero 状态筛选**
   - 全部 / 未入库 / 已入库

#### B. 论文列表（右侧）

每篇论文显示为**卡片**，包含：

1. **标题**（粗体，可点击跳转 arXiv）
2. **作者**（最多显示前3位 + "等N人"）
3. **发表场所** + **日期**
4. **质量评分**（星级或数字，彩色标识）
5. **引用数**（如有）
6. **标签**（小徽章）
7. **中文摘要**（一行截断，可展开）
8. **操作按钮**:
   - 📄 PDF（新窗口打开）
   - 📋 复制引用
   - 📚 加入 Zotero（核心按钮）
   - ⭐ 收藏（本地存储）

#### C. 论文详情弹窗/展开

点击卡片展开或弹出模态框：

1. 完整英文摘要
2. 完整中文摘要
3. 所有作者 + 单位
4. 分类信息
5. 引用统计
6. 质量评分明细（各维度信号）
7. 操作按钮（同上）

### 3.2 搜索功能

顶部搜索框，支持：
- 标题搜索
- 作者搜索
- 摘要全文搜索
- 输入即搜（debounce 300ms）
- 高亮匹配文本

### 3.3 "加入 Zotero" 功能

**交互流程**:

1. 用户点击某篇论文的「📚 加入 Zotero」
2. 按钮变为「⏳ 正在添加...」
3. 前端调用后端 API（见第4节）
4. 成功 → 按钮变为「✅ 已加入」+ 更新 `zotero_status`
5. 失败 → 显示错误提示 + 重试按钮

**批量操作**:
- 勾选多篇论文后，顶部出现「批量加入 Zotero (N篇)」按钮

### 3.4 数据更新提示

- 页面顶部显示「最后更新：YYYY-MM-DD HH:mm」
- 新论文（当天抓取）标记 🆕 徽章
- 可选：自动刷新（每5分钟检查 `papers_database.json` 是否更新）

### 3.5 响应式

- 桌面端（>1024px）：左侧筛选栏 + 右侧列表
- 移动端（<768px）：筛选栏折叠为顶部抽屉，列表单列

## 4. Zotero API 接口

### 4.1 端点

```
POST http://localhost:8765/zotero/add
Content-Type: application/json

{
  "arxiv_ids": ["2402.03300", "2401.12345"],
  "collection": "arXiv Papers"   // 可选，Zotero 中的收藏夹名
}
```

### 4.2 响应

```json
{
  "success": true,
  "added": 2,
  "failed": 0,
  "results": [
    {"arxiv_id": "2402.03300", "status": "added", "zotero_key": "ABC123"},
    {"arxiv_id": "2401.12345", "status": "added", "zotero_key": "DEF456"}
  ]
}
```

### 4.3 状态查询

```
GET http://localhost:8765/zotero/status?arxiv_id=2402.03300
```

## 5. 技术建议

| 项目 | 建议 |
|------|------|
| 框架 | 纯 HTML+CSS+JS（单文件，零依赖）或 Vue/React（如果需要复杂交互） |
| 数据加载 | `fetch('papers_database.json')` 或直接内嵌 |
| 状态管理 | 前端内存（从 JSON 加载后全部在内存操作，数据量 <1000 条） |
| 部署 | 本地文件 `file://` 打开，或 `python -m http.server` 托管 |
| 缓存 | LocalStorage 存筛选偏好和收藏列表 |
| 图标 | 可以用 emoji 或简单的 SVG |

## 6. 交付物

1. **单个 HTML 文件**（或少量文件）包含完整功能
2. 放到 `项目根目录\viewer\` 目录
3. 后端通过 `python viewer/run_viewer.py` 或直接 `python -m http.server` 启动

## 7. 验收标准

- [ ] 能加载 `papers_database.json` 并显示论文列表
- [ ] 按分类、日期、评分筛选功能正常
- [ ] 搜索功能（标题/作者/摘要）正常
- [ ] 论文详情弹窗显示完整信息
- [ ] Zotero 按钮能调用后端 API
- [ ] 移动端基本可用
- [ ] 新论文有 🆕 标记
