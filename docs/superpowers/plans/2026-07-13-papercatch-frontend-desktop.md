# PaperCatch 前端与桌面端实施计划

日期：2026-07-13
状态：已完成并验证（含 2026-07-13 桌面运行时补充修复 PC-039）
范围：PC-018、PC-020 至 PC-022、PC-025 至 PC-036、PC-038、PC-039

## 目标

1. 修复窄侧栏日期输入溢出和移动端筛选占满首屏。
2. 筛选后批量选择只保留当前可见论文。
3. 为详情、Hermes 和设置 Modal 补齐语义、初始焦点和焦点恢复。
4. 在 `desktop/` 提供独立 Windows 窗口、随机 loopback 后端和关闭回收。
5. PyInstaller 包内只放静态资源，可写数据进入 `%LOCALAPPDATA%\PaperCatch`。
6. 在复用的设置 Modal 中提供脱敏 Zotero 配置读写，并补齐移动端控件状态、长标题、弹窗滚动和 toast 布局。

## 实施顺序

1. 用前端契约测试固定选择集合和 Modal 行为。
2. 修改 `viewer/index.html` 与 `viewer/app.js`，完成桌面/移动 DOM 几何验证。
3. 用纯 Python 隔离测试定义桌面后端生命周期、路径分离和首次 seed。
4. 实现 pywebview 入口、PyInstaller spec、PowerShell 构建脚本和迁移说明。
5. 安装桌面依赖，构建并启动 EXE，最后运行全量单元测试和前端交互回归。

## 完成结果

- `/api/integrations` 支持脱敏读取和严格、原子保存；API Key 不回填，空值保留已有密钥，环境变量仍优先。
- 移动筛选同步 `aria-expanded` 和文案；手机卡片徽标移至标题下方；Modal 重开回到顶部；窄屏 toast 使用独立顶部通知区域。
- 系统 Edge 在 `1440x900`、`1024x768`、`390x844` 完成页面、交互、焦点、网络、控制台和几何回归；toast 与保存按钮重叠面积为 0。
- `FRONTEND_SPEC.md` 已按当前同源 HTTP 架构重写，并由实际 `fetch()` 端点契约测试防止再次漂移。
- 桌面窗口标题和启动背景已与页面品牌统一，入口契约与重建实包标题验证通过。
- 搜索框已从通用文本输入级联中隔离，重建实包在桌面/手机 Edge 中均保留 10.61px 图标文字安全间距。
- 桌面运行时补充修复：`BackendService.start()` 发现旧 worker 线程已退出时，会先回收陈旧 `server/thread/url` 再重新绑定新的 loopback URL，不再复用失效地址。
- PC-039 实包收尾：最新 onedir `dist\PaperCatch` 已按 `uv run --no-project --python 3.11 --with pywebview --with pyinstaller -- powershell -ExecutionPolicy Bypass -File desktop/build.ps1 -Python python` 重建；新实例窗口响应，`GET /health` 返回 `{"status":"ok","service":"PaperCatch"}`，首页品牌标题加载正常。
- 最新全量回归为 `108/108 OK`；桌面运行时 `13/13 OK`，focused `PC-039` 冒烟 `1/1 OK`，33 个 Python 文件编译通过，`node --check viewer/app.js` 和 `git diff --check` 通过。

## 边界

- 不复制或重写现有后端与 `viewer/` 业务代码。
- 不调用真实 Zotero、SMTP、arXiv、Hermes 或 LLM。
- seed 和迁移不得覆盖已存在的用户文件。
- 不提交、推送或重置当前工作区。
