# PaperCatch Desktop

`desktop/` 是独立的 Windows 桌面壳，复用根目录的 Python 后端和 `viewer/`，不复制业务代码。

## 本地运行

在项目根目录执行：

```powershell
python -m pip install -r desktop/requirements.txt
python -m desktop
```

桌面壳会在系统分配的随机 `127.0.0.1` 端口启动后端，关闭窗口时同步停止服务。缺少 `pywebview` 时，入口会输出明确的安装命令。

源码模式与网页版共用项目根目录的数据。打包后的 EXE 使用 `%LOCALAPPDATA%\PaperCatch` 保存可写数据，静态 `viewer/` 始终从 bundle 读取。首次启动只会在目标文件不存在时复制默认 `papercatch_categories.json` 和 `search_config.json`，不会迁移或覆盖源码目录里的现有用户数据。

## 在桌面端配置 Zotero

启动后进入右上角“设置 → Zotero 集成”，填写：

- `Zotero User ID`
- `Zotero API Key`
- 默认 Collection 路径

保存内容写入 `%LOCALAPPDATA%\PaperCatch\config.local.json`。页面只读取脱敏状态，不会显示或回填已保存的 API Key；密钥框留空保存会继续使用原密钥。若系统中设置了非空 `ZOTERO_API_KEY`、`ZOTERO_USER_ID` 或 `ZOTERO_DEFAULT_COLLECTION`，对应环境变量在运行时优先于文件值。

## 构建 EXE

```powershell
powershell -ExecutionPolicy Bypass -File desktop/build.ps1
```

构建结果：`dist\PaperCatch\PaperCatch.exe`。

当前使用 PyInstaller `onedir` 模式，发布时需要分发整个 `dist\PaperCatch` 目录，不能只复制单个 EXE。Windows 需要 WebView2 Runtime；Windows 10/11 通常已经安装。

构建前可运行 `python -m unittest discover -v`；构建后应启动 `dist\PaperCatch\PaperCatch.exe`，确认窗口可响应且其随机 loopback `/health` 返回 `status=ok`。

## 迁移现有源码数据（可选）

EXE 首次启动并关闭后，可把需要延续的数据复制到桌面端目录。请使用复制而不是移动，以便保留源码数据作为回滚副本：

```powershell
$target = Join-Path $env:LOCALAPPDATA "PaperCatch"
New-Item -ItemType Directory -Force $target | Out-Null
Copy-Item .\papers_database.json $target -ErrorAction SilentlyContinue
Copy-Item .\config.local.json $target -ErrorAction SilentlyContinue
Copy-Item .\search_config.json $target -Force
Copy-Item .\papercatch_categories.json $target -Force
Copy-Item .\pending_enrichment.json $target -ErrorAction SilentlyContinue
Copy-Item .\crawled_ids.txt $target -ErrorAction SilentlyContinue
```

复制前必须关闭桌面端，避免和正在运行的后端同时写同一文件。上述操作不会删除项目根目录里的原文件。
