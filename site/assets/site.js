/* Nexus 官网交互：双语、主题、网页试用对话（浏览器直连厂商接口） */
(function () {
  "use strict";

  /* ---------------- 语言 ---------------- */
  var EN = {
    "本地优先 · Windows 桌面 AI 助手": "Local-first · Windows desktop AI assistant",
    "能力": "Capabilities",
    "在线试用": "Live demo",
    "安全": "Security",
    "下载": "Download",
    "版本": "Versions",
    "常见问题": "FAQ",
    "最新版本": "Latest version",
    "每个版本，都让桌面更顺手一点": "Every release makes the desktop a little smoother",
    "安装包只从官网和 GitHub Releases 发布。下面是最新版本的内容，历史版本可在 GitHub 查看。":
      "Installer builds ship only from this site and GitHub Releases. Here is what changed in the latest version; older releases are on GitHub.",
    "最新": "Latest",
    "GitHub 发布页": "GitHub release",
    "多厂商模型接入：8 家内置厂商 + 自定义 OpenAI / Anthropic 兼容接口，每家 Key 独立加密保存":
      "Multi-provider models: 8 built-in providers plus custom OpenAI- or Anthropic-compatible endpoints, each key encrypted separately",
    "30+ 个工具：电脑诊断、网络修复、文件与文档、单文件网页、截图提问、本地语音、Windows UI 自动化":
      "30+ tools: PC diagnostics, network repair, files and documents, single-file pages, screenshot Q&A, local speech, Windows UI automation",
    "本地数据 AES-256-GCM 加密，主密钥由 Windows DPAPI 保护，不写日志":
      "Local data encrypted with AES-256-GCM; the master key is protected by Windows DPAPI and never written to logs",
    "自托管更新清单 update.json，下载后先校验 SHA-256 再安装":
      "Self-hosted update manifest (update.json) with SHA-256 verification before install",
    "PDF 阅读与页面渲染改用 PDFium，源码以 MIT 开源":
      "PDF reading and page rendering now use PDFium; source released under MIT",
    "从 GitHub 下载安装包": "Download from GitHub",
    "查看源代码": "View source",
    "当前版本": "Current version",
    "发布日期": "Released",
    "发布渠道": "Channels",
    "官网 · GitHub Releases": "This site · GitHub Releases",
    "切换语言": "Switch language",
    "下载 Windows 版": "Download for Windows",
    "把电脑，": "Your PC,",
    "交给一句话。": "handled in one sentence.",
    "说一句「帮我把网修好」或「把这堆资料做成 PPT」，Nexus 就去做。30+ 个工具接在桌面上：查网络、理文件、写文档、做网页、点按钮，都不用再一层层找菜单。":
      "Say “fix my network” or “turn this pile into a deck” and Nexus does it. 30+ tools sit on your desktop: diagnose, tidy files, write documents, build pages, click buttons — no menu digging.",
    "在浏览器里试用": "Try in your browser",
    "30+ 个工具": "30+ tools",
    "9 家模型厂商": "9 model providers",
    "双击即用": "Double-click to run",
    "30+ 个": "30+",
    "9 家": "9",
    "未配置": "Not set",
    "已配置": "Ready",
    "还没有配置厂商": "No provider configured yet",
    "已保存，仅存本机浏览器": "Saved in this browser only",
    "请填写 API Key": "Enter an API key",
    "接口地址需要以 http:// 或 https:// 开头": "Base URL must start with http:// or https://",
    "请选择或填写模型": "Choose or type a model",
    "已清除 Key": "API key cleared",
    "已删除该厂商配置": "Provider configuration removed",
    "缺少接口地址": "Missing base URL",
    "浏览器不支持流式响应": "This browser does not support streaming",
    "（没有返回内容）": "(empty response)",
    "已停止": "Stopped",
    "已停止生成": "Generation stopped",
    "出错了：": "Something went wrong: ",
    "请求失败": "Request failed",
    "请求失败：": "Request failed: ",
    "。若厂商不允许浏览器直连，请改用其他厂商或桌面版。": ". If this provider blocks browser requests, switch to another provider or use the desktop app.",
    "账户余额不足，请到厂商控制台充值或换一家厂商。": "Insufficient balance. Top up in the provider console or switch providers.",
    "Key 无效或没有权限，请检查后重试。": "Invalid key or no permission. Check it and try again.",
    "接口或模型不存在，请检查接口地址与模型 ID。": "Endpoint or model not found. Check the base URL and model ID.",
    "请求太频繁或额度用尽，稍后再试。": "Rate limited or out of quota. Try again later.",
    "先配置模型和 API Key": "Configure a model and API key first",
    "正在生成…": "Generating…",
    "演示版只保留当前会话": "The demo keeps only the current chat",
    "关闭": "Close",
    "删除配置": "Remove",
    "确定删除该厂商的配置吗？": "Remove this provider's configuration?",
    "先聊两句，再决定要不要装": "Try it before you install it",
    "下面是桌面版界面的 1:1 网页还原，不用安装就能聊。填一个你自己的 API Key 就能开始——不用注册，Key 只留在这台设备的浏览器里。":
      "A 1:1 web rebuild of the desktop app — no install needed. Add your own API key and start chatting; no sign-up, and the key stays in this browser.",
    "网页试用": "Web demo",
    "新对话": "New chat",
    "对话": "Chat",
    "模型设置": "Model settings",
    "最近对话": "Recent chats",
    "还没有对话": "No chats yet",
    "演示模式": "Demo mode",
    "网页演示": "Web demo",
    "切换外观": "Toggle theme",
    "演示": "Demo",
    "配置模型": "Configure models",
    "有什么可以帮你？": "What can I help with?",
    "网页版只做对话：写文案、解释概念、给代码片段": "The web demo only chats: copywriting, explanations, code snippets",
    "说说你想做什么…（Enter 发送，Shift+Enter 换行）": "Ask anything… (Enter to send, Shift+Enter for a new line)",
    "模型": "Model",
    "先配置模型": "Configure a model first",
    "Key 仅存本机浏览器": "Key stays in this browser",
    "发送": "Send",
    "配置 API Key…": "Set up an API key…",
    "Key 只保存在本机浏览器的 localStorage，不发送到任何中间服务器；对话会直接从浏览器请求厂商接口。":
      "The key is stored in this browser's localStorage only and is sent straight to the provider — never to an intermediate server of ours.",
    "厂商": "Provider",
    "收起": "Collapse",
    "接口地址": "Base URL",
    "保存并设为当前": "Save and use",
    "清除 Key": "Clear key",
    "三件事，一句话就够了": "Three jobs, one sentence",
    "电脑管家": "PC care",
    "网断了、变慢了、某个端口不通，直接问。系统信息、进程、服务、ping / DNS / IP / 代理 / 端口一次查完，再给出能照着做的修复步骤。":
      "Connection down, machine slow, port unreachable — just ask. System info, processes, services, ping / DNS / IP / proxy / ports in one pass, then fix steps you can actually follow.",
    "一句话跑完一轮网络诊断": "A full network check from one sentence",
    "进程、服务、磁盘占用一屏看清": "Processes, services and disk usage in one view",
    "修复命令直接给出，确认即执行": "Repair commands handed over, run on confirm",
    "知识助手": "Knowledge work",
    "把一堆散文件变成能交付的成品：Markdown、CSV、Word、Excel、PPT，或者 CSS、JS、图片全部内联的单文件网页，说一声就生成。":
      "Turn scattered files into something deliverable: Markdown, CSV, Word, Excel, PPT, or single-file pages with CSS, JS and images inlined.",
    "Word / Excel / PPT / PDF 读与写": "Reads and writes Word / Excel / PPT / PDF",
    "单文件网页，双击就能打开": "Single-file pages that open on double-click",
    "截图丢进来就能看图说话": "Drop in a screenshot and ask about it",
    "界面操作": "UI automation",
    "不是所有软件都有 API。Nexus 走 Windows UI 树，找到窗口里的按钮和输入框，把重复的点击和填写替你做掉。":
      "Not every app has an API. Nexus walks the Windows UI tree, finds the real buttons and fields, and does the repetitive clicking and typing for you.",
    "按控件名与类型精准定位": "Targets controls by name and type",
    "点击、输入、快捷键组合都能做": "Clicks, typing and key combos",
    "没有接口的老软件也能自动化": "Automates legacy apps without APIs",
    "放得开，也收得住": "Full power, with brakes",
    "它能读写文件、执行命令、操作界面，所以把权限做成了三档：只让它看、每一步问你、或者放手让它做，按场景随时切换。数据与密钥都留在这台机器上。":
      "It can read and write files, run commands and drive the UI — so permissions come in three tiers: watch only, ask every step, or let it run. Switch whenever the job changes. Data and keys stay on this machine.",
    "数据在你手里": "Your data, your machine",
    "历史、文件与配置都在这台机器上，换台电脑不会自动跟过去；备份与清理都由你决定。":
      "History, files and settings live on this machine — they do not follow you to another PC, and backup or cleanup is your call.",
    "密钥加密保存": "Keys encrypted at rest",
    "每家厂商的 API Key 独立加密（AES-256-GCM，密钥由 Windows DPAPI 保护），只有这台机器解得开。":
      "Each provider's API key is encrypted separately (AES-256-GCM, unlocked by Windows DPAPI) and only this machine can decrypt it.",
    "三档权限": "Three permission tiers",
    "安全 / 监管 / 全部下放：从只读工具到全量工具，一个开关切换，危险动作默认逐条确认。":
      "Safe / supervised / full: from read-only tools to the whole set, one switch, with risky actions confirmed by default.",
    "写入有边界": "Writes stay in bounds",
    "写文件只落在桌面、文档、下载、图片与输出目录；系统目录与浏览器凭据不在范围内。":
      "File writes land in Desktop, Documents, Downloads, Pictures and the output folder; system directories and browser credentials are out of scope.",
    "下载与更新": "Download and updates",
    "装上就能用，更新自动完成": "Install once, update automatically",
    "当前构建": "Current build",
    "安装包由独立下载通道分发；客户端会读取同一通道的 update.json 检查新版本，下载后校验 SHA-256 再安装。":
      "Installers come from a separate download endpoint; the app reads update.json there, verifies SHA-256, then installs.",
    "前往下载通道": "Open download endpoint",
    "查看更新清单": "View update manifest",
    "下载通道目前处于更新流程测试阶段，页面会标注模拟版本；稳定版安装包请以通道内标注为准。":
      "The download endpoint is currently rehearsing the update flow and labels simulated versions; follow the labels there for the stable build.",
    "稳定版": "Stable",
    "下载安装包": "Download installer",
    "复制 SHA-256": "Copy SHA-256",
    "已复制": "Copied",
    "双击安装，不需要预装 Python 或运行库；客户端内置自动更新，读取同一通道的 update.json 检查版本，下载后校验 SHA-256 再安装。":
      "Double-click to install — no Python or runtime needed. The app checks update.json on the same endpoint and verifies SHA-256 before installing.",
    "内置 WebView2": "WebView2 included",
    "支持离线诊断": "Offline diagnostics",
    "更新可断点续传": "Resumable updates",
    "安装包": "Installer",
    "自动更新": "Auto-update",
    "内置": "Built in",
    "运行环境": "Runtime",
    "依赖": "Dependencies",
    "内置 WebView2 运行时": "Bundled WebView2 runtime",
    "模型接入": "Model access",
    "8 家厂商 + 自定义": "8 providers + custom",
    "数据位置": "Data location",
    "本机数据目录": "Local data folder",
    "你可能想知道": "Things you may ask",
    "需要联网吗？": "Does it need the internet?",
    "对话需要连你配置的模型服务；文件、历史与配置都留在这台机器上，断网时网络诊断照样能用。":
      "Chat needs the model service you configured; files, history and settings stay on this machine, and network diagnostics still work offline.",
    "支持哪些模型？": "Which models are supported?",
    "内置小米 MiMo、火山方舟、DeepSeek、硅基流动、Kimi、智谱 GLM、MiniMax、通义千问，另可自定义 OpenAI 兼容或 Anthropic 兼容接口。每家 Key 独立保存，可同时配置多家。":
      "MiMo, Volcano Ark, DeepSeek, SiliconFlow, Kimi, Zhipu GLM, MiniMax and Qwen are built in, plus custom OpenAI- or Anthropic-compatible endpoints. Each key is stored separately, and several can be active at once.",
    "会不会乱动我的电脑？": "Will it touch my PC on its own?",
    "默认监管模式：命令执行、打开程序、删除文件与界面操作都会先问你；想让它自己跑，切到全部下放就行。":
      "Supervised by default: commands, app launches, deletions and UI actions ask first. Switch to full access when you want it to run on its own.",
    "网页试用和桌面版有什么区别？": "How is the web demo different?",
    "网页版只做对话；文件读写、命令执行与界面操作，装桌面版就能用。":
      "The web demo just chats. File access, commands and UI control come with the desktop app.",
    "网页版只做对话；桌面版有 30+ 个工具，能读写文件、执行命令、操作界面，也能记住你的历史与配置。":
      "The web demo only chats. The desktop app has 30+ tools, reads and writes files, runs commands, drives the UI, and remembers your history and settings.",
    "更新清单": "Update manifest",
    "本地优先 · 数据在你手里": "Local-first · your data stays yours",
    "下载与更新": "Download and updates",
    "示例：用一个比喻解释本地优先": "Try: explain local-first with one analogy",
    "示例：写一段 80 字内的发布文案": "Try: write an 80-word launch note",
    "示例：把这句话改得更简洁": "Try: tighten this sentence",
    "用一个比喻解释「本地优先」，控制在 80 字内。": "Explain “local-first” with one analogy, under 40 words.",
    "帮 Nexus 写一段 80 字以内的发布文案，语气克制。": "Write a restrained 80-word launch note for Nexus.",
    "把这句话改得更简洁：我们希望能够帮助用户在不需要了解命令行的情况下完成常见的电脑维护工作。":
      "Tighten this sentence: We hope to help users complete common PC maintenance work without needing to understand the command line."
  };

  function lang() {
    try { return localStorage.getItem("nexus.site.lang") === "en" ? "en" : "zh"; } catch (e) { return "zh"; }
  }
  function T(zh) {
    if (lang() !== "en") return zh;
    return EN[zh] || zh;
  }

  function applyLang() {
    var code = lang();
    document.documentElement.setAttribute("lang", code === "en" ? "en" : "zh-CN");
    var btns = document.querySelectorAll("[data-i18n]");
    for (var i = 0; i < btns.length; i++) {
      var el = btns[i];
      var zh = el.getAttribute("data-i18n");
      el.textContent = code === "en" ? (EN[zh] || zh) : zh;
    }
    var ph = document.querySelectorAll("[data-i18n-placeholder]");
    for (var j = 0; j < ph.length; j++) {
      var z = ph[j].getAttribute("data-i18n-placeholder");
      ph[j].setAttribute("placeholder", code === "en" ? (EN[z] || z) : z);
    }
    var ti = document.querySelectorAll("[data-i18n-title]");
    for (var k = 0; k < ti.length; k++) {
      var t = ti[k].getAttribute("data-i18n-title");
      ti[k].setAttribute("title", code === "en" ? (EN[t] || t) : t);
    }
    var langBtn = document.getElementById("langBtn");
    if (langBtn) langBtn.textContent = code === "en" ? "中文" : "EN";
    var title = document.getElementById("demoTitle");
    if (title) title.textContent = state.sessionTitle || T("新对话");
    renderChips();
    refreshPill();
    renderSessions();
  }

  /* ---------------- 主题 ---------------- */
  function currentTheme() {
    try { return localStorage.getItem("nexus.site.theme") === "dark" ? "dark" : "light"; } catch (e) { return "light"; }
  }
  function applyTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    try { localStorage.setItem("nexus.site.theme", theme); } catch (e) { /* ignore */ }
  }

  /* ---------------- 厂商目录 ---------------- */
  var PROVIDERS = [
    { id: "mimo", name: "小米 MiMo", nameEn: "Xiaomi MiMo", short: "MiMo", color: "#ff6900", mark: "Mi", icon: "assets/providers/mimo.png",
      base: "https://api.xiaomimimo.com/v1",
      models: [["mimo-v2.6-pro", "MiMo V2.6 Pro"], ["mimo-v2.6-flash", "MiMo V2.6 Flash"]] },
    { id: "ark", name: "火山方舟", nameEn: "Volcano Ark", short: "方舟", color: "#1664ff", mark: "方", icon: "assets/providers/ark.png",
      base: "https://ark.cn-beijing.volces.com/api/v3",
      models: [["doubao-seed-2-1-pro", "Doubao Seed 2.1 Pro"], ["doubao-seed-evolving", "Doubao Seed Evolving"], ["doubao-seed-2-1-lite", "Doubao Seed 2.1 Lite"]] },
    { id: "deepseek", name: "DeepSeek", nameEn: "DeepSeek", short: "DeepSeek", color: "#4d6bfe", mark: "DS", icon: "assets/providers/deepseek.png",
      base: "https://api.deepseek.com",
      models: [["deepseek-flash", "DeepSeek V4.1 Flash"], ["deepseek-v4-pro", "DeepSeek V4 Pro"]] },
    { id: "siliconflow", name: "硅基流动", nameEn: "SiliconFlow", short: "硅基流动", color: "#7c3aed", mark: "硅", icon: "assets/providers/siliconflow.png",
      base: "https://api.siliconflow.cn/v1",
      models: [["deepseek-ai/DeepSeek-V4.1-Flash", "DeepSeek V4.1 Flash"], ["Qwen/Qwen3.8-27B", "Qwen3.8 27B"], ["moonshotai/Kimi-K2.6", "Kimi K2.6"]] },
    { id: "kimi", name: "Kimi", nameEn: "Kimi", short: "Kimi", color: "#111827", mark: "K", icon: "assets/providers/kimi.png",
      base: "https://api.moonshot.cn/v1",
      models: [["kimi-k3.1-pro", "Kimi K3.1 Pro"], ["kimi-k3.1-pro-highspeed", "Kimi K3.1 Pro 高速版"]] },
    { id: "glm", name: "智谱 GLM", nameEn: "Zhipu GLM", short: "GLM", color: "#0e7490", mark: "G", icon: "assets/providers/glm.png",
      base: "https://open.bigmodel.cn/api/paas/v4",
      models: [["glm-5.3", "GLM-5.3"], ["glm-5.3-flash", "GLM-5.3 Flash"]] },
    { id: "minimax", name: "MiniMax", nameEn: "MiniMax", short: "MiniMax", color: "#e11d48", mark: "M", icon: "assets/providers/minimax.png",
      base: "https://api.minimaxi.com/v1",
      models: [["MiniMax-M3", "MiniMax M3"], ["MiniMax-M2.7", "MiniMax M2.7"]] },
    { id: "qwen", name: "通义千问", nameEn: "Qwen", short: "千问", color: "#2563eb", mark: "Q", icon: "assets/providers/qwen.png",
      base: "https://dashscope.aliyuncs.com/compatible-mode/v1",
      models: [["qwen3.8-max", "Qwen3.8 Max"], ["qwen3.8-flash", "Qwen3.8 Flash"]] },
    { id: "custom", name: "自定义", nameEn: "Custom", short: "自定义", color: "#64748b", mark: "+", icon: "",
      base: "", models: [] }
  ];

  function provider(id) {
    for (var i = 0; i < PROVIDERS.length; i++) if (PROVIDERS[i].id === id) return PROVIDERS[i];
    return null;
  }

  function pname(info) {
    if (!info) return "";
    return lang() === "en" ? (info.nameEn || info.name) : info.name;
  }

  function storeKey(id) { return "nexus.site.provider." + id; }

  function readProvider(id) {
    try {
      var raw = localStorage.getItem(storeKey(id));
      return raw ? JSON.parse(raw) : null;
    } catch (e) { return null; }
  }
  function writeProvider(id, data) {
    try { localStorage.setItem(storeKey(id), JSON.stringify(data)); } catch (e) { /* ignore */ }
  }
  function dropProvider(id) {
    try { localStorage.removeItem(storeKey(id)); } catch (e) { /* ignore */ }
  }
  function readActive() {
    try {
      var raw = localStorage.getItem("nexus.site.active");
      return raw ? JSON.parse(raw) : null;
    } catch (e) { return null; }
  }
  function writeActive(data) {
    try { localStorage.setItem("nexus.site.active", JSON.stringify(data)); } catch (e) { /* ignore */ }
  }

  function configuredIds() {
    var out = [];
    for (var i = 0; i < PROVIDERS.length; i++) {
      var item = readProvider(PROVIDERS[i].id);
      if (item && item.key) out.push(PROVIDERS[i].id);
    }
    return out;
  }

  function modelLabel(pid, model) {
    var info = provider(pid);
    if (info) {
      for (var i = 0; i < info.models.length; i++) {
        if (info.models[i][0] === model) return info.models[i][1];
      }
    }
    return model || "";
  }

  /* ---------------- 演示界面 ---------------- */
  var state = {
    provider: "",
    model: "",
    messages: [],
    streaming: false,
    abort: null,
    sessionTitle: ""
  };

  function $(sel) { return document.querySelector(sel); }

  function refreshPill() {
    var pillText = $("#demoPillText");
    var pillIcon = $("#demoPillIcon");
    if (!pillText) return;
    var active = readActive();
    if (!active || !active.provider || !active.model) {
      var ids = configuredIds();
      if (ids.length) {
        var info = provider(ids[0]);
        var saved = readProvider(ids[0]);
        state.provider = ids[0];
        state.model = (saved && saved.model) || info.models[0][0];
      }
      pillText.textContent = T("先配置模型");
      if (pillIcon) { pillIcon.hidden = true; pillIcon.removeAttribute("src"); }
      return;
    }
    state.provider = active.provider;
    state.model = active.model;
    var meta = provider(active.provider);
    if (pillIcon) {
      if (meta && meta.icon) { pillIcon.src = meta.icon; pillIcon.hidden = false; }
      else { pillIcon.hidden = true; pillIcon.removeAttribute("src"); }
    }
    var short = meta ? (lang() === "en" ? pname(meta) : meta.short) : active.provider;
    pillText.textContent = short + " · " + modelLabel(active.provider, active.model);
  }

  function renderChips() {
    var box = $("#demoChips");
    if (!box) return;
    var examples = [
      ["用一个比喻解释「本地优先」，控制在 80 字内。", "示例：用一个比喻解释本地优先"],
      ["帮 Nexus 写一段 80 字以内的发布文案，语气克制。", "示例：写一段 80 字内的发布文案"],
      ["把这句话改得更简洁：我们希望能够帮助用户在不需要了解命令行的情况下完成常见的电脑维护工作。", "示例：把这句话改得更简洁"]
    ];
    box.innerHTML = "";
    examples.forEach(function (pair) {
      var btn = document.createElement("button");
      btn.className = "chip";
      btn.type = "button";
      btn.textContent = T(pair[1]);
      btn.addEventListener("click", function () { sendMessage(pair[0]); });
      box.appendChild(btn);
    });
  }

  function renderSessions() {
    var box = $("#demoSessions");
    if (!box) return;
    box.innerHTML = "";
    if (!state.sessionTitle) {
      var empty = document.createElement("div");
      empty.className = "side-empty";
      empty.textContent = T("还没有对话");
      box.appendChild(empty);
      return;
    }
    var item = document.createElement("button");
    item.className = "side-item active";
    item.type = "button";
    item.textContent = state.sessionTitle;
    item.addEventListener("click", function () {
      setStatus(T("演示版只保留当前会话"), "");
    });
    box.appendChild(item);
  }

  function setStatus(text, kind) {
    var el = $("#demoStatus");
    if (!el) return;
    el.textContent = text || "";
    el.className = "demo-status" + (kind ? " " + kind : "");
  }

  function escapeHtml(text) {
    return String(text || "")
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  function renderMarkdown(text) {
    var raw = escapeHtml(text);
    var blocks = [];
    raw = raw.replace(/```([a-zA-Z0-9+#-]*)\n([\s\S]*?)```/g, function (m, langName, code) {
      blocks.push('<pre><code>' + code.replace(/\n$/, "") + "</code></pre>");
      return "\u0000BLOCK" + (blocks.length - 1) + "\u0000";
    });
    raw = raw.replace(/`([^`\n]+)`/g, "<code>$1</code>");
    raw = raw.replace(/\*\*([^*\n]+)\*\*/g, "<b>$1</b>");
    var lines = raw.split("\n");
    var html = "";
    var list = false;
    lines.forEach(function (line) {
      var placeholder = /^\u0000BLOCK(\d+)\u0000$/.exec(line.trim());
      if (placeholder) {
        if (list) { html += "</ul>"; list = false; }
        html += blocks[Number(placeholder[1])];
        return;
      }
      if (/^\s*[-*]\s+/.test(line)) {
        if (!list) { html += "<ul>"; list = true; }
        html += "<li>" + line.replace(/^\s*[-*]\s+/, "") + "</li>";
        return;
      }
      if (list) { html += "</ul>"; list = false; }
      if (line.trim() === "") return;
      html += "<p>" + line + "</p>";
    });
    if (list) html += "</ul>";
    return html || "<p></p>";
  }

  function ensureThread() {
    var thread = $("#demoThread");
    var empty = $("#demoEmpty");
    if (empty && empty.parentNode) empty.parentNode.removeChild(empty);
    return thread;
  }

  function addMessage(role, text) {
    var thread = ensureThread();
    var wrap = document.createElement("div");
    wrap.className = "msg " + (role === "user" ? "user" : "bot");
    if (role !== "user") {
      var avatar = document.createElement("span");
      avatar.className = "msg-avatar";
      wrap.appendChild(avatar);
    }
    var bubble = document.createElement("div");
    bubble.className = "bubble";
    if (role === "user") bubble.textContent = text;
    else bubble.innerHTML = renderMarkdown(text) + '<span class="caret"></span>';
    wrap.appendChild(bubble);
    thread.appendChild(wrap);
    scrollBottom();
    return bubble;
  }

  function scrollBottom() {
    var box = $("#demoMessages");
    if (box) box.scrollTop = box.scrollHeight;
  }

  function setBusy(busy) {
    state.streaming = busy;
    var btn = $("#demoSend");
    if (btn) btn.classList.toggle("stop", busy);
  }

  function systemPrompt() {
    if (lang() === "en") {
      return "You are the web demo assistant on the Nexus site. Be concise and practical. You can only chat: no file access, no commands, no UI control. If asked about local abilities, say the Windows desktop app provides them.";
    }
    return "你是 Nexus 官网的网页演示助手。回答简洁、可操作，优先给步骤或成品文本。你只能对话，不能读写文件、不能执行命令、不能操作电脑；被问及本地能力时，说明 Windows 桌面版可以做到。";
  }

  function buildPayload() {
    var messages = [{ role: "system", content: systemPrompt() }];
    state.messages.slice(-20).forEach(function (item) {
      messages.push({ role: item.role, content: item.content });
    });
    return { model: state.model, messages: messages, stream: true, temperature: 0.7 };
  }

  function friendlyError(err, status) {
    if (status === 401 || status === 403) {
      return T("Key 无效或没有权限，请检查后重试。");
    }
    if (status === 402) {
      return T("账户余额不足，请到厂商控制台充值或换一家厂商。");
    }
    if (status === 404) {
      return T("接口或模型不存在，请检查接口地址与模型 ID。");
    }
    if (status === 429) {
      return T("请求太频繁或额度用尽，稍后再试。");
    }
    if (status) {
      return T("请求失败") + "（HTTP " + status + "）";
    }
    return T("请求失败：") + (err && err.message ? err.message : String(err)) +
      T("。若厂商不允许浏览器直连，请改用其他厂商或桌面版。");
  }

  async function sendMessage(explicit) {
    var input = $("#demoInput");
    var text = String(explicit != null ? explicit : (input ? input.value : "")).trim();
    if (!text || state.streaming) return;

    var active = readActive();
    if (!active || !active.provider || !active.model) {
      setStatus(T("先配置模型和 API Key"), "error");
      openConfig(active && active.provider ? active.provider : "deepseek");
      return;
    }
    var saved = readProvider(active.provider);
    if (!saved || !saved.key) {
      setStatus(T("先配置模型和 API Key"), "error");
      openConfig(active.provider);
      return;
    }

    state.provider = active.provider;
    state.model = active.model;
    if (input) { input.value = ""; input.style.height = "auto"; }
    if (!state.sessionTitle) {
      state.sessionTitle = text.length > 18 ? text.slice(0, 18) + "…" : text;
      var title = $("#demoTitle");
      if (title) title.textContent = state.sessionTitle;
      renderSessions();
    }

    state.messages.push({ role: "user", content: text });
    addMessage("user", text);
    setBusy(true);
    setStatus(T("正在生成…"), "");

    var bubble = addMessage("assistant", "");
    var buffer = "";
    var controller = new AbortController();
    state.abort = controller;

    try {
      var base = String(saved.base || (provider(active.provider) || {}).base || "").replace(/\/+$/, "");
      if (!base) throw new Error(T("缺少接口地址"));
      var resp = await fetch(base + "/chat/completions", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Authorization": "Bearer " + saved.key
        },
        body: JSON.stringify(buildPayload()),
        signal: controller.signal
      });
      if (!resp.ok) {
        var detail = "";
        try {
          var data = await resp.json();
          detail = (data && data.error && (data.error.message || data.error.code)) || "";
        } catch (e) { /* ignore */ }
        throw { status: resp.status, detail: detail };
      }
      if (!resp.body) throw new Error(T("浏览器不支持流式响应"));

      var reader = resp.body.getReader();
      var decoder = new TextDecoder("utf-8");
      var pending = "";
      while (true) {
        var chunk = await reader.read();
        if (chunk.done) break;
        pending += decoder.decode(chunk.value, { stream: true });
        var parts = pending.split("\n\n");
        pending = parts.pop();
        for (var i = 0; i < parts.length; i++) {
          var block = parts[i].trim();
          if (!block) continue;
          var lines = block.split("\n");
          for (var j = 0; j < lines.length; j++) {
            var line = lines[j];
            if (line.indexOf("data:") !== 0) continue;
            var payload = line.slice(5).trim();
            if (!payload || payload === "[DONE]") continue;
            var obj = null;
            try { obj = JSON.parse(payload); } catch (e) { continue; }
            var choice = obj && obj.choices && obj.choices[0];
            var delta = choice && choice.delta;
            if (delta && delta.content) {
              buffer += delta.content;
              bubble.innerHTML = renderMarkdown(buffer) + '<span class="caret"></span>';
              scrollBottom();
            }
          }
        }
      }
      if (!buffer) buffer = T("（没有返回内容）");
      bubble.innerHTML = renderMarkdown(buffer);
      state.messages.push({ role: "assistant", content: buffer });
      setStatus("", "");
    } catch (err) {
      if (err && err.name === "AbortError") {
        bubble.innerHTML = renderMarkdown(buffer || T("已停止"));
        if (buffer) state.messages.push({ role: "assistant", content: buffer });
        setStatus(T("已停止生成"), "");
      } else {
        var message = err && err.status
          ? friendlyError(err, err.status) + (err.detail ? "：" + err.detail : "")
          : friendlyError(err, 0);
        bubble.innerHTML = renderMarkdown(T("出错了：") + message);
        if (state.messages.length && state.messages[state.messages.length - 1].role === "user") {
          state.messages.pop();
        }
        setStatus(message, "error");
      }
    } finally {
      state.abort = null;
      setBusy(false);
      scrollBottom();
    }
  }

  function stopStreaming() {
    if (state.abort) state.abort.abort();
  }

  /* ---------------- 模型菜单 ---------------- */
  function toggleMenu(sel) {
    var el = $(sel);
    if (!el) return;
    var hidden = el.hidden;
    closeMenus();
    el.hidden = !hidden;
  }
  function closeMenus() {
    ["#demoModelMenu"].forEach(function (sel) {
      var el = $(sel);
      if (el) el.hidden = true;
    });
  }

  function renderMenu() {
    var list = $("#demoModelList");
    if (!list) return;
    list.innerHTML = "";
    var ids = configuredIds();
    if (!ids.length) {
      var empty = document.createElement("button");
      empty.className = "menu-row";
      empty.type = "button";
      empty.textContent = T("还没有配置厂商");
      empty.addEventListener("click", function () { closeMenus(); openConfig("deepseek"); });
      list.appendChild(empty);
      return;
    }
    var active = readActive() || {};
    ids.forEach(function (pid) {
      var info = provider(pid);
      var saved = readProvider(pid) || {};
      var label = document.createElement("div");
      label.className = "menu-label";
      if (info.icon) {
        var img = document.createElement("img");
        img.src = info.icon;
        img.alt = "";
        label.appendChild(img);
      }
      var name = document.createElement("span");
      name.textContent = pname(info);
      label.appendChild(name);
      list.appendChild(label);
      var models = (saved.models && saved.models.length) ? saved.models : info.models.map(function (m) { return m[0]; });
      var current = saved.model || models[0];
      if (models.indexOf(current) < 0) models = [current].concat(models);
      models.forEach(function (mid) {
        var row = document.createElement("button");
        row.className = "menu-row";
        row.type = "button";
        row.dataset.model = mid;
        row.dataset.provider = pid;
        row.dataset.selected = (active.provider === pid && active.model === mid) ? "1" : "0";
        var span = document.createElement("span");
        span.textContent = modelLabel(pid, mid);
        var check = document.createElement("b");
        check.className = "menu-check";
        row.appendChild(span);
        row.appendChild(check);
        row.addEventListener("click", function () {
          writeActive({ provider: pid, model: mid });
          closeMenus();
          refreshPill();
          setStatus("", "");
        });
        list.appendChild(row);
      });
    });
  }

  /* ---------------- 配置弹窗 ---------------- */
  var configProvider = "deepseek";

  function markEl(info) {
    var mark = document.createElement("span");
    mark.className = "provider-mark";
    if (info.icon) {
      mark.classList.add("has-icon");
      var img = document.createElement("img");
      img.src = info.icon;
      img.alt = "";
      mark.appendChild(img);
    } else {
      mark.textContent = info.mark || "AI";
      mark.style.background = info.color || "#64748b";
    }
    return mark;
  }

  function renderProviderGrid() {
    var grid = $("#demoProviderGrid");
    if (!grid) return;
    grid.innerHTML = "";
    var active = readActive() || {};
    PROVIDERS.forEach(function (info) {
      var saved = readProvider(info.id);
      var configured = !!(saved && saved.key);
      var card = document.createElement("button");
      card.type = "button";
      card.className = "provider-card" +
        (configured ? " configured" : "") +
        (configProvider === info.id ? " selected" : "") +
        (active.provider === info.id ? " active" : "");
      card.style.setProperty("--provider-color", info.color || "#64748b");
      var head = document.createElement("div");
      head.className = "provider-card-head";
      head.appendChild(markEl(info));
      var name = document.createElement("span");
      name.className = "provider-card-name";
      name.textContent = pname(info);
      head.appendChild(name);
      var note = document.createElement("div");
      note.className = "provider-card-note";
      note.textContent = configured ? (saved.model || info.models[0][0]) : T("未配置");
      var foot = document.createElement("div");
      foot.className = "provider-card-foot";
      var badge = document.createElement("span");
      badge.className = "provider-state" + (configured ? " on" : "");
      badge.textContent = configured ? T("已配置") : T("未配置");
      foot.appendChild(badge);
      card.appendChild(head);
      card.appendChild(note);
      card.appendChild(foot);
      card.addEventListener("click", function () { selectConfigProvider(info.id); });
      grid.appendChild(card);
    });
  }

  function selectConfigProvider(id) {
    configProvider = id;
    var info = provider(id);
    var saved = readProvider(id) || {};
    var detail = $("#demoProviderDetail");
    if (!info || !detail) return;
    detail.hidden = false;
    var mark = $("#demoPdMark");
    mark.innerHTML = "";
    mark.className = "provider-mark" + (info.icon ? " has-icon" : "");
    if (info.icon) {
      var img = document.createElement("img");
      img.src = info.icon;
      img.alt = "";
      mark.appendChild(img);
    } else {
      mark.textContent = info.mark;
      mark.style.background = info.color;
    }
    $("#demoPdName").textContent = pname(info);
    $("#demoPdKind").textContent = "OpenAI";
    $("#demoKeyInput").value = saved.key || "";
    $("#demoBaseInput").value = saved.base || info.base || "";
    $("#demoBaseInput").placeholder = info.base || "https://api.example.com/v1";

    var sel = $("#demoModelSelect");
    var text = $("#demoModelInput");
    var models = (saved.models && saved.models.length) ? saved.models : info.models.map(function (m) { return m[0]; });
    if (info.id === "custom" || !models.length) {
      sel.hidden = true;
      text.hidden = false;
      text.value = saved.model || "";
    } else {
      sel.hidden = false;
      text.hidden = true;
      sel.innerHTML = "";
      models.forEach(function (mid) {
        var opt = document.createElement("option");
        opt.value = mid;
        opt.textContent = modelLabel(id, mid);
        sel.appendChild(opt);
      });
      sel.value = saved.model && models.indexOf(saved.model) >= 0 ? saved.model : models[0];
    }
    $("#demoKeyStatus").className = "field-status";
    $("#demoKeyStatus").textContent = "";
    renderProviderGrid();
  }

  function openConfig(id) {
    closeMenus();
    var mask = $("#demoConfigMask");
    if (!mask) return;
    mask.hidden = false;
    selectConfigProvider(id || configProvider || "deepseek");
  }
  function closeConfig() {
    var mask = $("#demoConfigMask");
    if (mask) mask.hidden = true;
  }

  function saveConfig() {
    var info = provider(configProvider);
    if (!info) return;
    var key = String($("#demoKeyInput").value || "").trim();
    var base = String($("#demoBaseInput").value || "").trim().replace(/\/+$/, "");
    var model = info.id === "custom" || !info.models.length
      ? String($("#demoModelInput").value || "").trim()
      : $("#demoModelSelect").value;
    if (!key) {
      $("#demoKeyStatus").className = "field-status fail";
      $("#demoKeyStatus").textContent = T("请填写 API Key");
      return;
    }
    if (!/^https?:\/\//i.test(base)) {
      $("#demoKeyStatus").className = "field-status fail";
      $("#demoKeyStatus").textContent = T("接口地址需要以 http:// 或 https:// 开头");
      return;
    }
    if (!model) {
      $("#demoKeyStatus").className = "field-status fail";
      $("#demoKeyStatus").textContent = T("请选择或填写模型");
      return;
    }
    var models = info.models.map(function (m) { return m[0]; });
    if (models.indexOf(model) < 0) models.unshift(model);
    writeProvider(info.id, { key: key, base: base, model: model, models: models, name: info.name });
    writeActive({ provider: info.id, model: model });
    $("#demoKeyStatus").className = "field-status ok";
    $("#demoKeyStatus").textContent = T("已保存，仅存本机浏览器");
    refreshPill();
    renderProviderGrid();
    setStatus("", "");
  }

  function clearConfig() {
    dropProvider(configProvider);
    var active = readActive();
    if (active && active.provider === configProvider) {
      try { localStorage.removeItem("nexus.site.active"); } catch (e) { /* ignore */ }
    }
    $("#demoKeyInput").value = "";
    $("#demoKeyStatus").className = "field-status";
    $("#demoKeyStatus").textContent = T("已删除该厂商配置");
    refreshPill();
    renderProviderGrid();
  }

  /* ---------------- 事件绑定 ---------------- */
  function bind() {
    var langBtn = $("#langBtn");
    if (langBtn) {
      langBtn.addEventListener("click", function () {
        try { localStorage.setItem("nexus.site.lang", lang() === "en" ? "zh" : "en"); } catch (e) { /* ignore */ }
        applyLang();
      });
    }
    var themeBtn = $("#demoThemeBtn");
    if (themeBtn) {
      themeBtn.addEventListener("click", function () {
        applyTheme(currentTheme() === "dark" ? "light" : "dark");
      });
    }

    var input = $("#demoInput");
    if (input) {
      input.addEventListener("input", function () {
        input.style.height = "auto";
        input.style.height = Math.min(input.scrollHeight, 160) + "px";
      });
      input.addEventListener("keydown", function (e) {
        if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
          e.preventDefault();
          if (state.streaming) return;
          sendMessage();
        }
      });
    }

    var send = $("#demoSend");
    if (send) {
      send.addEventListener("click", function () {
        if (state.streaming) stopStreaming();
        else sendMessage();
      });
    }

    var newChat = $("#demoNewChat");
    if (newChat) {
      newChat.addEventListener("click", function () {
        if (state.streaming) stopStreaming();
        state.messages = [];
        state.sessionTitle = "";
        var thread = $("#demoThread");
        if (thread) {
          thread.innerHTML =
            '<div class="empty" id="demoEmpty">' +
            '<div class="empty-mark"><span class="mark-ring"></span><span class="mark-dot"></span></div>' +
            "<h1>" + escapeHtml(T("有什么可以帮你？")) + "</h1>" +
            "<p>" + escapeHtml(T("网页版只做对话：写文案、解释概念、给代码片段")) + "</p>" +
            '<div class="chips" id="demoChips"></div>' +
            "</div>";
          renderChips();
        }
        var title = $("#demoTitle");
        if (title) title.textContent = T("新对话");
        renderSessions();
        setStatus("", "");
      });
    }

    var pill = $("#demoModelPill");
    if (pill) {
      pill.addEventListener("click", function (e) {
        e.stopPropagation();
        toggleMenu("#demoModelMenu");
        renderMenu();
      });
    }
    var menuConfig = $("#demoMenuConfig");
    if (menuConfig) {
      menuConfig.addEventListener("click", function () {
        closeMenus();
        openConfig(configProvider);
      });
    }
    document.addEventListener("click", function (e) {
      var menu = $("#demoModelMenu");
      if (menu && !menu.hidden) {
        if (!menu.contains(e.target) && !(pill && pill.contains(e.target))) menu.hidden = true;
      }
    });

    document.querySelectorAll("[data-demo-view]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        if (btn.getAttribute("data-demo-view") === "settings") {
          openConfig(configProvider || "deepseek");
        } else {
          closeConfig();
        }
      });
    });

    var configBtn = $("#demoConfigBtn");
    if (configBtn) configBtn.addEventListener("click", function () { openConfig(configProvider); });

    var mask = $("#demoConfigMask");
    if (mask) {
      mask.addEventListener("click", function (e) {
        if (e.target === mask) closeConfig();
      });
    }
    var close = $("#demoPdClose");
    if (close) {
      close.addEventListener("click", function () {
        var detail = $("#demoProviderDetail");
        if (detail) detail.hidden = true;
      });
    }
    var modalClose = $("#demoConfigClose");
    if (modalClose) modalClose.addEventListener("click", closeConfig);

    var saveBtn = $("#demoSaveKey");
    if (saveBtn) saveBtn.addEventListener("click", saveConfig);
    var copySha = $("#copySha");
    if (copySha) {
      copySha.addEventListener("click", async function () {
        var value = "EAE312F67D27C55B86A77D7410F40B595CA1C93FB7EB0ACF4976C209587C7141";
        try {
          await navigator.clipboard.writeText(value);
        } catch (e) {
          var helper = document.createElement("textarea");
          helper.value = value;
          document.body.appendChild(helper);
          helper.select();
          document.execCommand("copy");
          document.body.removeChild(helper);
        }
        var original = T("复制 SHA-256");
        copySha.textContent = T("已复制");
        setTimeout(function () { copySha.textContent = original; }, 1600);
      });
    }
    var clearBtn = $("#demoClearKey");
    if (clearBtn) {
      clearBtn.addEventListener("click", function () {
        if (!window.confirm(T("确定删除该厂商的配置吗？"))) return;
        clearConfig();
      });
    }

    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") {
        closeMenus();
        closeConfig();
      }
    });

    /* 滚动进入 */
    var targets = document.querySelectorAll(".m-section, .m-demo, .m-download, .m-faq");
    if ("IntersectionObserver" in window) {
      var io = new IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) {
            entry.target.classList.add("in");
            io.unobserve(entry.target);
          }
        });
      }, { threshold: 0.08 });
      targets.forEach(function (el) {
        el.classList.add("reveal");
        io.observe(el);
      });
    }
  }

  /* ---------------- 启动 ---------------- */
  applyTheme(currentTheme());
  bind();
  applyLang();
  refreshPill();
  renderSessions();
})();
