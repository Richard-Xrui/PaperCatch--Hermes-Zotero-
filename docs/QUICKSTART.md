# 🎯 快速开始指南

## 一键启动

```bash
# 1. 进入项目目录
cd D:\PaperCatch-Hermes-Zotero

# 2. 启动服务（会自动打开浏览器）
python start.py
```

服务启动后访问：**http://localhost:8765**

---

## 🎨 全新中式美学界面

### 设计特色

- **水墨配色** - 宣纸白、浓墨、朱砂印章红
- **书法排版** - 优雅的中文衬线字体
- **印章元素** - "纸上得来" 品牌印章
- **留白设计** - 简约而不失精致

### 界面预览

```
┌─────────────────────────────────────────────────────────┐
│ [纸] 纸上得来  [🔍 搜索...]  [最后更新] [⟳] [设置] [Hermes] │
├──────────┬──────────────────────────────────────────────┤
│ 筛选器    │  摘要栏：显示 13 / 13 篇论文                  │
│          ├──────────────────────────────────────────────┤
│ 📅 日期   │  ┌──────────────────────────────────────┐   │
│ 🏷️ 分类   │  │  [✓] Cortex: A Bidirectionally...    │   │
│ ⭐ 评分   │  │  作者：Jiaqi Peng、Xiqian Yu...      │   │
│ 📊 排序   │  │  摘要：While recent Vision-Language... │   │
│ 📚 状态   │  │  [详情] [复制] [arXiv] [加入Zotero]  │   │
│          │  └──────────────────────────────────────┘   │
│          │                                              │
│          │  [更多论文卡片...]                            │
└──────────┴──────────────────────────────────────────────┘
```

---

## ⚡ 核心功能

### 1. 智能筛选

- **日期快捷键**: 今天 / 近7天 / 近30天 / 全部
- **自定义分类**: 支持关键词匹配
- **质量评分**: 滑块筛选 0-10 分
- **Zotero 状态**: 已入库 / 未入库

### 2. 全文搜索

实时搜索标题、作者、摘要、标签，300ms防抖。

### 3. 一键入库

- 单篇加入 Zotero
- 批量加入 Zotero
- 自动分类到文件夹

### 4. Hermes 智能搜索

用自然语言从已配置的公开来源搜索论文：
- "找最近 7 天 LLM safety 论文 8 篇，并加入 Zotero"
- "搜索多模态 3D/4D 论文 6 篇"

在单篇论文上还可以：
- 针对当前保存的摘要和已有内容提问，回答附带证据字段
- 按问题或学习目标生成 Markdown 学习笔记
- 当摘要不足以支持结论时明确提示需要全文

---

## 📚 数据管理

### 获取最新论文

```bash
# 获取最近3天的论文（推荐）
python daily_pipeline.py --days 3 --max-per-cat 10

# 获取今天的论文
python daily_pipeline.py --days 0 --max-per-cat 25

# 获取最近7天的论文
python daily_pipeline.py --days 7 --max-per-cat 15
```

### 配置 Zotero

```bash
# 首次配置
python start.py --setup

# 或编辑配置文件
notepad config.local.json
```

需要填写：
- `zotero.api_key` - 从 https://www.zotero.org/settings/keys/new 获取
- `zotero.user_id` - 你的 Zotero 用户 ID

也可以启动网页或桌面端后进入“设置 → Zotero 集成”。已保存的 API Key 不会显示或回填，留空保存会保留原密钥。

---

## 🎛️ 自定义分类

### 添加新分类

1. 点击左侧筛选器的 "分类" 旁边的 **+** 按钮
2. 输入分类名称（如：安全对齐）
3. 输入关键词（如：safety, alignment, 对齐）
4. 点击 "添加"

### 关键词匹配规则

- 逗号分隔多个关键词
- 自动匹配标题、摘要、标签
- 不区分大小写
- 支持中英文

### 默认分类

- 大语言模型（LLM, agent, prompt...）
- 计算机视觉（vision, image, VLM...）
- 机器学习（machine learning, training...）
- 机器人（robot, manipulation...）
- 生成模型（diffusion, GAN, VAE...）

---

## 🔧 常用操作

### 查看论文详情

点击论文卡片的 **"详情"** 按钮，查看：
- 完整英文摘要
- 中文摘要（如有）
- 全部作者与分类
- 引用统计
- 快捷链接（arXiv, PDF）

### 论文问答、学习笔记与保存 PDF

- 点击 **“问这篇论文”**，基于当前已保存的标题、摘要和增强内容提问；先看 `grounded` 和证据，再使用回答。
- 点击 **“生成学习笔记”**，填写关注点后生成 Markdown，并可直接复制到 Obsidian 或其他 Markdown 工具。
- 只有明确开放获取的论文会显示 **“保存 PDF”**。保存期间按钮显示“保存中…”，完成后显示“PDF 已保存”；受限内容不会尝试绕过权限。
- 源码模式默认保存到项目数据目录的 `PDFs/`；桌面打包版保存到 `%LOCALAPPDATA%\PaperCatch\PDFs`。

### 复制论文引用

点击 **"复制引用"** 按钮，格式：
```
作者1, 作者2, ... 标题. arXiv:ID, 日期.
```

### 批量操作

1. 勾选多篇论文
2. 顶部出现批量操作栏
3. 点击 "批量加入 Zotero"

---

## ⚙️ 高级设置

### 搜索设置

点击顶部 **"搜索设置"** 按钮：
- 设置每日研究领域 / 关键词
- 选择 arXiv、OpenAlex、Crossref、Semantic Scholar、Europe PMC 来源
- 选择 arXiv 分类
- 每类篇数限制
- 搜索天数范围

### 自动刷新

左侧筛选器底部勾选 **"每 5 分钟自动刷新"**

---

## 🐛 常见问题

### Q: Zotero 加入失败？
**A**: 检查配置：
```bash
python start.py --doctor
```
确保 `Zotero: ready` 显示。

### Q: 论文列表为空？
**A**: 运行数据抓取：
```bash
python daily_pipeline.py --days 3 --max-per-cat 10
```

### Q: 搜索无结果？
**A**: 
1. 检查筛选条件（日期、分类、评分）
2. 点击 "重置" 清空筛选
3. 确认数据库有论文数据

### Q: Hermes 搜索失败？
**A**: `/hermes/search` 不要求本机 Hermes 可执行文件。需要 LLM 解析时配置：
```bash
# config.local.json: llm.api_key / llm.base_url
# 或环境变量 DEEPSEEK_API_KEY / DEEPSEEK_BASE_URL
```

LLM 不可用时会自动回落到内置规则解析器；如果整个请求失败，先检查 `python start.py` 的服务日志和 arXiv 网络访问。

---

## 📱 响应式设计

- **桌面** (>1024px) - 左右分栏
- **平板** (768-1024px) - 筛选器折叠
- **手机** (<640px) - 单列布局

所有功能在移动端完美可用！

---

## 🚀 性能提示

- 数据保存在本地（`papers_database.json`）
- 筛选在浏览器内存中进行，无需请求服务器
- 使用 localStorage 保存状态
- 搜索防抖减少计算

---

## 📞 获取帮助

查看完整文档：
- `README.md` - 项目总览
- `CHANGELOG.md` - 更新日志
- `FRONTEND_SPEC.md` - 前端规格

---

## 🎉 开始使用

```bash
# 一条命令，完成所有配置
python start.py --bootstrap

# 然后获取论文数据
python daily_pipeline.py --days 3 --max-per-cat 10

# 打开浏览器访问
# http://localhost:8765
```

享受全新的论文浏览体验！📖
