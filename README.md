# Nexus 桌面助手 / Nexus Desktop Assistant

本地优先的 Windows 桌面 AI 助手。它可以聊天、诊断电脑、生成文档与单文件网页、截图提问，也能通过 Windows UI 自动化替你操作软件界面。

A local-first AI assistant for Windows. It chats, diagnoses your PC, writes documents and single-file web pages, answers questions about screenshots, and can operate application UIs through Windows UI Automation.

[简体中文](#简体中文) · [English](#english)

---

## 简体中文

### 获取与安装

官方发行版**只提供安装包** `Nexus-Setup-<版本>.exe`：双击运行，安装向导可自选安装位置，默认 `%LOCALAPPDATA%\Programs\Nexus`，无需管理员权限。

源码以 MIT 协议开放，可以自行运行、修改和构建。构建脚本也会在本地生成绿色包，但绿色包仅供本地测试，不作为官方发行物提供。

程序采用分体式结构：`Nexus.exe` 只是启动入口，依赖库在 `_internal\`，业务字节码在 `lib\app\`。请勿单独移动 `Nexus.exe`，否则无法启动。`lib\app\` 中只有编译后的 `.pyc`，不含 `.py` 源码。

### 首次使用

1. 首次启动会打开独立的引导窗口：Nexus 轨道标志会带你依次完成称呼与界面语言、头像上传或默认头像、模型连接、外观与开机启动，最后给助手起名并确认它该怎么称呼你。
2. 完成引导后会打开主界面；也可以按 `Ctrl+Alt+Space` 随时唤起。已有 API Key 的老用户会直接进入主界面，不会重复走引导。
3. API Key 用 Windows DPAPI 加密保存，不写日志；没有真实账号系统，昵称、头像和助手名称只保存在本机。助手名称与你指定的称呼会写入系统提示词。
4. 试试这些说法：
   - “我电脑上不了网，帮我看看”
   - “帮我写一份本周网络维护周报”
   - “做一个单文件网页，展示我的读书清单”
   - “打开记事本，帮我输入今天的待办”

### 主要功能

| 能力 | 说明 |
| --- | --- |
| 对话 | 流式回复、停止、思考过程、工具调用卡片；不限制工具轮次，是否思考由模型逐轮决定；Markdown 边生成边渲染，支持表格、多级标题、代码块、引用、图片 |
| 中英文 | 设置里切换简体中文 / English / 跟随系统，主界面、设置、历史、快捷浮窗、托盘和引导页同步 |
| 本地账号 | 昵称、头像上传或默认头像、助手名称，只保存在本机 |
| 设置中心 | 账号与语言、模型与 API、上下文、运行时、快捷键、通知与外观、文件与数据、性能、关于与更新九组 |
| 上下文压缩 | 128K / 1M 两档；对话状态栏实时显示 token 与圆环占用占比，点击圆环即可压缩；达到 50% 自动把整个会话统一总结为摘要，也可关闭自动压缩 |
| 输出上限 | 64K / 128K 两档，按所选上限发送请求 |
| 性能监控 | 设置 > 性能实时显示后端、整个应用（含 WebView2）和系统的 CPU / 内存；记录上次对话平均 CPU 与用时 |
| API 报错详情 | 保留友好提示，可展开查看 HTTP 状态码与服务端原始错误 |
| 电脑诊断 | 系统信息、进程、服务、网络 ping / DNS / IP / 代理 / 端口 |
| 网络修复 | 清 DNS、重新获取 IP、释放 IP、重置 Winsock（每次确认） |
| 文件与文档 | 读写、编辑、搜索、批量查找，生成 Markdown / CSV / 文本 |
| 单文件网页 | CSS / JS / 图片全部内联，双击即可打开，不依赖外网 |
| 截图提问 | 全屏截图、自绘区域截图，随消息发给模型分析 |
| 语音输入 | 本地 SenseVoice 模型，`Ctrl+Alt+V` 开始/结束，不经过系统语音 |
| 电脑操作 | 枚举窗口、读取界面、查找控件、点击与输入（每次确认） |
| 联网搜索 | DeepSeek Search / Fetch，读取网页正文 |
| 定时任务 | 延时或定时执行一次性提示词任务，可在设置里查看与取消 |
| 运行时权限 | 安全（只读）/ 监管（执行命令、运行程序需确认，写文件免确认）/ 全部下放（自主执行任何命令，责任自负） |
| 自动更新 | 优先读取自建更新服务的 `update.json`，也可配置 GitHub `owner/repo` 检查 Releases；可立即更新或暂不更新，下载后先校验 SHA-256 |

### 数据与隐私

默认数据目录：`%APPDATA%\Nexus`。绿色包在程序目录下使用 `data\`。

| 文件 | 内容与保护方式 |
| --- | --- |
| `config.dat` | 设置。整体 AES-256-GCM 加密，不再保存明文 `config.json` |
| `secret.key` | 32 字节随机主密钥，只保存 Windows DPAPI 密文 |
| `nexus.db` | 会话、消息、工具记录、文件索引、审计、定时任务；敏感字段逐条 AES-256-GCM 加密 |
| `files\` | 你让 Nexus 生成的文件（本身不加密） |
| `models\` | 本地语音模型（首次使用时下载） |
| `logs\` | 运行日志，不含 API Key |
| `webview\` | WebView2 缓存 |

- 旧版本的明文 `config.json` 和明文历史会在首次启动时自动迁移为加密格式。
- 主密钥由 Windows DPAPI 保护，**绑定当前 Windows 账户和电脑**。把数据目录复制到别的电脑或换成别的 Windows 账户时，旧数据无法解密：程序会把 `config.dat`、`nexus.db` 等备份到 `backup-<时间>` 目录，然后以全新状态启动。
- 加密用于防止数据文件被直接拷走或读取；它不能防御已经以你的账户运行的恶意软件。
- 对话内容只在本机保存；调用模型时，消息会发送给你配置的模型服务（默认 DeepSeek）。

### 安装、升级与卸载

- 安装包会自动创建开始菜单快捷方式，安装向导可勾选桌面快捷方式。
- 升级时直接运行新安装包覆盖安装即可；设置与历史会保留。
- 在「设置 → 关于与更新」填写更新服务地址或 GitHub `owner/repo` 后，Nexus 会自动检查新版本；发现新版本可立即更新或暂不更新。更新包下载后先校验 SHA-256 再执行安装。
- 在「设置 → 应用和功能」或安装目录的 `uninstall.exe` 卸载。卸载时会询问是否删除 `%APPDATA%\Nexus` 中的数据；选择“否”可保留数据供以后重装使用。

### 常见问题

**双击后没有窗口？**  
程序默认显示悬浮球。查看屏幕右下角；若被其他窗口挡住，按 `Ctrl+Alt+Space` 打开主界面。

**提示 WebView2 不可用？**  
Windows 10/11 通常自带 WebView2。若精简系统缺失，请安装 Microsoft Edge WebView2 Runtime。

**SmartScreen 提示未知发布者？**  
当前安装包没有代码签名证书，选择“更多信息 → 仍要运行”。正式分发建议购买代码签名证书。

**悬浮球不见了？**  
右键悬浮球选择“打开主界面”，或在托盘图标菜单里重新显示。

**可以只复制 Nexus.exe 吗？**  
不可以。`_internal\` 和 `lib\app\` 都是运行必需目录。

### 从源码运行

环境：Windows 10/11、Python 3.11、Microsoft Edge WebView2 Runtime。

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

# 开发模式（带控制台）
python app\main.py

# 内核自检（加密存储、工具、Office/PDF、更新清单等）
python app\main.py --selftest
```

### 构建安装包

需要额外安装 `pyinstaller`、`markdown` 与 NSIS（`makensis`）。

```powershell
pip install pyinstaller markdown
python build\build_release.py
```

产物写入 `release\`：`Nexus-Setup-<版本>.exe`、`Nexus-Portable-<版本>.zip`、`SHA256SUMS.txt`。绿色包只用于本地测试，不作为官方发行物；构建脚本不会把 `data\` 打进压缩包。

### 项目结构

```text
app\main.py            启动器与 --selftest
app\ui.py              pywebview 桥、窗口与 IPC
app\core\              内核：agent、config、store、safety、tools、office、updater
app\web\               前端界面（HTML/CSS/JS）与图标、字体、xterm.js
build\                 构建脚本、PyInstaller spec、NSIS 安装脚本
site\                  官网（静态站，可在浏览器里直接试用）
docs\                  开发规划、设计、进度、日志、接口文档
```

### 许可证

源代码以 [MIT 许可证](LICENSE) 发布，Copyright (c) 2026 donghai。

安装包内含第三方组件，各自遵循其许可证，详见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。其中 `pystray` 为 LGPL-3.0，以未修改的库形式分发，可按需替换后重新打包。

---

## English

### Get and install

Official releases ship **the installer only**, `Nexus-Setup-<version>.exe`: run it, pick an install location if you like (default `%LOCALAPPDATA%\Programs\Nexus`), no administrator rights required.

The source is open under MIT, so you can run, modify, and build it yourself. The build script can also produce a portable folder locally, but the portable package is not an official release.

The app uses a split layout: `Nexus.exe` is only the entry point, dependencies live in `_internal\`, and application bytecode lives in `lib\app\`. Do not move `Nexus.exe` by itself. `lib\app\` contains compiled `.pyc` files only, with no `.py` sources.

### First run

1. On first launch Nexus opens a separate onboarding window: the Nexus orb guides you through your name and interface language, an uploaded or default avatar, model setup, appearance and launch-at-login, then naming the assistant and confirming how it should address you. Existing users with an API key go straight to the main window and skip onboarding.
2. After onboarding, the main window opens. Press `Ctrl+Alt+Space` anytime to open it again. Your name, avatar, and assistant name stay on this PC; there is no cloud account. The assistant name and your preferred form of address are written into the system prompt.
3. The API key is encrypted with Windows DPAPI and never written to logs.
4. Try prompts such as:
   - "My PC cannot access the internet, please check it."
   - "Write a weekly report about network maintenance."
   - "Create a single-file web page for my reading list."
   - "Open Notepad and type today's to-do list."

### Features

| Capability | Description |
| --- | --- |
| Chat | Streaming replies, stop, reasoning view, tool-call cards; no tool-round cap and the model decides when to reason; Markdown renders while streaming, with tables, headings, code blocks, quotes, and images |
| Chinese / English | Switch between Simplified Chinese, English, or Follow system; applies to the main window, Settings, History, quick panel, tray, and onboarding |
| Local profile | Display name, uploaded or default avatar, and assistant name, stored only on this PC |
| Settings center | Nine groups: account/language, model/API, context, runtime, shortcuts, notifications/appearance, files/data, performance, about/updates |
| Context compression | 128K / 1M tiers with live usage and a status-bar ring; click the ring to compress; at 50% the whole conversation becomes one summary; can be disabled |
| Output limit | Two tiers, 64K / 128K, sent as the request limit |
| Performance monitor | Settings > Performance shows live CPU/memory for the backend, the whole app (including WebView2), and the system, plus the last run’s average CPU and duration |
| API error details | Friendly message plus expandable HTTP status and raw server response |
| Diagnostics | System info, processes, services, ping / DNS / IP / proxy / ports |
| Network repair | Flush DNS, renew/release IP, reset Winsock (confirmation required) |
| Files & documents | Read, write, edit, search, batch lookup; Markdown / CSV / text output |
| Single-file pages | Inline CSS / JS / images; opens offline with a double-click |
| Screenshot Q&A | Full-screen or region screenshots sent to the model |
| Voice input | Local SenseVoice model; `Ctrl+Alt+V` to start/stop; no system speech service |
| PC automation | Enumerate windows, read UI trees, find controls, click and type (confirmation required) |
| Web search | DeepSeek Search / Fetch with page text extraction |
| Scheduled tasks | One-shot delayed or timed prompt runs, visible and cancellable in Settings |
| Runtime permissions | Safe (read-only) / Supervised (commands and program launches need approval; file writes do not) / Full access (autonomous; you bear the risk) |
| Auto update | Reads `update.json` from a self-hosted update service first, or checks GitHub Releases for a configured `owner/repo`; update now or postpone, with SHA-256 verification before install |

### Data and privacy

Default data folder: `%APPDATA%\Nexus`. The portable build uses `data\` next to `Nexus.exe`.

| File | Content and protection |
| --- | --- |
| `config.dat` | Settings, encrypted as a whole with AES-256-GCM. No plaintext `config.json` anymore |
| `secret.key` | 32-byte random master key, stored only as a Windows DPAPI ciphertext |
| `nexus.db` | Sessions, messages, tool runs, file index, audit log, schedules; sensitive fields are individually encrypted with AES-256-GCM |
| `files\` | Files generated for you (not encrypted) |
| `models\` | Local speech model, downloaded on first use |
| `logs\` | Runtime logs without API keys |
| `webview\` | WebView2 cache |

- Legacy plaintext `config.json` and history are migrated to the encrypted format automatically on first launch.
- The master key is protected by Windows DPAPI and is **bound to the current Windows account and PC**. If you copy the data folder to another PC or another Windows account, the old data cannot be decrypted: Nexus moves `config.dat`, `nexus.db`, etc. into `backup-<timestamp>` and starts fresh.
- Encryption protects data files from being copied and read directly. It cannot defend against malware already running under your account.
- Chat history stays on this PC. When calling the model, messages are sent to the model service you configure (DeepSeek by default).

### Install, upgrade and uninstall

- The installer creates a Start Menu shortcut and offers an optional desktop shortcut.
- To upgrade, run the new installer over the old installation. Settings and history are preserved.
- Fill in an update service URL or a GitHub `owner/repo` under Settings → About and updates to check for new versions. Nexus can update now or postpone, and verifies SHA-256 before installing.
- Uninstall from Settings → Apps or `uninstall.exe` in the install folder. The uninstaller asks whether to delete `%APPDATA%\Nexus`; choose No to keep your data for a later reinstall.

### FAQ

**Nothing appears after launch?**  
Nexus shows the floating orb by default. Look at the bottom-right corner of the screen, or press `Ctrl+Alt+Space`.

**WebView2 is missing?**  
Windows 10/11 usually includes it. On trimmed systems, install the Microsoft Edge WebView2 Runtime.

**SmartScreen warns about an unknown publisher?**  
The installer is not code-signed yet. Choose "More info → Run anyway". Code signing is recommended for public distribution.

**The orb disappeared?**  
Right-click the tray icon and choose to show the orb again.

**Can I copy only Nexus.exe?**  
No. Both `_internal\` and `lib\app\` are required.

### Build from source

Requirements: Windows 10/11, Python 3.11, Microsoft Edge WebView2 Runtime.

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

# Development (with console)
python app\main.py

# Self-test (encrypted storage, tools, Office/PDF, update manifest)
python app\main.py --selftest
```

To build the installer you also need `pyinstaller`, `markdown`, and NSIS (`makensis`):

```powershell
pip install pyinstaller markdown
python build\build_release.py
```

Artifacts are written to `release\`: `Nexus-Setup-<version>.exe`, `Nexus-Portable-<version>.zip`, and `SHA256SUMS.txt`. The portable package is for local testing only and is not an official release; the build never packs `data\` into the zip.

### Project layout

```text
app\main.py            entry point and --selftest
app\ui.py              pywebview bridge, windows, IPC
app\core\              kernel: agent, config, store, safety, tools, office, updater
app\web\               UI (HTML/CSS/JS), icons, fonts, xterm.js
build\                 build scripts, PyInstaller spec, NSIS installer script
site\                  official website (static, with an in-browser demo)
docs\                  planning, design, progress, changelog, API docs
```

### License

Source code is released under the [MIT License](LICENSE), Copyright (c) 2026 donghai.

Bundled third-party components keep their own licenses; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). `pystray` is LGPL-3.0, shipped unmodified and replaceable by rebuilding.
