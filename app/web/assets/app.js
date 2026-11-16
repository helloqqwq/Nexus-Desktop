/* Nexus 前端逻辑：侧栏、对话、工具卡片、命令/引用、设置、历史、确认弹窗 */
(function () {
  'use strict';

  const $ = (sel) => document.querySelector(sel);
  const T = (text) => (window.NexusI18n ? window.NexusI18n.t(text) : text);
  const TF = (text, vars) => (window.NexusI18n ? window.NexusI18n.tf(text, vars) : text);
  const S = {
    booted: false,
    sessionId: null,
    sessionTitle: '新对话',
    streaming: false,
    attachments: [],
    scenes: [],
    skills: [],
    activeSkill: null,
    editingSkill: null,
    prompts: [],
    editingPrompt: null,
    memories: [],
    editingMemory: null,
    settings: {},
    settingsPage: 'groupAccount',
    settingsProvider: '',
    providerDraftModels: [],
    providerDraftModel: '',
    providerDraftKind: 'openai',
    assistantName: 'Nexus',
    theme: 'light',
    themeMode: 'light',
    accent: 'blue',
    profile: { name: '', avatar: 'default', color: 'blue' },
    profileDraft: null,
    view: 'chat',
    contextTokens: 0,
    contextLimit: 131072,
    contextPercent: 0,
    contextSummarized: false,
    compressing: false,
    updateInfo: null,
    updateReady: false,
    msgs: {},
    current: null,
    typingEl: null,
    confirmId: null,
    askId: null,
    histKind: 'sessions',
    status: 'idle',
    meta: {},
    sideSessions: [],
    sideLoaded: false,
    fileCache: null,
    lastUserText: '',
    lastAssistant: null,
    runStart: 0,
    runRounds: 0,
    runSteps: 0,
    runDuration: 0,
    trigger: null,
    triggerIndex: 0,
    triggerItems: [],
    dragDepth: 0,
    rightOpen: false,
    rpWidth: 0,
    tree: null,
    treeRoot: '',
    treeSig: '',
    expanded: [],
    treeTimer: null,
    searchTimer: null,
    rpQuery: '',
    rpMode: 'tree',
    rpTabs: [],
    rpActive: '',
    rpSeq: 0,
    shells: null,
    shellsPromise: null,
    embedSuppress: false,
    previewPath: '',
    previewData: null,
    editMode: false,
    mdDirty: false,
    mdDraft: null,
    pdfPage: 0,
    pdfZoom: 1.4,
    docxMode: 'render',
    docxDirty: false,
    docxEdits: {},
    xlsxDirty: false,
    xlsxEdits: {},
    xlsxSheet: '',
    xlsxSel: 'A1',
    pptIndex: 0,
    pptMode: 'render',
    pptDirty: false,
    pptEdits: {},
    pptData: null,
    rpManualClosed: false,
    voiceActive: false,
    voiceBase: '',
    voicePartial: '',
    voiceStart: 0,
    voiceTimer: null,
    voiceLevel: 0,
    voiceBands: [],
    voiceWaveTimer: null,
  };
  let scrollQueued = false;
  let followBottom = true;
  const BOTTOM_GAP = 80;
  let perfBusy = false;
  let statusHtml = '';

  const MODEL_NAMES = {
    'deepseek-flash': 'DeepSeek Flash',
    'deepseek-v4-pro': 'DeepSeek V4 Pro',
  };
  const EFFORT_NAMES = { high: '高', max: '最高' };
  const TEXT_EXT = ['txt', 'md', 'markdown', 'json', 'py', 'js', 'ts', 'html', 'css',
    'csv', 'log', 'yaml', 'yml', 'ini', 'xml', 'toml', 'bat', 'ps1', 'sh', 'sql'];

  const TOOL_LABELS = {
    fs_read: '读取文件', fs_write: '写入文件', fs_edit: '修改文件',
    fs_list: '查看文件夹', fs_search: '搜索文件',
    shell_run: '执行诊断命令', net_diag: '网络诊断',
    proc_list: '查看进程', sys_info: '系统信息', service_list: '查看服务',
    app_open: '打开文件', app_launch: '打开程序', screenshot_capture: '屏幕截图', todo_write: '更新任务清单',
    ui_windows: '查看窗口', ui_tree: '读取界面', ui_find: '查找控件', ui_act: '操作界面',
    release_control: '交还控制权',
    fs_delete: '删除文件', fs_glob: '查找文件', web_search: '联网搜索', web_fetch: '读取网页',
    ask_user: '向你提问', notify_user: '发送通知', shell_exec: '执行命令',
    schedule_task: '创建定时任务', list_schedules: '查看定时任务', cancel_schedule: '取消定时任务',
    office_read: '读取办公文档', docx_write: '生成 Word', xlsx_write: '生成 Excel',
    pptx_write: '生成 PPT', html_to_pptx: 'HTML 转 PPT', office_edit: '编辑办公文档',
  };

  const COMMANDS = [
    { cmd: 'new', label: '新对话', desc: '清空并开始新对话', icon: '+', run: function () { newChat(); } },
    { cmd: 'clear', label: '清空当前对话', desc: '只清空界面，不删除记录', icon: '×', run: clearChat },
    { cmd: 'history', label: '历史记录', desc: '过去的对话、文件与排查记录', icon: '◷', run: function () { switchView('history'); } },
    { cmd: 'settings', label: '设置', desc: '模型、快捷键与数据目录', icon: '⚙', run: function () { switchView('settings'); } },
    { cmd: 'model', label: '切换模型', desc: '模型与推理强度', icon: '◎', run: openModelMenu },
    { cmd: 'shot', label: '截图', desc: '截取整个屏幕并附到对话', icon: '▣', run: function () { capture(); } },
    { cmd: 'region', label: '区域截图', desc: '框选屏幕区域', icon: '▢', run: function () { capture('region'); } },
    { cmd: 'voice', label: '语音输入', desc: '打开 Windows 语音输入', icon: '◉', run: startVoice },
    { cmd: 'file', label: '引用文件', desc: '选择本地文件并插入路径', icon: '@', run: pickFileReference },
    { cmd: 'stop', label: '停止回答', desc: '中断当前生成', icon: '■', run: function () { call('stop'); } },
    { cmd: 'help', label: '快捷键', desc: '查看全部快捷键', icon: '?', run: openHelp },
  ];

  const threadEl = () => $('#thread');

  function api() {
    return window.pywebview && window.pywebview.api;
  }

  async function call(name) {
    const a = api();
    if (!a || typeof a[name] !== 'function') {
      toast('界面还未就绪，请稍等一下');
      return null;
    }
    const args = Array.prototype.slice.call(arguments, 1);
    try {
      return await a[name].apply(a, args);
    } catch (e) {
      toast('操作失败：' + (e && e.message ? e.message : e));
      return null;
    }
  }

  /* ---------------- Markdown ---------------- */
  function esc(text) {
    return String(text == null ? '' : text)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  function mdTableSep(line) {
    const t = String(line || '').trim();
    return t.indexOf('-') >= 0 &&
      /^\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?$/.test(t);
  }

  function mdRow(line) {
    let t = String(line || '').trim();
    if (t.charAt(0) === '|') t = t.slice(1);
    if (t.charAt(t.length - 1) === '|') t = t.slice(0, -1);
    return t.split('|').map(function (c) { return c.trim(); });
  }

  function mdCell(tag, content, align) {
    const style = align ? ' style="text-align:' + align + '"' : '';
    return '<' + tag + style + '>' + content + '</' + tag + '>';
  }

  function renderMarkdown(text) {
    const codes = [];
    let s = String(text || '').replace(/```([a-zA-Z0-9_+-]*)\r?\n?([\s\S]*?)(?:```|$)/g,
      function (m, lang, code) {
        codes.push('<pre><code>' + esc(code.replace(/\r?\n$/, '')) + '</code></pre>');
        return '\n@@CODE' + (codes.length - 1) + '@@\n';
      });
    s = esc(s);
    const inlines = [];
    s = s.replace(/`([^`\n]+)`/g, function (m, code) {
      inlines.push('<code>' + code + '</code>');
      return '@@IC' + (inlines.length - 1) + '@@';
    });
    s = s.replace(/!\[([^\]\n]*)\]\((https?:\/\/[^\s)]+)\)/g,
      '<img src="$2" alt="$1" loading="lazy">');
    s = s.replace(/\[([^\]\n]+)\]\((https?:\/\/[^\s)]+)\)/g,
      '<a href="$2" target="_blank" rel="noreferrer">$1</a>');
    s = s.replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>');
    s = s.replace(/~~([^~\n]+)~~/g, '<del>$1</del>');
    s = s.replace(/(^|[^*])\*([^*\n]+)\*(?!\*)/g, '$1<em>$2</em>');

    const lines = s.split(/\r?\n/);
    const out = [];
    let list = null;
    let para = [];

    function flushList() {
      if (list) { out.push('</' + list + '>'); list = null; }
    }
    function flushPara() {
      if (para.length) { out.push('<p>' + para.join('<br>') + '</p>'); para = []; }
    }
    function flush() { flushList(); flushPara(); }

    for (let i = 0; i < lines.length; i++) {
      const line = lines[i].trim();
      const cm = line.match(/^@@CODE(\d+)@@$/);
      if (cm) { flush(); out.push(codes[+cm[1]]); continue; }
      if (!line) { flush(); continue; }
      if (line.indexOf('|') >= 0 && i + 1 < lines.length && mdTableSep(lines[i + 1])) {
        flush();
        const head = mdRow(line);
        const aligns = mdRow(lines[i + 1]).map(function (c) {
          const left = c.charAt(0) === ':';
          const right = c.charAt(c.length - 1) === ':';
          return left && right ? 'center' : (right ? 'right' : (left ? 'left' : ''));
        });
        let html = '<div class="md-table-wrap"><table><thead><tr>';
        for (let c = 0; c < head.length; c++) html += mdCell('th', head[c], aligns[c]);
        html += '</tr></thead><tbody>';
        i += 2;
        while (i < lines.length) {
          const row = lines[i].trim();
          if (!row || row.indexOf('|') < 0 || mdTableSep(row)) break;
          const cells = mdRow(row);
          html += '<tr>';
          for (let c = 0; c < cells.length; c++) html += mdCell('td', cells[c], aligns[c]);
          html += '</tr>';
          i++;
        }
        i -= 1;
        out.push(html + '</tbody></table></div>');
        continue;
      }
      if (/^(\*\s*){3,}$/.test(line) || /^(-\s*){3,}$/.test(line) || /^(_\s*){3,}$/.test(line)) {
        flush();
        out.push('<hr>');
        continue;
      }
      const h = line.match(/^(#{1,6})\s+(.*)$/);
      if (h) {
        flush();
        const lv = Math.min(6, h[1].length + 1);
        out.push('<h' + lv + '>' + h[2] + '</h' + lv + '>');
        continue;
      }
      const ul = line.match(/^[-*+]\s+(.*)$/);
      if (ul) {
        if (list !== 'ul') { flushList(); flushPara(); out.push('<ul>'); list = 'ul'; }
        out.push('<li>' + ul[1] + '</li>');
        continue;
      }
      const ol = line.match(/^\d+[.)]\s+(.*)$/);
      if (ol) {
        if (list !== 'ol') { flushList(); flushPara(); out.push('<ol>'); list = 'ol'; }
        out.push('<li>' + ol[1] + '</li>');
        continue;
      }
      if (line.indexOf('&gt;') === 0) {
        flush();
        const quote = [];
        while (i < lines.length) {
          const q = lines[i].trim();
          if (q.indexOf('&gt;') !== 0) break;
          quote.push(q.slice(4).replace(/^\s/, ''));
          i++;
        }
        i -= 1;
        out.push('<blockquote>' + quote.join('<br>') + '</blockquote>');
        continue;
      }
      flushList();
      para.push(line);
    }
    flush();
    return out.join('').replace(/@@IC(\d+)@@/g, function (m, i) { return inlines[+i]; });
  }

  /* ---------------- 消息渲染 ---------------- */
  function hideEmpty() {
    const empty = $('#empty');
    if (empty) empty.style.display = 'none';
  }

  function showEmpty() {
    const empty = $('#empty');
    if (empty) empty.style.display = '';
  }

  function clearMessages() {
    const box = threadEl();
    Array.prototype.slice.call(box.querySelectorAll('.msg')).forEach(function (n) { n.remove(); });
    S.msgs = {};
    S.current = null;
    S.typingEl = null;
    S.lastAssistant = null;
    showEmpty();
  }

  function nowTime() {
    const d = new Date();
    return String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0');
  }

  function addUser(text, attachments, skill) {
    hideEmpty();
    const wrap = document.createElement('div');
    wrap.className = 'msg user';
    const bubble = document.createElement('div');
    bubble.className = 'bubble';
    if (skill && skill.name) {
      const tag = document.createElement('div');
      tag.className = 'bubble-skill';
      tag.textContent = '✦ ' + T('技能') + ' · ' + skill.name;
      bubble.appendChild(tag);
    }
    if (attachments && attachments.length) {
      attachments.forEach(function (a) {
        if (a.type === 'image' && a.data_url) {
          const img = document.createElement('img');
          img.src = a.data_url;
          img.style.cursor = 'zoom-in';
          img.addEventListener('click', function () { openLightbox(a.data_url); });
          bubble.appendChild(img);
        } else if (a.type === 'file') {
          const badge = document.createElement('span');
          badge.className = 'bubble-file';
          badge.textContent = '📄 ' + a.name;
          bubble.appendChild(badge);
        }
      });
    }
    if (text) {
      const span = document.createElement('span');
      span.textContent = text;
      bubble.appendChild(span);
    }
    wrap.appendChild(bubble);
    threadEl().appendChild(wrap);
    scrollBottom(true);
    return wrap;
  }

  function ensureAssistant(id) {
    if (id && S.msgs[id]) { S.current = S.msgs[id]; return S.msgs[id]; }
    hideEmpty();
    const wrap = document.createElement('div');
    wrap.className = 'msg assistant';
    wrap.innerHTML =
      '<div class="msg-avatar"></div>' +
      '<div class="msg-main">' +
      '<details class="msg-reasoning" hidden><summary>思考过程</summary><div class="reasoning-text"></div></details>' +
      '<div class="md"></div>' +
      '<div class="msg-actions">' +
      '<button class="mini-btn copy-btn">复制</button>' +
      '<button class="mini-btn regen-btn">重新生成</button>' +
      '<button class="mini-btn quote-btn">引用</button>' +
      '<span class="msg-foot"><span class="tok"></span><span class="time"></span></span>' +
      '</div></div>';
    threadEl().appendChild(wrap);
    const avatarEl = wrap.querySelector('.msg-avatar');
    if (avatarEl) avatarEl.title = S.assistantName || 'Nexus';
    const item = {
      wrap: wrap,
      md: wrap.querySelector('.md'),
      reason: wrap.querySelector('.msg-reasoning'),
      reasonText: wrap.querySelector('.reasoning-text'),
      tok: wrap.querySelector('.tok'),
      raw: '',
      mdTimer: null,
      id: id || null,
    };
    wrap.querySelector('.time').textContent = nowTime();
    if (id) S.msgs[id] = item;
    S.current = item;
    S.lastAssistant = item;
    wrap.querySelector('.copy-btn').addEventListener('click', function () {
      copyText(item.raw || item.md.innerText || '');
    });
    wrap.querySelector('.regen-btn').addEventListener('click', function () { regenerate(item); });
    wrap.querySelector('.quote-btn').addEventListener('click', function () { quote(item.raw); });
    return item;
  }

  function scheduleMdRender(item) {
    if (!item || !item.md || item.mdTimer) return;
    // 流式渲染：按文本长度自适应节流，短文本跟手，长文本降低重排频率。
    const delay = item.raw.length > 16000 ? 140 : (item.raw.length > 6000 ? 90 : 55);
    item.mdTimer = setTimeout(function () {
      item.mdTimer = null;
      if (!item.md.isConnected) return;
      item.md.innerHTML = renderMarkdown(item.raw);
    }, delay);
  }

  function copyText(text) {
    if (!text) return;
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(function () { toast('已复制'); },
        function () { toast('复制失败'); });
    } else {
      const ta = document.createElement('textarea');
      ta.value = text; document.body.appendChild(ta); ta.select();
      try { document.execCommand('copy'); toast('已复制'); } catch (e) { toast('复制失败'); }
      ta.remove();
    }
  }

  function quote(text) {
    const body = String(text || '').trim();
    if (!body) return;
    const excerpt = body.length > 220 ? body.slice(0, 220) + '…' : body;
    const ta = $('#input');
    const prefix = ta.value.trim() ? ta.value.replace(/\s+$/, '') + '\n\n' : '';
    ta.value = prefix + excerpt.replace(/\n/g, '\n> ').replace(/^/, '> ') + '\n\n';
    autoGrow();
    ta.focus();
    ta.setSelectionRange(ta.value.length, ta.value.length);
    toast('已引用到输入框');
  }

  function regenerate(item) {
    if (S.streaming) { toast('正在回答中，先停止再试'); return; }
    if (!S.lastUserText) { toast('找不到上一条提问'); return; }
    if (item) { item.wrap.remove(); S.lastAssistant = null; }
    sendText(S.lastUserText, { skipUser: true });
  }

  function showTyping() {
    if (S.typingEl) return;
    hideEmpty();
    const wrap = document.createElement('div');
    wrap.className = 'msg assistant';
    wrap.innerHTML = '<div class="msg-avatar"></div><div class="msg-main"><div class="typing"><i></i><i></i><i></i></div></div>';
    threadEl().appendChild(wrap);
    S.typingEl = wrap;
    scrollBottom(true);
  }

  function removeTyping() {
    if (S.typingEl) { S.typingEl.remove(); S.typingEl = null; }
  }

  function nearBottom(box) {
    return box.scrollHeight - box.scrollTop - box.clientHeight <= BOTTOM_GAP;
  }

  // force=true 用于用户主动发消息、切换会话等场景；普通流式更新只在用户停留在底部时跟随
  function scrollBottom(force) {
    const box = $('#messages');
    if (!box) return;
    if (force) followBottom = true;
    else if (!followBottom) return;
    box.scrollTop = box.scrollHeight;
  }

  function scrollBottomSoon() {
    if (scrollQueued || !followBottom) return;
    scrollQueued = true;
    requestAnimationFrame(function () {
      scrollQueued = false;
      if (followBottom) scrollBottom();
    });
  }

  function toolLabel(name) {
    return T(TOOL_LABELS[name] || name || '工具');
  }

  function addToolStart(evt) {
    removeTyping();
    const item = ensureAssistant();
    S.runSteps += 1;
    const card = document.createElement('div');
    card.className = 'tool';
    card.dataset.id = evt.id || '';
    const argText = summarizeArgs(evt.args);
    card.innerHTML =
      '<div class="tool-head">' +
      '<span class="tool-dot running"></span>' +
      '<span class="tool-name">' + esc(toolLabel(evt.name)) + '</span>' +
      (argText ? '<span class="tool-arg" style="color:var(--text-3);font-size:11px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:110px;">' + esc(argText) + '</span>' : '') +
      '<span class="tool-ms"></span><span class="tool-chev">›</span></div>' +
      '<div class="tool-body"><pre class="tool-args">' + esc(JSON.stringify(evt.args || {}, null, 2)) + '</pre>' +
      '<div class="tool-summary"></div></div>';
    const head = card.querySelector('.tool-head');
    head.addEventListener('click', function () { card.classList.toggle('open'); });
    item.wrap.querySelector('.msg-main').appendChild(card);
    S.meta['tool_' + evt.id] = card;
    scrollBottom();
  }

  function addToolEnd(evt) {
    const card = S.meta['tool_' + evt.id];
    if (card) {
      const dot = card.querySelector('.tool-dot');
      dot.className = 'tool-dot ' + (evt.ok ? 'ok' : 'fail');
      card.querySelector('.tool-ms').textContent = (evt.ms || 0) + 'ms';
      card.querySelector('.tool-summary').textContent = evt.summary || '';
      if (!evt.ok) card.classList.add('open');
    }
    if (evt.ok && FILE_TOOLS[evt.name]) scheduleTreeRefresh();
    scrollBottom();
  }

  function summarizeArgs(args) {
    if (!args) return '';
    const keys = Object.keys(args);
    for (let i = 0; i < keys.length; i++) {
      const v = args[keys[i]];
      if (typeof v === 'string' && v) return v.length > 28 ? v.slice(0, 28) + '…' : v;
    }
    return '';
  }

  function addFiles(items) {
    if (!items || !items.length) return;
    const item = ensureAssistant();
    items.forEach(function (f) {
      const card = document.createElement('div');
      card.className = 'file-card';
      const ext = (f.name || f.path || '').split('.').pop().slice(0, 4);
      card.innerHTML =
        '<div class="file-icon">' + esc(ext) + '</div>' +
        '<div class="file-meta"><div class="file-name">' + esc(f.name || '文件') + '</div>' +
        '<div class="file-path">' + esc(f.path || '') + '</div></div>' +
        '<button class="open-file">打开</button><button class="show-file">位置</button>';
      card.querySelector('.open-file').addEventListener('click', function () {
        previewFile(f.path);
      });
      card.querySelector('.show-file').addEventListener('click', function () {
        call('reveal_path', f.path);
      });
      item.wrap.querySelector('.msg-main').appendChild(card);
    });
    scrollBottom();
  }

  function deltaTag(added, removed) {
    let html = '';
    if (added) html += '<i class="add">+' + added + '</i>';
    if (removed) html += '<i class="del">−' + removed + '</i>';
    return html || '<i class="none">无变化</i>';
  }

  // 一轮结束：总量单独一行，文件沿用原来的文件卡片外观，只取改动最大的 3 个
  function addChanges(evt) {
    const items = evt.items || [];
    if (!items.length) return;
    // 收尾事件晚于最终回答，直接放到对话流末尾，保证一眼能看到
    hideEmpty();
    const block = document.createElement('div');
    block.className = 'changes-block';
    const total = evt.total || items.length;
    const summary = document.createElement('div');
    summary.className = 'changes-total';
    summary.innerHTML =
      '<div class="changes-total-main">' + esc(TF('本轮改动 {n} 个文件', { n: total })) + '</div>' +
      '<div class="changes-total-sum">' + deltaTag(evt.added, evt.removed) + '</div>';
    block.appendChild(summary);
    items.forEach(function (f) {
      const card = document.createElement('div');
      card.className = 'file-card change-file';
      card.title = f.path || '';
      const ext = (f.name || f.path || '').split('.').pop().slice(0, 4);
      card.innerHTML =
        '<div class="file-icon">' + esc(ext) + '</div>' +
        '<div class="file-meta"><div class="file-name">' + esc(f.name || '文件') + '</div>' +
        '<div class="file-path">' + esc(f.path || '') + '</div></div>';
      card.addEventListener('click', function () { previewFile(f.path); });
      block.appendChild(card);
    });
    threadEl().appendChild(block);
    scrollBottom();
  }

  function renderTodo(items) {
    const panel = $('#todoPanel');
    if (!items || !items.length) { panel.hidden = true; return; }
    panel.hidden = false;
    panel.innerHTML = items.map(function (it) {
      const status = it.status || 'pending';
      return '<div class="todo-item ' + status + '"><span class="tick"></span><span class="todo-text">' +
        esc(it.text) + '</span></div>';
    }).join('');
  }

  function addError(evt) {
    removeTyping();
    const item = ensureAssistant();
    const note = document.createElement('div');
    note.className = 'error-note';
    note.textContent = T(evt.message || '出错了');
    if (evt.hint) {
      const span = document.createElement('span');
      span.textContent = T(evt.hint);
      note.appendChild(span);
    }
    if (evt.detail && S.settings.show_api_errors !== false) {
      const detail = document.createElement('details');
      detail.className = 'error-detail';
      const summary = document.createElement('summary');
      summary.textContent = evt.status ? 'HTTP ' + evt.status : 'API';
      const pre = document.createElement('pre');
      pre.textContent = String(evt.detail);
      detail.appendChild(summary);
      detail.appendChild(pre);
      note.appendChild(detail);
    }
    item.wrap.querySelector('.msg-main').appendChild(note);
    toast(evt.message || '出错了');
    scrollBottom();
  }

  /* ---------------- 事件入口 ---------------- */
  function onEvent(evt) {
    if (!evt || !evt.type) return;
    const scoped = ['assistant_delta', 'reasoning_delta', 'assistant_done', 'tool_start',
      'tool_end', 'todo', 'files', 'changes', 'error', 'run_end'];
    if (evt.session_id && scoped.indexOf(evt.type) >= 0 &&
        S.sessionId && String(evt.session_id) !== String(S.sessionId)) {
      return;
    }
    switch (evt.type) {
      case 'schedule_start':
        toast(TF('定时任务开始：{title}', { title: evt.title || '' }));
        switchView('chat');
        if (evt.session_id) openSession(evt.session_id);
        loadSideSessions();
        break;
      case 'schedule_done':
        toast(TF('定时任务完成：{title}', { title: evt.title || '' }));
        loadSideSessions();
        if (evt.session_id && String(evt.session_id) === String(S.sessionId)) {
          openSession(evt.session_id);
        }
        break;
      case 'state':
        setStatus(evt.status);
        break;
      case 'assistant_delta': {
        removeTyping();
        const item = ensureAssistant(evt.id);
        const piece = evt.text || '';
        item.raw += piece;
        if (piece) scheduleMdRender(item);
        scrollBottomSoon();
        break;
      }
      case 'reasoning_delta': {
        removeTyping();
        const item = ensureAssistant(evt.id);
        const piece = evt.text || '';
        if (item.reason) {
          item.reason.hidden = false;
          if (piece) item.reasonText.appendChild(document.createTextNode(piece));
        }
        scrollBottomSoon();
        break;
      }
      case 'assistant_done': {
        removeTyping();
        const item = ensureAssistant(evt.id);
        if (item.mdTimer) { clearTimeout(item.mdTimer); item.mdTimer = null; }
        item.raw = evt.text || item.raw;
        item.md.innerHTML = renderMarkdown(item.raw);
        if (item.tok) item.tok.textContent = '~' + estTokens(item.raw) + ' tok';
        S.current = item;
        S.lastAssistant = item;
        S.runRounds += 1;
        scrollBottom();
        break;
      }
      case 'tool_start':
        addToolStart(evt);
        break;
      case 'tool_end':
        addToolEnd(evt);
        break;
      case 'confirm_request':
        openConfirm(evt);
        break;
      case 'ask_request':
        openAsk(evt);
        break;
      case 'notify':
        toast((evt.title ? evt.title + '：' : '') + (evt.message || ''));
        break;
      case 'todo':
        renderTodo(evt.items);
        break;
      case 'voice_state':
        handleVoiceState(evt);
        break;
      case 'voice_partial':
        if (evt.target !== 'quick') handleVoicePartial(evt.text);
        break;
      case 'voice_level':
        applyVoiceLevel(evt.level, evt.bands);
        break;
      case 'voice_result':
        if (evt.target !== 'quick') insertVoiceText(evt.text || '');
        break;
      case 'quick_send':
        (function () {
          var text = evt.text || '';
          var incoming = evt.attachments || [];
          if (!text && !incoming.length) return;
          switchView('chat');
          var el = $('#input');
          if (el) { el.value = text; autoGrow(); }
          incoming.forEach(function (a) {
            var data = a.data || a.base64 || '';
            if (!data) return;
            S.attachments.push({
              type: 'image',
              base64: data.replace(/^data:[^,]*,/, ''),
              data_url: data.indexOf('data:') === 0
                ? data : ('data:image/png;base64,' + data),
            });
          });
          sendText(text);
        })();
        break;
      case 'files':
        addFiles(evt.items);
        if ((evt.items || []).length) {
          ensureRightPanel();
          if (S.rpMode === 'tree') loadTree();
        }
        break;
      case 'changes':
        addChanges(evt);
        break;
      case 'term_data':
      case 'term_exit':
        handleTermEvent(evt);
        break;
      case 'attach_image':
        if (evt.data_url || evt.base64) {
          S.attachments.push({
            type: 'image',
            base64: evt.base64 || '',
            data_url: evt.data_url || ('data:image/png;base64,' + evt.base64),
          });
          renderAttachments();
          toast('已添加截图，可以补充问题后发送');
          $('#input').focus();
        }
        break;
      case 'new_chat':
        newChat();
        break;
      case 'open_settings':
        switchView('settings');
        break;
      case 'error':
        addError(evt);
        break;
      case 'run_end':
        finishRun();
        break;
      case 'settings_changed':
        if (evt.settings) applyState({ settings: evt.settings, theme: evt.settings.theme, mode: evt.settings.mode, language: evt.language });
        break;
      case 'context':
        if (evt.session_id && S.sessionId && String(evt.session_id) !== String(S.sessionId)) break;
        if (evt.action === 'compressing') {
          S.compressing = true;
          updateStatusBar();
          setCompressStatus(T('正在压缩上下文…'), '');
          toast('正在压缩上下文…');
        } else if (evt.action === 'compressed') {
          S.compressing = false;
          if (evt.used !== undefined) {
            applyContextStats({ used: evt.used, limit: evt.limit, percent: evt.percent,
                                summarized: evt.summarized });
          } else {
            refreshContextStats();
          }
          if (evt.manual) {
            setCompressStatus(TF('已把 {n} 条消息压缩为摘要', { n: evt.summarized_count || 0 }), 'ok');
            toast('上下文已压缩，历史已统一为摘要');
          } else {
            toast('上下文已压缩，早期对话已生成摘要');
          }
        } else if (evt.action === 'compress_failed') {
          S.compressing = false;
          updateStatusBar();
          setCompressStatus(TF('压缩失败：{msg}', { msg: evt.message || '' }), 'fail');
          toast(TF('上下文压缩失败：{msg}', { msg: evt.message || '' }));
        } else if (evt.action === 'compress_skipped') {
          S.compressing = false;
          updateStatusBar();
          setCompressStatus(evt.message || T('当前会话还没有可压缩的内容'), '');
          toast(evt.message || '当前会话还没有可压缩的内容');
        } else if (evt.action === 'trimmed') {
          toast('上下文已达上限，较早消息已省略');
          refreshContextStats();
        } else if (evt.action === 'usage') {
          applyContextStats(evt);
        }
        break;
      case 'update_available':
        showUpdate(evt.info || {});
        break;
      case 'update_progress':
        updateUpdateProgress(evt);
        break;
      case 'update_failed':
        updateUpdateFailed(evt.message || '');
        break;
      case 'update_simulated':
        showUpdateSimulated(evt);
        break;
      case 'history_cleared':
        newChat();
        loadSideSessions();
        toast('已清空对话历史');
        break;
      case 'settings_reset':
        if (evt.state) applyState(evt.state);
        toast('已恢复默认设置');
        break;
      default:
        break;
    }
  }

  window.Nexus = {
    onEvent: onEvent,
    focusInput: function () {
      switchView('chat');
      setTimeout(function () { $('#input').focus(); }, 30);
    },
  };

  function setStatus(status) {
    S.status = status || 'idle';
    const dot = $('#modeAvatar .avatar-status');
    if (dot) dot.className = 'avatar-status ' + (S.status === 'idle' ? '' : S.status);
  }

  function finishRun() {
    S.streaming = false;
    S.runDuration = S.runStart ? (Date.now() - S.runStart) / 1000 : 0;
    removeTyping();
    setStatus('idle');
    $('#stopBtn').hidden = true;
    $('#sendBtn').disabled = false;
    S.rpManualClosed = false;
    loadSideSessions();
    updateStatusBar();
    refreshContextStats();
    scheduleTreeRefresh();
    if (S.view === 'settings') refreshPerfStats(true);
  }

  /* ---------------- 发送 ---------------- */
  async function sendText(text, opts) {
    opts = opts || {};
    if (S.streaming) return;
    text = (text || '').trim();
    if (!text && !S.attachments.length) return;
    const attachments = S.attachments.slice();
    const activeSkill = S.activeSkill ? { id: S.activeSkill.id, name: S.activeSkill.name } : null;
    if (!opts.skipUser) addUser(text, attachments, activeSkill);
    $('#input').value = '';
    autoGrow();
    closeTrigger();
    S.attachments = [];
    renderAttachments();
    S.lastUserText = text;
    S.streaming = true;
    S.runStart = Date.now();
    S.runRounds = 0;
    S.runSteps = 0;
    S.runDuration = 0;
    S.rpManualClosed = false;
    $('#sendBtn').disabled = true;
    $('#stopBtn').hidden = false;
    showTyping();
    updateStatusBar();
    if (S.sessionTitle === '新对话' && text) {
      S.sessionTitle = text.slice(0, 18);
      renderTitle();
    }
    const payload = {
      session_id: S.sessionId,
      text: text || '请看看附件',
      skill: activeSkill ? activeSkill.id : '',
      attachments: attachments.map(function (a) {
        if (a.type === 'file') return { type: 'file', name: a.name, text: a.text };
        return { type: 'image', data: a.base64 };
      }),
    };
    // 技能只作用于这一条消息，发送后立即清空输入框旁的技能 chip。
    if (activeSkill) setActiveSkill(null);
    const res = await call('send', payload);
    if (!res || !res.ok) {
      if (res && res.error) toast(res.error);
      finishRun();
      return;
    }
    S.sessionId = res.session_id;
    loadSideSessions();
  }

  /* ---------------- 截图 ---------------- */
  async function capture(mode) {
    const region = mode === 'region';
    toast(region ? '请拖动鼠标框选区域，Esc 取消…' : '正在截图…');
    const res = await call('capture_screen', region ? { mode: 'region' } : undefined);
    if (!res) return;
    if (!res.ok) {
      if (!res.cancelled) toast(res.error || '截图失败');
      return;
    }
    S.attachments.push({ type: 'image', base64: res.base64, data_url: res.data_url });
    renderAttachments();
    toast(region ? '已添加区域截图' : '已添加截图，可以补充问题后发送');
    $('#input').focus();
  }

  function renderAttachments() {
    const bar = $('#attachmentBar');
    bar.innerHTML = '';
    if (!S.attachments.length) { bar.hidden = true; return; }
    bar.hidden = false;
    S.attachments.forEach(function (a, idx) {
      const box = document.createElement('div');
      box.className = 'attachment' + (a.type === 'image' ? ' image' : '');
      if (a.type === 'image') {
        const img = document.createElement('img');
        img.src = a.data_url;
        img.addEventListener('click', function () { openLightbox(a.data_url); });
        box.appendChild(img);
      } else {
        const badge = document.createElement('span');
        badge.className = 'file-badge';
        badge.textContent = (a.name || '').split('.').pop().slice(0, 4);
        const name = document.createElement('span');
        name.className = 'att-name';
        name.textContent = a.name || '文件';
        box.appendChild(badge);
        box.appendChild(name);
      }
      const del = document.createElement('button');
      del.textContent = '×';
      del.title = '移除';
      del.addEventListener('click', function () {
        S.attachments.splice(idx, 1);
        renderAttachments();
      });
      box.appendChild(del);
      bar.appendChild(box);
    });
  }

  /* ---------------- 拖放文件 ---------------- */
  function showDrop(show) {
    const mask = $('#dropMask');
    if (mask) mask.hidden = !show;
  }

  function isTextFile(name) {
    const ext = String(name || '').split('.').pop().toLowerCase();
    return TEXT_EXT.indexOf(ext) >= 0;
  }

  function readAsText(file) {
    return new Promise(function (resolve) {
      const fr = new FileReader();
      fr.onload = function () { resolve(String(fr.result || '')); };
      fr.onerror = function () { resolve(''); };
      fr.readAsText(file);
    });
  }

  function readAsDataUrl(file) {
    return new Promise(function (resolve) {
      const fr = new FileReader();
      fr.onload = function () { resolve(String(fr.result || '')); };
      fr.onerror = function () { resolve(''); };
      fr.readAsDataURL(file);
    });
  }

  async function handleFiles(fileList) {
    const files = Array.prototype.slice.call(fileList || []);
    if (!files.length) return;
    for (let i = 0; i < files.length && i < 6; i++) {
      const file = files[i];
      const name = file.name || '文件';
      if ((file.type || '').indexOf('image/') === 0) {
        if (file.size > 8 * 1024 * 1024) { toast(name + ' 超过 8MB，已跳过'); continue; }
        const dataUrl = await readAsDataUrl(file);
        const comma = dataUrl.indexOf(',');
        S.attachments.push({
          type: 'image',
          base64: comma >= 0 ? dataUrl.slice(comma + 1) : dataUrl,
          data_url: dataUrl,
        });
      } else if (isTextFile(name) && file.size <= 512 * 1024) {
        const text = await readAsText(file);
        S.attachments.push({ type: 'file', name: name, text: text.slice(0, 32000) });
      } else {
        toast(name + '：暂不支持该类型，可用 /file 引用路径');
        continue;
      }
    }
    renderAttachments();
    if (S.attachments.length) toast('已添加 ' + S.attachments.length + ' 个附件');
    $('#input').focus();
  }

  /* ---------------- 模型菜单 ---------------- */
  function providerCatalog() {
    return (S.settings && S.settings.provider_catalog) || [];
  }

  function providerInfo(id) {
    const list = providerCatalog();
    for (let i = 0; i < list.length; i++) {
      if (list[i].id === id) return list[i];
    }
    return null;
  }

  function providerState(id) {
    const all = (S.settings && S.settings.providers) || {};
    return all[id] || { configured: false, models: [], base_url: '', name: id, kind: 'openai' };
  }

  function providerIconPath(id) {
    const info = providerInfo(id);
    return (info && info.icon) ? ('assets/' + info.icon) : '';
  }

  function applyProviderMark(el, id) {
    if (!el) return;
    const info = providerInfo(id);
    const path = providerIconPath(id);
    el.innerHTML = '';
    if (path) {
      el.classList.add('has-icon');
      el.style.background = 'transparent';
      const img = new Image();
      img.src = path;
      img.alt = '';
      img.decoding = 'async';
      img.draggable = false;
      el.appendChild(img);
      return;
    }
    el.classList.remove('has-icon');
    el.textContent = (info && info.mark) || 'AI';
    el.style.background = (info && info.color) || '#64748b';
  }

  function modelLabel(provider, model) {
    const info = providerInfo(provider);
    const list = (info && info.models) || [];
    for (let i = 0; i < list.length; i++) {
      if (list[i].id === model) return list[i].label || model;
    }
    if (MODEL_NAMES[model]) return MODEL_NAMES[model];
    return model;
  }

  function modelPillText() {
    const st = S.settings || {};
    const pid = st.active_provider || st.provider || 'deepseek';
    const model = st.active_model || st.model || '';
    const effort = st.reasoning_effort || 'high';
    const info = providerInfo(pid);
    const state = providerState(pid);
    const provider = pid === 'custom'
      ? (state.name || '自定义')
      : ((info && (info.short || info.name)) || pid);
    const name = modelLabel(pid, model);
    const text = (name && name.toLowerCase().indexOf(String(provider).toLowerCase()) === 0)
      ? name
      : provider + ' · ' + name;
    return text + ' · ' + T(EFFORT_NAMES[effort] || '高');
  }

  function renderModelMenu() {
    const text = $('#modelPillText');
    if (text) text.textContent = modelPillText();
    const st = S.settings || {};
    const activeProvider = st.active_provider || st.provider || 'deepseek';
    const pillIcon = $('#modelPillIcon');
    if (pillIcon) {
      const path = providerIconPath(activeProvider);
      if (path) {
        pillIcon.src = path;
        pillIcon.hidden = false;
      } else {
        pillIcon.hidden = true;
        pillIcon.removeAttribute('src');
      }
    }
    const menu = $('#modelMenu');
    if (!menu) return;
    const list = $('#modelMenuList');
    if (!list) return;
    const activeModel = st.active_model || st.model || '';
    const providers = st.providers || {};
    list.innerHTML = '';
    let configured = 0;
    providerCatalog().forEach(function (info) {
      const state = providers[info.id] || {};
      if (!state.configured) return;
      const models = (state.models && state.models.length ? state.models : (info.models || []).map(function (m) { return m.id; }));
      if (!models.length) return;
      configured += 1;
      const label = document.createElement('div');
      label.className = 'menu-label';
      const iconPath = providerIconPath(info.id);
      if (iconPath) {
        const icon = new Image();
        icon.src = iconPath;
        icon.alt = '';
        icon.decoding = 'async';
        icon.draggable = false;
        label.appendChild(icon);
      }
      const labelText = document.createElement('span');
      labelText.textContent = info.id === 'custom'
        ? (state.name || info.name)
        : info.name;
      label.appendChild(labelText);
      list.appendChild(label);
      models.forEach(function (model) {
        const row = document.createElement('button');
        row.className = 'menu-row';
        row.dataset.model = model;
        row.dataset.provider = info.id;
        row.dataset.selected = (info.id === activeProvider && model === activeModel) ? '1' : '0';
        const span = document.createElement('span');
        span.textContent = modelLabel(info.id, model);
        const check = document.createElement('b');
        check.className = 'menu-check';
        row.appendChild(span);
        row.appendChild(check);
        row.addEventListener('click', function () {
          setModelTarget(info.id, model);
        });
        list.appendChild(row);
      });
    });
    if (!configured) {
      const empty = document.createElement('button');
      empty.className = 'menu-row';
      empty.innerHTML = '<span>' + esc(T('还没有可用的模型，去配置')) + '</span><b class="menu-check"></b>';
      empty.addEventListener('click', function () {
        closeMenus();
        switchView('settings');
        showSettingsPage('groupModel');
      });
      list.appendChild(empty);
    }
    const effort = st.reasoning_effort || 'high';
    Array.prototype.slice.call(menu.querySelectorAll('[data-effort]')).forEach(function (row) {
      row.dataset.selected = row.dataset.effort === effort ? '1' : '0';
    });
  }

  function syncModelMenu() {
    renderModelMenu();
  }

  function openModelMenu() {
    closeMenus();
    togglePop('#modelMenu');
    renderModelMenu();
  }

  function togglePop(sel) {
    const el = $(sel);
    if (!el) return;
    const willOpen = el.hidden;
    closeMenus();
    el.hidden = !willOpen;
  }

  function closeMenus() {
    ['#modelMenu', '#plusMenu'].forEach(function (sel) {
      const el = $(sel);
      if (el) el.hidden = true;
    });
  }

  async function setModelTarget(provider, model) {
    const res = await call('model_select', { provider: provider, model: model });
    if (res && res.ok) {
      const info = providerInfo(provider);
      S.settings.active_provider = provider;
      S.settings.provider = provider;
      S.settings.active_model = model;
      S.settings.model = model;
      if (res.settings) S.settings = res.settings;
      syncModelMenu();
      toast(TF('已切换到 {provider} · {name}', {
        provider: (info && info.name) || provider,
        name: modelLabel(provider, model),
      }));
    } else {
      toast((res && res.error) || T('切换模型失败'));
    }
    closeMenus();
  }

  async function setEffort(effort) {
    const res = await call('settings_save', { reasoning_effort: effort });
    if (res && res.ok) {
      S.settings.reasoning_effort = effort;
      syncModelMenu();
      toast(TF('推理强度：{name}', { name: T(EFFORT_NAMES[effort] || effort) }));
    } else {
      toast((res && res.error) || T('切换失败'));
    }
    closeMenus();
  }

  /* ---------------- 命令与引用菜单 ---------------- */
  function triggerContext() {
    const ta = $('#input');
    const pos = ta.selectionStart || 0;
    const before = ta.value.slice(0, pos);
    const m = before.match(/(^|[\s\n])([/@])([^\s/@]*)$/);
    if (!m) return null;
    return {
      trigger: m[2],
      query: m[3] || '',
      start: pos - (m[3] || '').length - 1,
      end: pos,
    };
  }

  function openTrigger(ctx) {
    S.trigger = ctx;
    if (ctx.trigger === '/') {
      const q = ctx.query.toLowerCase();
      const skills = (S.skills || []).filter(function (s) {
        if (!s.enabled) return false;
        if (!q) return true;
        return (String(s.id) + ' ' + String(s.name) + ' ' + String(s.description) + ' ' +
          String(s.when_to_use)).toLowerCase().indexOf(q) >= 0;
      }).map(function (s) {
        return {
          kind: 'skill', skill: s, label: s.name,
          desc: s.description || s.when_to_use || '', icon: '✦',
        };
      });
      const commands = COMMANDS.filter(function (c) {
        return !q || c.cmd.indexOf(q) === 0 || c.label.toLowerCase().indexOf(q) >= 0;
      }).map(function (c) {
        return { kind: 'cmd', cmd: c, label: T(c.label), desc: T(c.desc), icon: c.icon };
      });
      S.triggerItems = skills.concat(commands);
      S.triggerIndex = 0;
      renderTrigger();
    } else {
      openReferenceMenu(ctx);
    }
  }

  async function openReferenceMenu(ctx) {
    const menu = $('#triggerMenu');
    menu.hidden = false;
    menu.innerHTML = '<div class="menu-title">正在读取文件…</div>';
    if (!S.fileCache) {
      const res = await call('list_files');
      S.fileCache = (res && res.ok) ? (res.items || []) : [];
    }
    const q = String(ctx.query || '').toLowerCase();
    const files = S.fileCache.filter(function (f) {
      const name = String(f.name || '').toLowerCase();
      const path = String(f.path || '').toLowerCase();
      return !q || name.indexOf(q) >= 0 || path.indexOf(q) >= 0;
    }).slice(0, 30);
    S.triggerItems = files.map(function (f) {
      return { kind: 'file', path: f.path, label: f.name || f.path, desc: f.path, icon: '·' };
    }).concat([{ kind: 'pick', label: '选择本地文件…', desc: '用系统对话框选择', icon: '+' }]);
    S.triggerIndex = 0;
    renderTrigger();
  }

  function renderTrigger() {
    const menu = $('#triggerMenu');
    if (!S.triggerItems.length) {
      menu.hidden = false;
      menu.innerHTML = '<div class="menu-title">没有匹配项</div>';
      return;
    }
    if (S.triggerIndex >= S.triggerItems.length) S.triggerIndex = 0;
    menu.hidden = false;
    menu.innerHTML = S.triggerItems.map(function (item, idx) {
      const desc = item.kind === 'file' ? shortenPath(item.desc) : (item.desc || '');
      return '<button class="menu-row' + (idx === S.triggerIndex ? ' active' : '') + '" data-idx="' + idx + '">' +
        '<span class="trig-icon">' + esc(item.icon || '·') + '</span>' +
        '<span>' + esc(item.label) + '</span>' +
        '<span class="menu-desc">' + esc(desc) + '</span></button>';
    }).join('');
    Array.prototype.slice.call(menu.querySelectorAll('.menu-row')).forEach(function (row) {
      row.addEventListener('mousedown', function (e) {
        e.preventDefault();
        applyTrigger(parseInt(row.dataset.idx, 10));
      });
    });
  }

  function shortenPath(path) {
    const s = String(path || '');
    const parts = s.split(/[\\/]/).filter(function (p) { return p; });
    if (parts.length > 1) return '…\\' + parts.slice(-2).join('\\');
    if (s.length <= 42) return s;
    return '…' + s.slice(-40);
  }

  function closeTrigger() {
    const menu = $('#triggerMenu');
    if (menu) menu.hidden = true;
    S.trigger = null;
    S.triggerItems = [];
    S.triggerIndex = 0;
  }

  function removeTriggerText(ctx) {
    const ta = $('#input');
    const value = ta.value;
    ta.value = value.slice(0, ctx.start) + value.slice(ctx.end);
    const pos = ctx.start;
    ta.setSelectionRange(pos, pos);
    autoGrow();
  }

  async function applyTrigger(idx) {
    const item = S.triggerItems[idx];
    const ctx = S.trigger;
    if (!item || !ctx) return;
    if (item.kind === 'cmd') {
      removeTriggerText(ctx);
      closeTrigger();
      item.cmd.run();
      return;
    }
    if (item.kind === 'skill') {
      removeTriggerText(ctx);
      closeTrigger();
      setActiveSkill(item.skill);
      toast(TF('已选择技能：{name}', { name: item.skill.name }));
      $('#input').focus();
      return;
    }
    if (item.kind === 'file') {
      removeTriggerText(ctx);
      const token = /\s/.test(item.path) ? '@"' + item.path + '"' : '@' + item.path;
      const ta = $('#input');
      const pos = ta.selectionStart || 0;
      ta.value = ta.value.slice(0, pos) + token + ' ' + ta.value.slice(pos);
      const next = pos + token.length + 1;
      ta.setSelectionRange(next, next);
      autoGrow();
      closeTrigger();
      ta.focus();
      return;
    }
    if (item.kind === 'pick') {
      removeTriggerText(ctx);
      closeTrigger();
      await pickFileReference();
    }
  }

  async function pickFileReference() {
    const res = await call('pick_files');
    if (!res || !res.ok) {
      if (res && res.error) toast(res.error);
      return;
    }
    const paths = res.paths || [];
    if (!paths.length) return;
    const ta = $('#input');
    const tokens = paths.map(function (p) {
      return /\s/.test(p) ? '@"' + p + '"' : '@' + p;
    }).join(' ');
    const pos = ta.selectionStart || ta.value.length;
    ta.value = ta.value.slice(0, pos) + tokens + ' ' + ta.value.slice(pos);
    const next = pos + tokens.length + 1;
    ta.setSelectionRange(next, next);
    autoGrow();
    ta.focus();
    toast('已引用 ' + paths.length + ' 个文件');
  }

  /* ---------------- 确认弹窗 ---------------- */
  function openConfirm(evt) {
    S.confirmId = evt.id;
    $('#confirmTitle').textContent = evt.title || '需要你确认';
    $('#confirmDetail').textContent = evt.detail || '';
    const cmd = $('#confirmCmd');
    if (evt.command) { cmd.hidden = false; cmd.textContent = evt.command; }
    else { cmd.hidden = true; cmd.textContent = ''; }
    $('#confirmMask').hidden = false;
  }

  function closeConfirm(allow) {
    const id = S.confirmId;
    S.confirmId = null;
    $('#confirmMask').hidden = true;
    if (id) call('confirm_reply', { id: id, allow: allow });
  }

  /* ---------------- 对话区内联提问 ---------------- */
  function openAsk(evt) {
    hideEmpty();
    const wrap = document.createElement('div');
    wrap.className = 'msg assistant';
    wrap.dataset.askId = evt.id;
    const bubble = document.createElement('div');
    bubble.className = 'bubble ask-inline';
    const q = document.createElement('div');
    q.className = 'ask-inline-q';
    q.textContent = evt.question || '需要你的回答';
    bubble.appendChild(q);
    const opts = document.createElement('div');
    opts.className = 'ask-options';
    (evt.options || []).forEach(function (text) {
      const btn = document.createElement('button');
      btn.className = 'ask-option';
      btn.textContent = text;
      btn.addEventListener('click', function () { replyAsk(wrap, evt.id, text); });
      opts.appendChild(btn);
    });
    bubble.appendChild(opts);
    if (evt.allow_text !== false) {
      const row = document.createElement('div');
      row.className = 'ask-input-row';
      const input = document.createElement('input');
      input.className = 'ask-input';
      input.placeholder = '也可以直接输入回答…';
      const submit = document.createElement('button');
      submit.className = 'ask-send';
      submit.title = '发送回答';
      submit.setAttribute('aria-label', '发送回答');
      submit.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h13M12.5 6.5L19 12l-6.5 5.5"/></svg>';
      function sendTextAnswer() {
        const val = input.value.trim();
        if (!val) return;
        replyAsk(wrap, evt.id, val);
      }
      submit.addEventListener('click', sendTextAnswer);
      input.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' && !e.isComposing) {
          e.preventDefault();
          sendTextAnswer();
        }
      });
      row.appendChild(input);
      row.appendChild(submit);
      bubble.appendChild(row);
      setTimeout(function () { input.focus(); }, 40);
    }
    const skip = document.createElement('button');
    skip.className = 'ask-skip';
    skip.textContent = '跳过';
    skip.addEventListener('click', function () { replyAsk(wrap, evt.id, null); });
    bubble.appendChild(skip);
    wrap.appendChild(bubble);
    const thread = $('#thread') || $('#messages');
    thread.appendChild(wrap);
    scrollBottom();
  }

  function replyAsk(wrap, id, answer) {
    if (wrap.dataset.answered) return;
    wrap.dataset.answered = '1';
    wrap.querySelectorAll('button, input').forEach(function (el) { el.disabled = true; });
    const tip = document.createElement('div');
    tip.className = 'ask-answered';
    tip.textContent = answer === null ? '已跳过' : '已回答：' + String(answer);
    wrap.querySelector('.bubble').appendChild(tip);
    if (answer === null) call('ask_reply', { id: id, cancelled: true });
    else call('ask_reply', { id: id, answer: String(answer) });
    scrollBottom();
  }

  /* ---------------- 右侧文件面板 ---------------- */
  function ensureRightPanel() {
    if (S.rpManualClosed) return;
    if ($('#rightPanel').hidden) openRightPanel();
  }

  async function openRightPanel() {
    if (window.innerWidth < 900) return;
    const panel = $('#rightPanel');
    if (!panel) return;
    // 小窗里优先保证对话区宽度：打开右栏时临时收起左栏
    if (window.innerWidth <= 1100) setSidebar(true, true);
    panel.hidden = false;
    requestAnimationFrame(function () { panel.classList.add('open'); });
    S.rightOpen = true;
    $('#rpToggle').classList.add('active');
    startTreePoller();
    if (!S.tree || S.rpMode === 'tree') await loadTree();
    const active = activeInner(rpTabById(S.rpActive));
    if (active && active.kind === 'browser' && active.viewId) {
      setTimeout(function () {
        syncBrowserRect(active);
        syncEmbeds();
      }, 260);
    }
  }

  function closeRightPanel() {
    if (S.previewData) {
      if (S.editMode && S.mdDirty) savePreview(S.mdDraft);
      else if (S.docxDirty || S.xlsxDirty || S.pptDirty) saveOfficeEdits();
    }
    const panel = $('#rightPanel');
    if (panel) {
      panel.classList.remove('open');
      setTimeout(function () {
        if (!panel.classList.contains('open')) panel.hidden = true;
      }, 230);
    }
    S.rightOpen = false;
    syncEmbeds();
    const toggle = $('#rpToggle');
    if (toggle) toggle.classList.remove('active');
    if (S.streaming) S.rpManualClosed = true;
  }

  /* ---------------- 右侧面板宽度调整 ---------------- */
  const RP_W_KEY = 'nexus.rpWidth';
  const RP_MIN_W = 320;
  const CHAT_MIN_W = 420;

  function rpWidthLimits() {
    const vw = window.innerWidth;
    if (vw <= 960) return { min: RP_MIN_W, max: Math.max(RP_MIN_W, vw - 240) };
    const side = $('#sidebar');
    const sideW = side ? Math.round(side.getBoundingClientRect().width) : 280;
    return { min: RP_MIN_W, max: Math.max(RP_MIN_W, vw - sideW - CHAT_MIN_W) };
  }

  let rpSyncTimer = null;
  function schedulePanelSync() {
    clearTimeout(rpSyncTimer);
    rpSyncTimer = setTimeout(function () {
      const inner = activeInner(rpTabById(S.rpActive));
      if (inner && inner.kind === 'browser' && inner.viewId && S.rightOpen) syncBrowserRect(inner);
    }, 90);
  }

  function applyRpWidth(px, persist) {
    const panel = $('#rightPanel');
    if (!panel || !px) return;
    const lim = rpWidthLimits();
    const width = Math.round(Math.max(lim.min, Math.min(lim.max, px)));
    panel.style.width = width + 'px';
    if (persist) {
      const actual = Math.round(panel.getBoundingClientRect().width) || width;
      S.rpWidth = actual;
      try { localStorage.setItem(RP_W_KEY, String(actual)); } catch (e) { /* ignore */ }
    }
    schedulePanelSync();
  }

  function resetRpWidth() {
    const panel = $('#rightPanel');
    if (panel) panel.style.width = '';
    S.rpWidth = 0;
    try { localStorage.removeItem(RP_W_KEY); } catch (e) { /* ignore */ }
    schedulePanelSync();
  }

  function initRpResizer() {
    const bar = $('#rpResizer');
    const panel = $('#rightPanel');
    if (!bar || !panel) return;
    let dragging = false;
    let startX = 0;
    let startW = 0;
    bar.addEventListener('pointerdown', function (e) {
      if (e.button) return;
      dragging = true;
      startX = e.clientX;
      startW = panel.getBoundingClientRect().width;
      bar.classList.add('dragging');
      document.body.classList.add('rp-resizing');
      try { bar.setPointerCapture(e.pointerId); } catch (err) { /* ignore */ }
      e.preventDefault();
    });
    bar.addEventListener('pointermove', function (e) {
      if (!dragging) return;
      applyRpWidth(startW + (startX - e.clientX), false);
    });
    function endDrag(e) {
      if (!dragging) return;
      dragging = false;
      bar.classList.remove('dragging');
      document.body.classList.remove('rp-resizing');
      try { bar.releasePointerCapture(e.pointerId); } catch (err) { /* ignore */ }
      applyRpWidth(Math.round(panel.getBoundingClientRect().width), true);
    }
    bar.addEventListener('pointerup', endDrag);
    bar.addEventListener('pointercancel', endDrag);
    bar.addEventListener('dblclick', resetRpWidth);
    bar.addEventListener('keydown', function (e) {
      if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
      const step = e.key === 'ArrowLeft' ? 24 : -24;
      applyRpWidth(panel.getBoundingClientRect().width + step, true);
      e.preventDefault();
    });
  }

  /* ---------------- 右侧栏标签页 ---------------- */
  const RP_TAB_META = {
    editor: {
      name: '编辑器',
      ico: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"><path d="M5.4 4.4 2.4 8l3 3.6M10.6 4.4 13.6 8l-3 3.6"/></svg>',
    },
    browser: {
      name: '浏览器',
      ico: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"><circle cx="8" cy="8" r="5.6"/><path d="M2.4 8h11.2M8 2.4c1.5 1.6 2.2 3.4 2.2 5.6S9.5 12 8 13.6c-1.5-1.6-2.2-3.4-2.2-5.6S6.5 4 8 2.4Z"/></svg>',
    },
    terminal: {
      name: '终端',
      ico: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"><rect x="2.2" y="3.2" width="11.6" height="9.6" rx="2"/><path d="m5.2 6.6 1.8 1.5-1.8 1.5M8.8 9.8h2.4"/></svg>',
    },
  };

  function rpTabById(id) {
    for (let i = 0; i < S.rpTabs.length; i++) {
      if (S.rpTabs[i].id === id) return S.rpTabs[i];
    }
    return null;
  }

  function initRpTabs() {
    if (!S.rpTabs.length) {
      S.rpTabs.push({
        id: 'editor', kind: 'editor', title: '编辑器',
        closable: false, view: $('#rpViewEditor'),
      });
      S.rpActive = 'editor';
    }
    renderRpTabs();
  }

  function renderRpTabs() {
    const box = $('#rpTabs');
    if (!box) return;
    box.innerHTML = '';
    S.rpTabs.forEach(function (tab) {
      const meta = RP_TAB_META[tab.kind] || RP_TAB_META.editor;
      const el = document.createElement('div');
      el.className = 'rp-tab' + (S.rpActive === tab.id ? ' active' : '');
      el.title = tab.title;
      el.innerHTML =
        '<span class="rp-tab-ico">' + meta.ico + '</span>' +
        '<span class="rp-tab-name">' + esc(tab.title) + '</span>' +
        (tab.closable ? '<span class="rp-tab-close" title="关闭标签">×</span>' : '');
      el.addEventListener('click', function (e) {
        if (e.target.classList.contains('rp-tab-close')) {
          e.stopPropagation();
          closeRpTab(tab.id);
          return;
        }
        activateRpTab(tab.id);
      });
      box.appendChild(el);
    });
  }

  function activateRpTab(id) {
    const tab = rpTabById(id);
    if (!tab) return;
    S.rpActive = id;
    S.rpTabs.forEach(function (item) {
      if (item.view) item.view.classList.toggle('active', item.id === id);
    });
    renderRpTabs();
    const inner = activeInner(tab);
    if (inner && inner.kind === 'browser' && inner.viewId) {
      syncBrowserRect(inner);
      requestAnimationFrame(function () { syncBrowserRect(inner); });
    }
    if (inner && inner.kind === 'terminal') {
      requestAnimationFrame(function () { fitTerminal(inner); });
    }
    syncEmbeds();
  }

  function mountRpTab(tab, view) {
    view.classList.add('rp-view');
    tab.view = view;
    $('#rpViews').appendChild(view);
    S.rpTabs.push(tab);
    activateRpTab(tab.id);
  }

  function closeRpTab(id) {
    const idx = S.rpTabs.findIndex(function (t) { return t.id === id; });
    if (idx < 0) return;
    const tab = S.rpTabs[idx];
    if (!tab.closable) return;
    if (tab.inner) tab.inner.slice().forEach(releaseInner);
    if (tab.view) tab.view.remove();
    S.rpTabs.splice(idx, 1);
    if (S.rpActive === id) {
      const next = S.rpTabs[Math.min(idx, S.rpTabs.length - 1)];
      if (next) activateRpTab(next.id);
      else { S.rpActive = ''; renderRpTabs(); }
    } else {
      renderRpTabs();
    }
    syncEmbeds();
  }

  function toggleRpMenu(show) {
    const menu = $('#rpTabMenu');
    if (menu) menu.hidden = !show;
    refreshEmbedSuppress();
  }

  function prettyHost(url) {
    try {
      const u = new URL(url);
      return u.host || url;
    } catch (e) {
      return url;
    }
  }

  // 把面板里的占位区域换算成物理像素，供原生子窗口定位
  function rpHostRect(el) {
    const r = el.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    return {
      x: Math.round(r.left * dpr),
      y: Math.round(r.top * dpr),
      w: Math.max(120, Math.round(r.width * dpr)),
      h: Math.max(80, Math.round(r.height * dpr)),
    };
  }

  function showEmbed(tab, visible) {
    if (tab && tab.kind === 'browser' && tab.viewId) {
      call('browser_embed_show', { id: tab.viewId, show: !!visible });
    }
  }

  function eachBrowserTab(fn) {
    S.rpTabs.forEach(function (ws) {
      if (ws.kind !== 'browser' || !ws.inner) return;
      ws.inner.forEach(function (inner) {
        if (inner.kind === 'browser') fn(inner, ws);
      });
    });
  }

  function activeInner(ws) {
    if (!ws || !ws.inner) return null;
    for (let i = 0; i < ws.inner.length; i++) {
      if (ws.inner[i].id === ws.innerActive) return ws.inner[i];
    }
    return null;
  }

  function rpTabByKind(kind) {
    for (let i = 0; i < S.rpTabs.length; i++) {
      if (S.rpTabs[i].kind === kind) return S.rpTabs[i];
    }
    return null;
  }

  // 原生子窗口永远浮在网页之上：只有「面板打开 + 当前工作区是浏览器 + 当前内标签」才显示
  function syncEmbeds() {
    const ws = rpTabById(S.rpActive);
    eachBrowserTab(function (inner, owner) {
      const visible = !S.embedSuppress && S.rightOpen && !!ws &&
        owner.id === ws.id && inner.id === ws.innerActive;
      showEmbed(inner, visible);
    });
  }

  function anyMenuOpen() {
    if ($('#rpTabMenu') && !$('#rpTabMenu').hidden) return true;
    return S.rpTabs.some(function (ws) {
      return ws.shellMenu && !ws.shellMenu.hidden;
    });
  }

  function refreshEmbedSuppress() {
    S.embedSuppress = anyMenuOpen();
    syncEmbeds();
  }

  function syncBrowserRect(tab) {
    if (!tab || !tab.viewId || !tab.host) return;
    if (!tab.host.offsetParent) return; // 所在面板不可见时不要用 0 尺寸去挪窗口
    const rect = rpHostRect(tab.host);
    call('browser_embed_rect', { id: tab.viewId, x: rect.x, y: rect.y, w: rect.w, h: rect.h });
  }

  /* ---------------- 浏览器工作区（自带标签页） ---------------- */
  const RP_PLUS_SVG = '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><path d="M8 3.4v9.2M3.4 8h9.2"/></svg>';
  const BROWSER_ICO_SMALL = '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"><circle cx="8" cy="8" r="5.4"/><path d="M2.6 8h10.8M8 2.6c1.4 1.5 2.1 3.3 2.1 5.4S9.4 11.9 8 13.4c-1.4-1.5-2.1-3.3-2.1-5.4S6.6 4.1 8 2.6Z"/></svg>';
  const NAV_BACK_SVG = '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M9.8 3.6 5.4 8l4.4 4.4"/></svg>';
  const NAV_FWD_SVG = '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M6.2 3.6 10.6 8l-4.4 4.4"/></svg>';
  const NAV_RELOAD_SVG = '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"><path d="M12.9 8A4.9 4.9 0 1 1 11.4 4.5M12.9 2.6v3h-3"/></svg>';
  const BROWSER_ART_SVG =
    '<svg class="rp-browser-art" viewBox="0 0 64 64" fill="none" aria-hidden="true">' +
      '<circle cx="31" cy="33" r="17" stroke="currentColor" stroke-width="1.4" opacity=".62"/>' +
      '<ellipse cx="31" cy="33" rx="7.5" ry="17" stroke="currentColor" stroke-width="1.2" opacity=".42"/>' +
      '<path d="M14 33h34M17.5 23.5h27M17.5 42.5h27" stroke="currentColor" stroke-width="1.1" opacity=".34" stroke-linecap="round"/>' +
      '<circle cx="47" cy="20" r="3.4" fill="var(--accent)"/>' +
    '</svg>';

  function mountBrowserWorkspace() {
    const ws = { id: 'browser', kind: 'browser', title: '浏览器', closable: true,
                 inner: [], innerActive: '' };
    const view = document.createElement('section');
    view.dataset.kind = 'browser';
    view.className = 'rp-work';
    view.innerHTML =
      '<div class="rp-subbar">' +
        '<div class="rp-subtabs"></div>' +
        '<button class="rp-subadd" title="新建标签页">' + RP_PLUS_SVG + '</button>' +
      '</div>' +
      '<div class="rp-panes"></div>';
    ws.subtabs = view.querySelector('.rp-subtabs');
    ws.panes = view.querySelector('.rp-panes');
    view.querySelector('.rp-subadd').addEventListener('click', function () { addBrowserTab(ws); });
    mountRpTab(ws, view);
    addBrowserTab(ws);
    return ws;
  }

  function addBrowserTab(ws) {
    const tab = { id: 'b' + (S.rpSeq += 1), kind: 'browser', title: '新标签页',
                  url: '', viewId: '', host: null, ro: null, timer: null };
    const pane = document.createElement('div');
    pane.className = 'rp-pane rp-browser';
    pane.innerHTML =
      '<div class="rp-browser-bar">' +
        '<button class="rp-nav" data-act="back" title="后退">' + NAV_BACK_SVG + '</button>' +
        '<button class="rp-nav" data-act="forward" title="前进">' + NAV_FWD_SVG + '</button>' +
        '<button class="rp-nav" data-act="reload" title="刷新">' + NAV_RELOAD_SVG + '</button>' +
        '<input class="rp-browser-url" type="text" spellcheck="false" ' +
          'placeholder="输入网址、localhost 或本地 HTML 路径">' +
        '<button class="rp-browser-go">打开</button>' +
      '</div>' +
      '<div class="rp-browser-stage">' +
        '<div class="rp-browser-host"></div>' +
        '<div class="rp-browser-empty">' +
          BROWSER_ART_SVG +
          '<div class="rp-browser-hint">在上面输入地址，回车即在面板内打开</div>' +
          '<div class="rp-browser-sub">内嵌真实浏览器，不受站点禁止嵌入的限制</div>' +
          '<div class="rp-browser-chips"><span>https://…</span><span>localhost:5173</span><span>本地 HTML</span></div>' +
        '</div>' +
      '</div>';
    tab.pane = pane;
    tab.host = pane.querySelector('.rp-browser-host');
    tab.empty = pane.querySelector('.rp-browser-empty');
    tab.input = pane.querySelector('.rp-browser-url');
    ws.panes.appendChild(pane);
    ws.inner.push(tab);
    bindBrowserPane(ws, tab, pane);
    activateInner(ws, tab.id);
    tab.input.focus();
    return tab;
  }

  function bindBrowserPane(ws, tab, pane) {
    const input = tab.input;
    const host = tab.host;
    const empty = tab.empty;

    function startInfoPoll(t) {
      clearInterval(t.timer);
      t.timer = setInterval(function () {
        if (S.rpActive !== ws.id || ws.innerActive !== t.id || !t.viewId || !S.rightOpen) return;
        call('browser_embed_info', { id: t.viewId }).then(function (info) {
          if (!info || !info.ok) return;
          if (info.url && document.activeElement !== input) input.value = info.url;
          if (info.title && info.title !== t.title) {
            t.title = String(info.title).slice(0, 24);
            renderSubTabs(ws);
          }
        });
      }, 2000);
    }

    async function openTarget(raw) {
      const text = String(raw || '').trim();
      if (!text) { input.focus(); return; }
      if (!tab.viewId) {
        if ($('#rightPanel').hidden) return;
        await new Promise(function (r) { setTimeout(r, 260); }); // 等面板展开动画结束
        const rect = rpHostRect(host);
        const res = await call('browser_embed_open',
          { url: text, x: rect.x, y: rect.y, w: rect.w, h: rect.h });
        if (!res || !res.ok) {
          toast(res && res.error ? res.error : '打开失败');
          return;
        }
        tab.viewId = res.id;
        empty.hidden = true;
        if (window.ResizeObserver) {
          tab.ro = new ResizeObserver(function () {
            if (S.rpActive === ws.id && ws.innerActive === tab.id) syncBrowserRect(tab);
          });
          tab.ro.observe(host);
        }
        startInfoPoll(tab);
      } else {
        const res = await call('browser_embed_navigate', { id: tab.viewId, url: text });
        if (!res || !res.ok) {
          toast(res && res.error ? res.error : '打开失败');
          return;
        }
        empty.hidden = true;
      }
      tab.url = text;
      tab.title = prettyHost(text);
      renderSubTabs(ws);
      syncEmbeds();
      if (S.rpActive === ws.id && ws.innerActive === tab.id) syncBrowserRect(tab);
    }

    tab.open = openTarget;
    pane.querySelector('.rp-browser-go').addEventListener('click', function () {
      openTarget(input.value);
    });
    input.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') { e.preventDefault(); openTarget(this.value); }
    });
    pane.querySelectorAll('.rp-nav').forEach(function (btn) {
      btn.addEventListener('click', function () {
        if (!tab.viewId) return;
        call('browser_embed_act', { id: tab.viewId, action: btn.dataset.act });
        setTimeout(function () { startInfoPoll(tab); }, 1200);
      });
    });
  }

  /* ---------------- 终端工作区（自带标签页 + 类型选择） ---------------- */
  const SHELL_FALLBACK = {
    powershell: { id: 'powershell', label: 'PowerShell', hint: '5.1', badge: 'PS' },
    pwsh: { id: 'pwsh', label: 'PowerShell 7', hint: 'pwsh', badge: 'PS7' },
    cmd: { id: 'cmd', label: '命令提示符', hint: 'cmd.exe', badge: 'CMD' },
    gitbash: { id: 'gitbash', label: 'Git Bash', hint: 'Git for Windows', badge: 'GIT' },
    wsl: { id: 'wsl', label: 'WSL', hint: 'Linux', badge: 'WSL' },
  };

  function shellFor(id) {
    const list = S.shells || [];
    for (let i = 0; i < list.length; i++) {
      if (list[i].id === id) return list[i];
    }
    return SHELL_FALLBACK[id] || null;
  }

  function loadShells() {
    if (S.shells) return Promise.resolve(S.shells);
    if (S.shellsPromise) return S.shellsPromise;
    S.shellsPromise = Promise.resolve(call('terminal_shells')).then(function (res) {
      const items = (res && res.ok && res.items) || [];
      S.shells = items.length ? items : [
        { id: 'powershell', label: 'PowerShell', hint: '5.1', badge: 'PS' },
        { id: 'cmd', label: '命令提示符', hint: 'cmd.exe', badge: 'CMD' },
      ];
      return S.shells;
    }).catch(function () {
      S.shells = [SHELL_FALLBACK.powershell, SHELL_FALLBACK.cmd];
      return S.shells;
    });
    return S.shellsPromise;
  }

  function mountTerminalWorkspace() {
    const ws = { id: 'terminal', kind: 'terminal', title: '终端', closable: true,
                 inner: [], innerActive: '' };
    const view = document.createElement('section');
    view.dataset.kind = 'terminal';
    view.className = 'rp-work';
    view.innerHTML =
      '<div class="rp-subbar">' +
        '<div class="rp-subtabs"></div>' +
        '<button class="rp-subadd" title="新建终端">' + RP_PLUS_SVG + '</button>' +
        '<div class="rp-shell-menu" hidden></div>' +
      '</div>' +
      '<div class="rp-panes"></div>';
    ws.subtabs = view.querySelector('.rp-subtabs');
    ws.panes = view.querySelector('.rp-panes');
    ws.addBtn = view.querySelector('.rp-subadd');
    ws.shellMenu = view.querySelector('.rp-shell-menu');
    ws.addBtn.addEventListener('click', function (e) {
      e.stopPropagation();
      toggleShellMenu(ws);
    });
    mountRpTab(ws, view);
    // 先按 PowerShell 立刻开一个会话，类型列表在后台探测（WSL 检测可能慢）
    addTerminalTab(ws, 'powershell');
    loadShells();
    return ws;
  }

  function renderShellMenu(ws) {
    ws.shellMenu.innerHTML = '';
    (S.shells || []).forEach(function (info) {
      const btn = document.createElement('button');
      btn.className = 'rp-menu-item';
      btn.innerHTML =
        '<span class="rp-subtab-badge" data-shell="' + esc(info.id) + '">' +
        esc(info.badge || '&gt;_') + '</span>' +
        '<span>' + esc(T(info.label) || info.label) + '</span>' +
        (info.hint ? '<em>' + esc(info.hint) + '</em>' : '');
      btn.addEventListener('click', function () {
        hideShellMenu(ws);
        addTerminalTab(ws, info.id);
      });
      ws.shellMenu.appendChild(btn);
    });
  }

  function toggleShellMenu(ws) {
    if (!ws.shellMenu) return;
    if (!ws.shellMenu.hidden) { hideShellMenu(ws); return; }
    renderShellMenu(ws);
    ws.shellMenu.hidden = false;
    refreshEmbedSuppress();
  }

  function hideShellMenu(ws) {
    if (!ws || !ws.shellMenu || ws.shellMenu.hidden) return;
    ws.shellMenu.hidden = true;
    refreshEmbedSuppress();
  }

  function addTerminalTab(ws, shellId) {
    const info = shellFor(shellId) || { id: shellId, label: shellId, badge: '>_' };
    const label = T(info.label) || info.label;
    const same = ws.inner.filter(function (t) {
      return t.kind === 'terminal' && t.shell === shellId;
    }).length;
    const tab = { id: 't' + (S.rpSeq += 1), kind: 'terminal',
                  title: label + (same ? ' ' + (same + 1) : ''),
                  shell: shellId, sessionId: '', term: null, fit: null };
    const pane = document.createElement('div');
    pane.className = 'rp-pane rp-term';
    pane.innerHTML = '<div class="rp-term-host"></div>';
    tab.pane = pane;
    ws.panes.appendChild(pane);
    ws.inner.push(tab);
    activateInner(ws, tab.id);

    const host = pane.querySelector('.rp-term-host');
    if (!window.Terminal) {
      host.textContent = '终端组件未加载';
      return tab;
    }
    const term = new window.Terminal({
      fontFamily: '"JetBrains Mono", Consolas, "Cascadia Mono", "Microsoft YaHei UI", monospace',
      fontSize: 12.5,
      lineHeight: 1.2,
      cursorBlink: true,
      scrollback: 5000,
      theme: {
        background: '#0b0d11', foreground: '#dbe1e8', cursor: '#8ab4f8',
        selectionBackground: 'rgba(138,180,248,.28)',
      },
    });
    const fit = new window.FitAddon.FitAddon();
    term.loadAddon(fit);
    term.open(host);
    term.writeln('\x1b[90m正在启动 ' + label + '…\x1b[0m');
    tab.term = term;
    tab.fit = fit;

    Promise.resolve(call('terminal_start', { shell: shellId, cols: term.cols, rows: term.rows }))
      .then(function (res) {
        if (!res || !res.ok) {
          term.writeln('\x1b[31m' + ((res && res.error) || '启动失败') + '\x1b[0m');
          return;
        }
        if (ws.inner.indexOf(tab) < 0) {
          // 启动过程中标签已被关闭，别把会话留在后台
          call('terminal_close', { id: res.id });
          return;
        }
        tab.sessionId = res.id;
        term.onData(function (data) {
          call('terminal_write', { id: res.id, data: data });
        });
        requestAnimationFrame(function () { fitTerminal(tab); });
        if (window.ResizeObserver) {
          tab.ro = new ResizeObserver(function () {
            if (ws.inner.indexOf(tab) < 0) return;
            if (S.rpActive !== ws.id || ws.innerActive !== tab.id) return;
            fitTerminal(tab);
          });
          tab.ro.observe(host);
        }
        term.focus();
      });
    return tab;
  }

  function fitTerminal(tab) {
    if (!tab || !tab.fit || !tab.term || !tab.sessionId) return;
    try {
      tab.fit.fit();
      call('terminal_resize', { id: tab.sessionId, cols: tab.term.cols, rows: tab.term.rows });
    } catch (e) { /* 尚未完成布局 */ }
  }

  function handleTermEvent(evt) {
    S.rpTabs.forEach(function (ws) {
      if (ws.kind !== 'terminal' || !ws.inner) return;
      ws.inner.forEach(function (tab) {
        if (tab.sessionId !== evt.id || !tab.term) return;
        if (evt.type === 'term_data') tab.term.write(evt.data || '');
        else tab.term.writeln('\r\n\x1b[90m[进程已退出]\x1b[0m');
      });
    });
  }

  /* ---------------- 工作区与内标签公共逻辑 ---------------- */
  function ensureWorkspace(kind) {
    const ws = rpTabByKind(kind);
    if (ws) { activateRpTab(ws.id); return ws; }
    if (kind === 'browser') return mountBrowserWorkspace();
    if (kind === 'terminal') return mountTerminalWorkspace();
    return rpTabById('editor');
  }

  function renderSubTabs(ws) {
    if (!ws.subtabs) return;
    ws.subtabs.innerHTML = '';
    ws.inner.forEach(function (t) {
      const el = document.createElement('div');
      el.className = 'rp-subtab' + (ws.innerActive === t.id ? ' active' : '');
      el.title = t.title;
      el.innerHTML = subTabIcon(t) +
        '<span class="rp-subtab-name">' + esc(t.title) + '</span>' +
        '<span class="rp-subtab-close" title="关闭标签">×</span>';
      el.addEventListener('click', function (e) {
        if (e.target.classList.contains('rp-subtab-close')) {
          e.stopPropagation();
          closeInner(ws, t.id);
          return;
        }
        activateInner(ws, t.id);
      });
      ws.subtabs.appendChild(el);
    });
  }

  function subTabIcon(t) {
    if (t.kind === 'browser') {
      return '<span class="rp-subtab-ico">' + BROWSER_ICO_SMALL + '</span>';
    }
    const info = shellFor(t.shell);
    return '<span class="rp-subtab-badge" data-shell="' + esc(t.shell) + '">' +
      esc((info && info.badge) || '>_') + '</span>';
  }

  function activateInner(ws, id) {
    ws.innerActive = id;
    ws.inner.forEach(function (t) {
      if (t.pane) t.pane.classList.toggle('active', t.id === id);
    });
    renderSubTabs(ws);
    const inner = activeInner(ws);
    if (inner && inner.kind === 'browser' && inner.viewId) {
      syncBrowserRect(inner);
      requestAnimationFrame(function () { syncBrowserRect(inner); });
    }
    syncEmbeds();
    if (inner && inner.kind === 'terminal') {
      requestAnimationFrame(function () { fitTerminal(inner); });
    }
  }

  function releaseInner(tab) {
    if (!tab) return;
    if (tab.ro) { try { tab.ro.disconnect(); } catch (e) { /* ignore */ } }
    if (tab.kind === 'terminal') {
      if (tab.term) { try { tab.term.dispose(); } catch (e) { /* ignore */ } }
      tab.term = null;
      if (tab.sessionId) call('terminal_close', { id: tab.sessionId });
    }
    if (tab.kind === 'browser') {
      clearInterval(tab.timer);
      if (tab.viewId) call('browser_embed_close', { id: tab.viewId });
    }
    if (tab.pane) tab.pane.remove();
  }

  function closeInner(ws, id) {
    const idx = ws.inner.findIndex(function (t) { return t.id === id; });
    if (idx < 0) return;
    releaseInner(ws.inner[idx]);
    ws.inner.splice(idx, 1);
    if (!ws.inner.length) { closeRpTab(ws.id); return; }
    if (ws.innerActive === id) {
      activateInner(ws, ws.inner[Math.min(idx, ws.inner.length - 1)].id);
    } else {
      renderSubTabs(ws);
    }
  }

  function toggleRightPanel() {
    if (window.innerWidth < 900) {
      toast('窗口太窄，先放大窗口再看文件面板');
      return;
    }
    if ($('#rightPanel').hidden || !$('#rightPanel').classList.contains('open')) {
      S.rpManualClosed = false;
      openRightPanel();
    } else {
      closeRightPanel();
    }
  }

  async function loadTree(silent) {
    const res = await call('workspace_tree');
    const box = $('#rpBody');
    if (!res || !res.ok) {
      if (box && !silent) box.innerHTML = '<div class="rp-empty">读取文件列表失败</div>';
      return;
    }
    const items = res.items || [];
    const sig = JSON.stringify(items);
    // 静默刷新时内容没变就不重绘，避免滚动位置和展开状态被反复重置。
    if (silent && sig === S.treeSig && S.rpMode === 'tree') return;
    S.treeSig = sig;
    S.tree = items;
    S.treeRoot = res.root || '';
    S.rpMode = 'tree';
    const top = box ? box.scrollTop : 0;
    renderTreeView();
    if (box) box.scrollTop = top;
  }

  const FILE_TOOLS = {
    fs_write: 1, fs_edit: 1, fs_delete: 1, shell_exec: 1, shell_run: 1,
    docx_write: 1, xlsx_write: 1, pptx_write: 1, html_to_pptx: 1, office_edit: 1,
    screenshot_capture: 1, app_focus_capture: 1,
  };

  function scheduleTreeRefresh() {
    if (!S.rightOpen || S.rpMode !== 'tree') return;
    clearTimeout(S.treeTimer);
    S.treeTimer = setTimeout(function () { loadTree(true); }, 350);
  }

  let treePoller = null;

  function startTreePoller() {
    if (treePoller) return;
    // 面板打开时定时静默刷新，外部程序或未覆盖的工具改了文件也能及时出现。
    treePoller = setInterval(function () {
      if (!S.rightOpen || S.rpMode !== 'tree' || document.hidden) return;
      loadTree(true);
    }, 2500);
  }

  function renderTreeView() {
    S.rpMode = 'tree';
    const sub = $('#rpSub');
    sub.textContent = S.treeRoot ? shortenPath(S.treeRoot) : '';
    sub.title = S.treeRoot || '';
    const box = $('#rpBody');
    box.innerHTML = '';
    if (!S.tree || !S.tree.length) {
      box.innerHTML = '<div class="rp-empty">输出目录还没有文件<br><span>模型生成的文件会出现在这里</span></div>';
      return;
    }
    const query = (S.rpQuery || '').trim().toLowerCase();
    const items = query ? filterTree(S.tree, query) : S.tree;
    const wrap = document.createElement('div');
    if (!items.length) {
      wrap.innerHTML = '<div class="rp-empty">没有匹配的文件<br><span>换个关键词试试</span></div>';
      box.appendChild(wrap);
      return;
    }
    renderNodes(items, wrap, 0);
    box.appendChild(wrap);
  }

  // 搜索时保留命中项及其所有上级目录
  function filterTree(items, query) {
    const out = [];
    (items || []).forEach(function (it) {
      const hit = String(it.name || '').toLowerCase().indexOf(query) >= 0;
      if (it.type === 'dir') {
        const kids = filterTree(it.children || [], query);
        if (hit || kids.length) {
          out.push({ type: 'dir', name: it.name, path: it.path, children: kids });
        }
      } else if (hit) {
        out.push(it);
      }
    });
    return out;
  }

  const CARET_SVG = '<svg viewBox="0 0 16 16" width="10" height="10" aria-hidden="true">' +
    '<path d="m6 4 4 4-4 4" fill="none" stroke="currentColor" stroke-width="1.8" ' +
    'stroke-linecap="round" stroke-linejoin="round"/></svg>';

  function svgIcon(body) {
    return '<svg viewBox="0 0 16 16" width="15" height="15" fill="none" aria-hidden="true">' +
      body + '</svg>';
  }

  const FOLDER_SVG = svgIcon(
    '<path d="M2 4.6c0-.7.6-1.3 1.3-1.3h2.6l1.4 1.6h4.4c.7 0 1.3.6 1.3 1.3v5.5c0 .7-.6 1.3-1.3 1.3H3.3c-.7 0-1.3-.6-1.3-1.3V4.6Z" ' +
    'stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"/>'
  );
  const FOLDER_OPEN_SVG = svgIcon(
    '<path d="M2 4.6c0-.7.6-1.3 1.3-1.3h2.6l1.4 1.6h4.4c.7 0 1.3.6 1.3 1.3v1.1H2V4.6Z" ' +
    'stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"/>' +
    '<path d="M2.9 7.2h11.2c.5 0 .8.4.7.9l-.8 3.3c-.1.5-.6.9-1.2.9H3.3c-.7 0-1.3-.6-1.3-1.3V8c0-.4.3-.8.9-.8Z" ' +
    'stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"/>'
  );

  const FILE_ICONS = {
    code: svgIcon(
      '<path d="M5.4 5 2.6 8l2.8 3M10.6 5l2.8 3-2.8 3M9.1 3.6 6.9 12.4" ' +
      'stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/>'
    ),
    doc: svgIcon(
      '<path d="M3.6 2.2h5.4l3.4 3.4v8.2H3.6V2.2Z" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"/>' +
      '<path d="M9 2.3v3.4h3.4M5.6 8.5h4.8M5.6 10.9h3.2" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/>'
    ),
    media: svgIcon(
      '<rect x="2.2" y="3.2" width="11.6" height="9.6" rx="1.8" stroke="currentColor" stroke-width="1.3"/>' +
      '<circle cx="5.8" cy="6.4" r="1.1" stroke="currentColor" stroke-width="1.2"/>' +
      '<path d="m3 11.8 3.2-3.1 2 1.8 2.1-2.4 2.5 3.7" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/>'
    ),
    archive: svgIcon(
      '<rect x="2.2" y="3.6" width="11.6" height="9" rx="1.8" stroke="currentColor" stroke-width="1.3"/>' +
      '<path d="M2.2 6.6h11.6M6.9 6.6v2.6" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/>'
    ),
    other: svgIcon(
      '<path d="M3.6 2.2h5.4l3.4 3.4v8.2H3.6V2.2Z" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"/>' +
      '<path d="M9 2.3v3.4h3.4" stroke="currentColor" stroke-width="1.2" stroke-linejoin="round"/>'
    ),
  };

  const EXT_GROUPS = {
    code: ('py pyw pyc pyo js mjs cjs jsx ts tsx html htm css scss less json jsonc xml ' +
      'yml yaml toml ini cfg conf env bat cmd ps1 sh sql vue svelte').split(' '),
    doc: 'md markdown txt log pdf doc docx rtf ppt pptx xls xlsx csv tsv'.split(' '),
    media: ('png jpg jpeg gif webp bmp ico svg avif mp3 wav flac m4a ogg aac ' +
      'mp4 mov avi mkv webm wmv').split(' '),
    archive: 'zip rar 7z tar gz bz2 xz'.split(' '),
  };
  const EXT_GROUP_MAP = (function () {
    const map = {};
    Object.keys(EXT_GROUPS).forEach(function (group) {
      EXT_GROUPS[group].forEach(function (ext) { map[ext] = group; });
    });
    return map;
  })();

  function fileExt(name) {
    const base = String(name || '');
    const dot = base.lastIndexOf('.');
    return dot > 0 ? base.slice(dot + 1).toLowerCase() : '';
  }

  function fileGroup(name) {
    return EXT_GROUP_MAP[fileExt(name)] || 'other';
  }

  function treeIcon(name, isDir, open) {
    if (isDir) return open ? FOLDER_OPEN_SVG : FOLDER_SVG;
    return FILE_ICONS[fileGroup(name)] || FILE_ICONS.other;
  }

  function setExpanded(path, open) {
    const idx = S.expanded.indexOf(path);
    if (open && idx < 0) S.expanded.push(path);
    if (!open && idx >= 0) S.expanded.splice(idx, 1);
  }

  function renderNodes(items, parent, depth) {
    const filtering = !!(S.rpQuery || '').trim();
    (items || []).forEach(function (it) {
      const isDir = it.type === 'dir';
      const open = isDir && (filtering || S.expanded.indexOf(it.path) >= 0);
      const active = !isDir && !!S.previewPath && it.path === S.previewPath;
      const row = document.createElement('div');
      row.className = 'tree-row ' + (isDir ? 'dir' : 'file') +
        (open ? ' open' : '') + (active ? ' active' : '');
      row.style.paddingLeft = (8 + depth * 13) + 'px';
      row.title = it.path || it.name;
      if (it.path) row.dataset.path = it.path;
      row.innerHTML = '<span class="tree-caret' + (open ? ' open' : '') + '">' +
        (isDir ? CARET_SVG : '') + '</span>' +
        '<span class="tree-icon" data-group="' + (isDir ? 'dir' : fileGroup(it.name)) + '">' +
        treeIcon(it.name, isDir, open) + '</span>' +
        '<span class="tree-name">' + esc(it.name) + '</span>' +
        (!isDir ? '<span class="tree-size">' + fmtSizeShort(it.size) + '</span>' : '');
      if (isDir) {
        const children = document.createElement('div');
        children.className = 'tree-children';
        children.hidden = !open;
        renderNodes(it.children || [], children, depth + 1);
        row.addEventListener('click', function () {
          const next = children.hidden;
          children.hidden = !next;
          row.classList.toggle('open', next);
          row.querySelector('.tree-caret').classList.toggle('open', next);
          row.querySelector('.tree-icon').innerHTML = treeIcon(it.name, true, next);
          setExpanded(it.path, next);
        });
        parent.appendChild(row);
        parent.appendChild(children);
      } else {
        row.addEventListener('click', function () { previewFile(it.path); });
        parent.appendChild(row);
      }
    });
  }

  // 预览成功后同步文件树里的选中态
  function markTreeActive() {
    Array.prototype.slice.call(document.querySelectorAll('.tree-row.file')).forEach(function (row) {
      row.classList.toggle('active', !!S.previewPath && row.dataset.path === S.previewPath);
    });
  }

  async function previewFile(path) {
    if (window.innerWidth < 900) {
      toast('窗口太窄，先放大窗口再看预览');
      return;
    }
    if ($('#rightPanel').hidden) await openRightPanel();
    if (rpTabById('editor')) activateRpTab('editor');
    if (S.editMode && S.previewPath === path) { markTreeActive(); return; }
    if ((S.docxMode === 'edit' || S.pptMode === 'edit') && S.previewPath === path) {
      markTreeActive();
      return;
    }
    if (S.editMode && S.mdDirty) {
      const saved = await savePreview(S.mdDraft);
      if (!saved) return;
    }
    if (S.docxDirty || S.xlsxDirty || S.pptDirty) {
      const saved = await saveOfficeEdits();
      if (!saved) return;
    }
    const res = await call('read_preview', { path: path });
    if (!res) return;
    if (!res.ok) { toast(res.error || '无法预览'); return; }
    S.rpMode = 'preview';
    S.previewPath = res.path || path;
    S.previewData = res;
    S.editMode = false;
    S.mdDirty = false;
    S.mdDraft = null;
    S.pdfPage = 0;
    S.pdfZoom = 1.4;
    S.docxMode = 'render';
    S.docxDirty = false;
    S.docxEdits = {};
    S.xlsxDirty = false;
    S.xlsxEdits = {};
    S.xlsxSheet = '';
    S.pptIndex = 0;
    S.pptMode = 'render';
    S.pptDirty = false;
    S.pptEdits = {};
    S.pptData = null;
    setPreviewHead(res);
    $('#rpPreviewOpen').hidden = false;
    renderPreview(res);
    updatePreviewButtons();
    markTreeActive();
  }

  function setPreviewHead(res) {
    const name = (res && res.name) || '预览';
    $('#rpPreviewHead').hidden = false;
    const title = $('#rpPreviewTitle');
    title.textContent = name;
    title.title = name;
    const badge = $('#rpPreviewBadge');
    const ext = fileExt(name);
    badge.hidden = !ext;
    badge.textContent = ext ? ext.slice(0, 4).toUpperCase() : '';
    badge.dataset.group = fileGroup(name);
    const meta = $('#rpPreviewMeta');
    let metaText = res && res.size ? fmtSize(res.size) : '';
    if (res && res.kind === 'pdf' && res.pages) metaText = res.pages + ' 页 · ' + metaText;
    else if (res && res.kind === 'pptx' && res.slides) metaText = res.slides + ' 页 · ' + metaText;
    else if (res && res.kind === 'docx' && res.paragraphs) metaText = res.paragraphs + ' 段 · ' + metaText;
    else if (res && res.kind === 'xlsx' && res.sheets) metaText = res.sheets.length + ' 个工作表 · ' + metaText;
    meta.textContent = metaText;
    meta.hidden = !metaText;
  }

  function previewModeOf(res) {
    if (!res) return 'render';
    if (res.kind === 'markdown') return S.editMode ? 'edit' : 'render';
    if (res.kind === 'docx') return S.docxMode;
    if (res.kind === 'pptx') return S.pptMode;
    return 'render';
  }

  function previewDirtyOf(res) {
    if (!res) return false;
    if (res.kind === 'markdown') return !!(S.editMode && S.mdDirty);
    if (res.kind === 'docx') return !!(S.docxMode === 'edit' && S.docxDirty);
    if (res.kind === 'xlsx') return !!S.xlsxDirty;
    if (res.kind === 'pptx') return !!(S.pptMode === 'edit' && S.pptDirty);
    return false;
  }

  function updatePreviewButtons() {
    const res = S.previewData || {};
    const editable = !!res.path && (res.kind === 'markdown' || res.kind === 'docx' || res.kind === 'pptx');
    const seg = $('#rpModeSeg');
    if (seg) {
      seg.hidden = !editable;
      if (editable) {
        const mode = previewModeOf(res);
        Array.prototype.slice.call(seg.querySelectorAll('[data-md-mode]')).forEach(function (b) {
          const on = b.dataset.mdMode === mode;
          b.classList.toggle('active', on);
          b.setAttribute('aria-pressed', on ? 'true' : 'false');
        });
      }
    }
    const save = $('#rpSaveBtn');
    if (save) {
      const editing = (res.kind === 'markdown' && S.editMode) ||
        (res.kind === 'docx' && S.docxMode === 'edit') ||
        (res.kind === 'pptx' && S.pptMode === 'edit');
      const dirty = previewDirtyOf(res);
      save.hidden = !(editing || dirty);
      save.disabled = !dirty;
    }
    const web = $('#rpHtmlOpen');
    if (web) web.hidden = !(res.kind === 'html' && res.path);
  }

  function setPreviewMode(mode) {
    const res = S.previewData;
    if (!res) return;
    if (res.kind === 'markdown') setMdMode(mode);
    else if (res.kind === 'docx') setDocxMode(mode);
    else if (res.kind === 'pptx') setPptMode(mode);
  }

  function setMdMode(mode) {
    const res = S.previewData;
    if (!res || res.kind !== 'markdown') return;
    if (mode === 'edit') {
      if (!res.path) { toast('拖入的文件无法直接保存，请从文件列表打开'); return; }
      S.editMode = true;
      buildMdEditor(res);
      updatePreviewButtons();
      return;
    }
    commitMdDraft().then(function (ok) {
      if (!ok) return;
      S.editMode = false;
      renderPreview(res);
      updatePreviewButtons();
    });
  }

  async function commitMdDraft() {
    if (!S.editMode || !S.mdDirty || S.mdDraft == null) return true;
    return await savePreview(S.mdDraft);
  }

  function buildMdEditor(res) {
    const box = $('#rpPreviewBody');
    box.innerHTML = '';
    box.classList.add('editing');
    S.mdDraft = res.content || '';
    S.mdDirty = false;
    const wrap = document.createElement('div');
    wrap.className = 'rp-md-edit';
    wrap.innerHTML =
      '<div class="rp-md-pane">' +
        '<div class="rp-md-pane-head"><span class="rp-md-pane-tag">' + esc(T('Markdown 源码')) + '</span>' +
        '<span class="rp-md-status"></span></div>' +
        '<textarea class="rp-editor" spellcheck="false" wrap="off"></textarea>' +
      '</div>' +
      '<div class="rp-md-pane rp-md-pane-live">' +
        '<div class="rp-md-pane-head"><span class="rp-md-pane-tag">' + esc(T('实时预览')) + '</span>' +
        '<span class="rp-md-pane-tip">Ctrl+S</span></div>' +
        '<div class="rp-md-live md rp-md"></div>' +
      '</div>';
    const area = wrap.querySelector('textarea');
    const live = wrap.querySelector('.rp-md-live');
    const status = wrap.querySelector('.rp-md-status');
    area.value = S.mdDraft;

    function paint() { live.innerHTML = renderMarkdown(area.value); }
    function stats() {
      const val = area.value;
      const lines = val ? val.split(/\r?\n/).length : 1;
      status.textContent = lines + ' ' + T('行') + ' · ' + val.length + ' ' + T('字符');
    }
    let timer = 0;
    area.addEventListener('input', function () {
      S.mdDraft = area.value;
      if (!S.mdDirty) { S.mdDirty = true; updatePreviewButtons(); }
      stats();
      clearTimeout(timer);
      timer = setTimeout(paint, 120);
    });
    area.addEventListener('keydown', function (e) {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
        e.preventDefault();
        savePreview(area.value);
        return;
      }
      if (e.key === 'Tab') {
        e.preventDefault();
        const start = area.selectionStart;
        const end = area.selectionEnd;
        area.value = area.value.slice(0, start) + '  ' + area.value.slice(end);
        area.setSelectionRange(start + 2, start + 2);
        area.dispatchEvent(new Event('input'));
      }
    });
    paint();
    stats();
    box.appendChild(wrap);
    area.focus();
    area.setSelectionRange(area.value.length, area.value.length);
  }

  async function savePreview(content) {
    const res = S.previewData;
    if (!res || !res.path) return false;
    const out = await call('save_preview', { path: res.path, content: content });
    if (!out || !out.ok) {
      toast((out && out.error) || '保存失败');
      return false;
    }
    res.content = content;
    S.mdDraft = content;
    S.mdDirty = false;
    toast('已保存');
    updatePreviewButtons();
    return true;
  }

  /* ---------------- 办公文件预览 ---------------- */
  function makeEl(tag, cls, text) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  }

  function officeHint(text) {
    return makeEl('div', 'rp-office-hint', text);
  }

  async function reloadPreview() {
    const res = S.previewData;
    if (!res || !res.path) return;
    const fresh = await call('read_preview', { path: res.path });
    if (!fresh || !fresh.ok) return;
    S.previewData = fresh;
    setPreviewHead(fresh);
    renderPreview(fresh);
    updatePreviewButtons();
  }

  async function saveOfficeEdits(refresh) {
    const res = S.previewData;
    if (!res || !res.path) return true;
    let updates = [];
    if (res.kind === 'docx') {
      updates = Object.keys(S.docxEdits).map(function (k) {
        return { index: +k, text: S.docxEdits[k] };
      });
    } else if (res.kind === 'xlsx') {
      Object.keys(S.xlsxEdits).forEach(function (sheet) {
        const cells = S.xlsxEdits[sheet] || {};
        Object.keys(cells).forEach(function (cell) {
          updates.push({ sheet: sheet, cell: cell, value: cells[cell] });
        });
      });
    } else if (res.kind === 'pptx') {
      updates = Object.keys(S.pptEdits).map(function (k) {
        const parts = k.split(':');
        return { slide: +parts[0], shape: +parts[1], text: S.pptEdits[k] };
      });
    }
    if (!updates.length) return true;
    const out = await call('office_save', { path: res.path, kind: res.kind, updates: updates });
    if (!out || !out.ok) {
      toast((out && out.error) || '保存失败');
      return false;
    }
    if (res.kind === 'docx') {
      (res.blocks || []).forEach(function (b) {
        if (Object.prototype.hasOwnProperty.call(S.docxEdits, b.index)) {
          b.text = S.docxEdits[b.index];
        }
      });
      S.docxEdits = {};
      S.docxDirty = false;
    } else if (res.kind === 'xlsx') {
      Object.keys(S.xlsxEdits).forEach(function (sheet) {
        const cells = S.xlsxEdits[sheet] || {};
        Object.keys(cells).forEach(function (cell) {
          const td = document.querySelector('.rp-sheet-cell[data-sheet="' + CSS.escape(sheet) +
            '"][data-ref="' + cell + '"]');
          if (td) td.dataset.orig = cells[cell];
        });
      });
      S.xlsxEdits = {};
      S.xlsxDirty = false;
    } else if (res.kind === 'pptx') {
      S.pptEdits = {};
      S.pptDirty = false;
    }
    toast('已保存');
    updatePreviewButtons();
    if (refresh && res.kind === 'xlsx') {
      await reloadPreview();
    }
    return true;
  }

  /* PDF */
  function renderPdf(res) {
    const box = $('#rpPreviewBody');
    box.innerHTML = '';
    box.classList.remove('editing');
    const wrap = makeEl('div', 'rp-pdf');
    const bar = makeEl('div', 'rp-pdf-bar');
    const prev = makeEl('button', 'rp-pdf-btn');
    prev.type = 'button';
    prev.title = T('上一页');
    prev.innerHTML = '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M10 3.5 5.5 8l4.5 4.5"/></svg>';
    const next = makeEl('button', 'rp-pdf-btn');
    next.type = 'button';
    next.title = T('下一页');
    next.innerHTML = '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M6 3.5 10.5 8 6 12.5"/></svg>';
    const label = makeEl('span', 'rp-pdf-page', '1 / ' + (res.pages || 1));
    const zoomOut = makeEl('button', 'rp-pdf-btn rp-pdf-zoom', '−');
    zoomOut.type = 'button';
    zoomOut.title = T('缩小');
    const zoomIn = makeEl('button', 'rp-pdf-btn rp-pdf-zoom', '+');
    zoomIn.type = 'button';
    zoomIn.title = T('放大');
    bar.append(prev, next, label, zoomOut, zoomIn);
    const stage = makeEl('div', 'rp-pdf-stage');
    const img = makeEl('img', 'rp-pdf-img');
    stage.appendChild(img);
    wrap.append(bar, stage);
    box.appendChild(wrap);

    const state = { page: res.page ? res.page.page : 0, pages: res.pages || 1,
      zoom: res.page ? res.page.zoom : 1.4 };
    function apply(out) {
      if (!out || !out.ok) return;
      state.page = out.page;
      state.zoom = out.zoom;
      img.src = out.data_url;
      label.textContent = (out.page + 1) + ' / ' + out.pages;
      prev.disabled = out.page <= 0;
      next.disabled = out.page >= out.pages - 1;
    }
    function go(page, zoom) {
      if (page < 0 || page >= state.pages) return;
      const z = Math.max(0.6, Math.min(zoom || state.zoom, 3));
      call('pdf_page', { path: res.path, page: page, zoom: z }).then(function (out) {
        if (out && out.ok) apply(out);
      });
    }
    apply(res.page);
    prev.addEventListener('click', function () { go(state.page - 1); });
    next.addEventListener('click', function () { go(state.page + 1); });
    zoomOut.addEventListener('click', function () { go(state.page, state.zoom - 0.2); });
    zoomIn.addEventListener('click', function () { go(state.page, state.zoom + 0.2); });
  }

  /* Word */
  function renderDocx(res) {
    const box = $('#rpPreviewBody');
    box.innerHTML = '';
    box.classList.remove('editing');
    if (S.docxMode === 'edit') { buildDocxEditor(res); return; }
    const wrap = makeEl('div', 'rp-docx');
    const page = makeEl('div', 'rp-docx-page');
    page.innerHTML = res.html || '';
    wrap.appendChild(page);
    box.appendChild(wrap);
  }

  function setDocxMode(mode) {
    const res = S.previewData;
    if (!res || res.kind !== 'docx' || !res.path) return;
    if (mode === 'edit') {
      S.docxMode = 'edit';
      buildDocxEditor(res);
      updatePreviewButtons();
      return;
    }
    if (S.docxDirty) {
      saveOfficeEdits().then(function (ok) {
        if (!ok) return;
        S.docxMode = 'render';
        reloadPreview();
      });
      return;
    }
    S.docxMode = 'render';
    renderDocx(res);
    updatePreviewButtons();
  }

  function buildDocxEditor(res) {
    const box = $('#rpPreviewBody');
    box.innerHTML = '';
    box.classList.add('editing');
    const wrap = makeEl('div', 'rp-docx rp-docx-editing');
    wrap.appendChild(officeHint(T('文本级编辑：只改文字，原有字体、颜色、图片与表格保持不变')));
    const page = makeEl('div', 'rp-docx-page rp-docx-edit');
    (res.blocks || []).forEach(function (b) {
      let tag = String(b.tag || 'p').toLowerCase();
      if (['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'blockquote'].indexOf(tag) < 0) tag = 'p';
      const node = document.createElement(tag);
      node.className = 'rp-docx-block';
      node.contentEditable = 'true';
      node.spellcheck = false;
      node.dataset.index = b.index;
      if (b.text) node.textContent = b.text;
      else node.innerHTML = '<br>';
      if (b.size) node.style.fontSize = (Math.min(b.size, 40) * 1.333).toFixed(1) + 'px';
      if (b.bold) node.style.fontWeight = '700';
      if (b.align) node.style.textAlign = b.align;
      node.addEventListener('input', function () {
        const text = node.innerText.replace(/\u00a0/g, ' ').replace(/\n$/, '');
        if (text === (b.text || '')) delete S.docxEdits[b.index];
        else S.docxEdits[b.index] = text;
        S.docxDirty = Object.keys(S.docxEdits).length > 0;
        updatePreviewButtons();
      });
      page.appendChild(node);
    });
    wrap.appendChild(page);
    box.appendChild(wrap);
    const first = page.querySelector('.rp-docx-block');
    if (first) first.focus();
  }

  /* Excel：仿 WPS / Excel 的表格视图 */
  function renderXlsx(res) {
    const box = $('#rpPreviewBody');
    box.innerHTML = '';
    box.classList.remove('editing');
    box.classList.add('sheet-mode');
    const wrap = makeEl('div', 'rp-sheet');
    const bar = makeEl('div', 'rp-sheet-bar');
    const nameBox = makeEl('div', 'rp-sheet-name', 'A1');
    const fx = makeEl('span', 'rp-sheet-fx', 'fx');
    const input = document.createElement('input');
    input.className = 'rp-sheet-input';
    input.type = 'text';
    input.spellcheck = false;
    input.autocomplete = 'off';
    bar.append(nameBox, fx, input);
    const scroll = makeEl('div', 'rp-sheet-scroll');
    const tabbar = makeEl('div', 'rp-sheet-tabbar');
    const tabs = makeEl('div', 'rp-sheet-tabs');
    const status = makeEl('span', 'rp-sheet-status', T('单击选中 · 双击编辑'));
    tabbar.append(tabs, status);
    wrap.append(bar, scroll, tabbar);
    box.appendChild(wrap);

    const sheets = res.sheets || [];
    if (!sheets.length) {
      scroll.textContent = '没有工作表';
      return;
    }
    let current = sheets.filter(function (s) { return s.name === S.xlsxSheet; })[0] || sheets[0];
    S.xlsxSheet = current.name;
    let sel = null;
    let editing = null;

    function refreshStatus() {
      status.textContent = S.xlsxDirty ? T('待保存') : T('单击选中 · 双击编辑');
    }

    function cellAt(ref) {
      return scroll.querySelector('.rp-sheet-cell[data-ref="' + ref + '"]');
    }

    function record(ref, value) {
      const td = cellAt(ref);
      const bucket = S.xlsxEdits[current.name] = S.xlsxEdits[current.name] || {};
      const original = td ? (td.dataset.orig || '') : '';
      if (value === original) delete bucket[ref];
      else bucket[ref] = value;
      if (!Object.keys(bucket).length) delete S.xlsxEdits[current.name];
      S.xlsxDirty = Object.keys(S.xlsxEdits).length > 0;
      refreshStatus();
      updatePreviewButtons();
    }

    function selectCell(td) {
      if (!td) return;
      if (editing && editing !== td) commitEdit();
      if (sel) sel.classList.remove('sel');
      Array.prototype.slice.call(scroll.querySelectorAll('.hl')).forEach(function (el) {
        el.classList.remove('hl');
      });
      sel = td;
      td.classList.add('sel');
      try { td.focus({ preventScroll: true }); } catch (e) { td.focus(); }
      S.xlsxSel = td.dataset.ref;
      nameBox.textContent = td.dataset.ref;
      const col = scroll.querySelector('.rp-sheet-col[data-col="' + td.dataset.col + '"]');
      const row = scroll.querySelector('.rp-sheet-row[data-row="' + td.dataset.row + '"]');
      if (col) col.classList.add('hl');
      if (row) row.classList.add('hl');
      input.value = td.dataset.formula || td.dataset.raw || '';
      refreshStatus();
    }

    function selectRef(ref) {
      const td = cellAt(ref);
      if (td) selectCell(td);
    }

    function moveSelection(dr, dc) {
      if (!sel) return;
      const row = Math.max(1, (+sel.dataset.row || 1) + dr);
      const col = Math.max(1, Math.min(28, (+sel.dataset.col || 1) + dc));
      selectRef(colName(col) + row);
    }

    function startEdit(td, initial) {
      if (!td) return;
      if (editing && editing !== td) commitEdit();
      selectCell(td);
      editing = td;
      td.contentEditable = 'true';
      td.classList.add('editing');
      td.textContent = initial != null ? initial : (td.dataset.raw || '');
      if (!td.textContent) td.innerHTML = '<br>';
      td.focus();
      const range = document.createRange();
      range.selectNodeContents(td);
      range.collapse(false);
      const selection = window.getSelection();
      selection.removeAllRanges();
      selection.addRange(range);
      input.value = td.textContent;
    }

    function commitEdit(moveDown) {
      if (!editing) return;
      const td = editing;
      editing = null;
      td.contentEditable = 'false';
      td.classList.remove('editing');
      const text = td.innerText.replace(/\u00a0/g, ' ').replace(/\r?\n/g, ' ');
      if (text !== (td.dataset.raw || '')) {
        td.dataset.raw = text;
        td.dataset.disp = text;
        td.dataset.formula = text.charAt(0) === '=' ? text : '';
        td.textContent = text;
        td.classList.toggle('is-formula', text.charAt(0) === '=');
        record(td.dataset.ref, text);
      } else {
        td.textContent = td.dataset.disp || '';
      }
      input.value = td.dataset.formula || td.dataset.raw || '';
      if (moveDown) moveSelection(1, 0);
    }

    function cancelEdit() {
      if (!editing) return;
      const td = editing;
      editing = null;
      td.contentEditable = 'false';
      td.classList.remove('editing');
      td.textContent = td.dataset.disp || '';
      input.value = td.dataset.formula || td.dataset.raw || '';
    }

    function paintTabs() {
      tabs.innerHTML = '';
      sheets.forEach(function (s) {
        const btn = makeEl('button', 'rp-sheet-tab', s.name);
        btn.type = 'button';
        btn.classList.toggle('active', s.name === current.name);
        btn.addEventListener('click', function () {
          commitEdit();
          current = s;
          S.xlsxSheet = s.name;
          S.xlsxSel = 'A1';
          paintTabs();
          paintGrid();
        });
        tabs.appendChild(btn);
      });
      const add = makeEl('button', 'rp-sheet-add', '+');
      add.type = 'button';
      add.title = T('新建工作表');
      add.addEventListener('click', addSheet);
      tabs.appendChild(add);
    }

    async function addSheet() {
      const saved = await saveOfficeEdits();
      if (!saved) return;
      const out = await call('xlsx_add_sheet', { path: res.path, name: '新工作表' });
      if (!out || !out.ok) {
        toast((out && out.error) || '新建工作表失败');
        return;
      }
      S.xlsxSheet = out.name;
      S.xlsxSel = 'A1';
      toast('已新建工作表：' + out.name);
      await reloadPreview();
    }

    function paintGrid() {
      scroll.innerHTML = '';
      scroll.appendChild(buildSheetGrid(current, {
        select: selectCell,
        startEdit: startEdit,
        commit: commitEdit,
        cancel: cancelEdit,
        record: record,
        move: moveSelection,
        colName: colName,
      }));
      selectRef(S.xlsxSel || 'A1');
      refreshStatus();
    }

    input.addEventListener('focus', function () {
      if (sel) input.value = sel.dataset.formula || sel.dataset.raw || '';
    });
    input.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') {
        e.preventDefault();
        if (!sel) return;
        const value = input.value;
        sel.dataset.raw = value;
        sel.dataset.disp = value;
        sel.dataset.formula = value.charAt(0) === '=' ? value : '';
        sel.textContent = value;
        sel.classList.toggle('is-formula', value.charAt(0) === '=');
        record(sel.dataset.ref, value);
        moveSelection(1, 0);
        input.blur();
      } else if (e.key === 'Escape') {
        input.value = sel ? (sel.dataset.formula || sel.dataset.raw || '') : '';
        input.blur();
      }
    });

    paintTabs();
    paintGrid();
  }

  function colName(n) {
    let name = '';
    while (n > 0) {
      const r = (n - 1) % 26;
      name = String.fromCharCode(65 + r) + name;
      n = Math.floor((n - 1) / 26);
    }
    return name;
  }

  function colIndex(letters) {
    let n = 0;
    for (let i = 0; i < letters.length; i++) {
      n = n * 26 + (letters.charCodeAt(i) - 64);
    }
    return n;
  }

  function buildSheetGrid(sheet, api) {
    const rows = sheet.rows || [];
    let maxCols = sheet.cols_total || 8;
    rows.forEach(function (r) { maxCols = Math.max(maxCols, (r || []).length); });
    const colCount = Math.min(28, Math.max(12, maxCols));
    const covered = {};
    const spans = {};
    (sheet.merges || []).forEach(function (range) {
      const m = /^([A-Z]+)(\d+):([A-Z]+)(\d+)$/i.exec(range);
      if (!m) return;
      const c1 = colIndex(m[1].toUpperCase());
      const r1 = +m[2];
      const c2 = colIndex(m[3].toUpperCase());
      const r2 = +m[4];
      spans[r1 + ':' + c1] = { rows: r2 - r1 + 1, cols: c2 - c1 + 1 };
      for (let r = r1; r <= r2; r++) {
        for (let c = c1; c <= c2; c++) {
          if (r !== r1 || c !== c1) covered[r + ':' + c] = 1;
        }
      }
    });
    const table = makeEl('table', 'rp-sheet-grid');
    const colgroup = document.createElement('colgroup');
    colgroup.appendChild(makeEl('col', 'rp-sheet-corner-col'));
    for (let c = 1; c <= colCount; c++) {
      const col = document.createElement('col');
      const width = sheet.widths && sheet.widths[api.colName(c)];
      if (width) col.style.width = Math.max(64, Math.min(width, 320)) + 'px';
      colgroup.appendChild(col);
    }
    table.appendChild(colgroup);
    const thead = document.createElement('thead');
    const hr = document.createElement('tr');
    hr.appendChild(makeEl('th', 'rp-sheet-corner'));
    for (let c = 1; c <= colCount; c++) {
      const th = makeEl('th', 'rp-sheet-col', api.colName(c));
      th.dataset.col = String(c);
      hr.appendChild(th);
    }
    thead.appendChild(hr);
    table.appendChild(thead);
    const tbody = document.createElement('tbody');
    const rowCount = Math.max(rows.length, 40);
    for (let r = 1; r <= rowCount; r++) {
      const tr = document.createElement('tr');
      const rowHead = makeEl('th', 'rp-sheet-row', String(r));
      rowHead.dataset.row = String(r);
      tr.appendChild(rowHead);
      const row = rows[r - 1] || [];
      for (let c = 1; c <= colCount; c++) {
        if (covered[r + ':' + c]) continue;
        const cell = row[c - 1] || {};
        const ref = api.colName(c) + r;
        const td = makeEl('td', 'rp-sheet-cell');
        td.tabIndex = -1;
        td.spellcheck = false;
        td.dataset.ref = ref;
        td.dataset.row = String(r);
        td.dataset.col = String(c);
        td.dataset.sheet = sheet.name;
        td.dataset.orig = cell.raw != null ? cell.raw : (cell.v || '');
        td.dataset.raw = td.dataset.orig;
        td.dataset.disp = cell.v || '';
        td.dataset.formula = cell.f || '';
        td.textContent = cell.v || '';
        const span = spans[r + ':' + c];
        if (span) {
          if (span.cols > 1) td.colSpan = span.cols;
          if (span.rows > 1) td.rowSpan = span.rows;
          td.classList.add('merged');
        }
        if (cell.n) td.classList.add('num');
        if (cell.f) td.classList.add('is-formula');
        const style = cell.s || {};
        if (style.b) td.style.fontWeight = '700';
        if (style.i) td.style.fontStyle = 'italic';
        if (style.bg) td.style.background = style.bg;
        if (style.fg) td.style.color = style.fg;
        if (style.fs) td.style.fontSize = Math.max(9, Math.min(style.fs, 20)) + 'px';
        if (style.a) td.style.textAlign = style.a;
        if (style.va) td.style.verticalAlign = style.va;
        if (style.wrap) td.classList.add('wrap');
        td.addEventListener('mousedown', function (e) {
          if (td.contentEditable === 'true') return;
          e.preventDefault();
          api.select(td);
        });
        td.addEventListener('dblclick', function () { api.startEdit(td, td.dataset.raw); });
        td.addEventListener('blur', function () {
          if (td.contentEditable === 'true') api.commit(false);
        });
        td.addEventListener('keydown', function (e) {
          if (td.contentEditable === 'true') {
            if (e.key === 'Enter') { e.preventDefault(); api.commit(true); }
            else if (e.key === 'Escape') { e.preventDefault(); api.cancel(); }
            else if (e.key === 'Tab') {
              e.preventDefault();
              api.commit(false);
              api.move(0, e.shiftKey ? -1 : 1);
            }
            return;
          }
          if (e.key === 'Enter' || e.key === 'F2') {
            e.preventDefault();
            api.startEdit(td, td.dataset.raw);
            return;
          }
          if (e.key === 'Backspace' || e.key === 'Delete') {
            e.preventDefault();
            td.dataset.raw = '';
            td.dataset.disp = '';
            td.dataset.formula = '';
            td.textContent = '';
            td.classList.remove('is-formula');
            api.record(ref, '');
            return;
          }
          if (e.key === 'Tab') {
            e.preventDefault();
            api.move(0, e.shiftKey ? -1 : 1);
            return;
          }
          if (e.key === 'ArrowUp') { e.preventDefault(); api.move(-1, 0); return; }
          if (e.key === 'ArrowDown') { e.preventDefault(); api.move(1, 0); return; }
          if (e.key === 'ArrowLeft') { e.preventDefault(); api.move(0, -1); return; }
          if (e.key === 'ArrowRight') { e.preventDefault(); api.move(0, 1); return; }
          if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) {
            e.preventDefault();
            api.startEdit(td, e.key);
          }
        });
        tr.appendChild(td);
      }
      tbody.appendChild(tr);
    }
    table.appendChild(tbody);
    return table;
  }

  /* PowerPoint */
  function renderPptx(res) {
    const box = $('#rpPreviewBody');
    box.innerHTML = '';
    box.classList.remove('editing');
    const wrap = makeEl('div', 'rp-ppt');
    const stageWrap = makeEl('div', 'rp-ppt-stage-wrap');
    const stage = makeEl('div', 'rp-ppt-stage');
    const strip = makeEl('div', 'rp-ppt-strip');
    wrap.append(stageWrap, strip);
    box.appendChild(wrap);
    stageWrap.appendChild(stage);
    const slide = S.pptData || res.slide;
    S.pptData = slide;
    S.pptIndex = slide ? slide.index : 0;
    renderPptStage(res, slide, stage);
    buildPptStrip(res, strip, stage);
  }

  function setPptMode(mode) {
    const res = S.previewData;
    if (!res || res.kind !== 'pptx' || !res.path) return;
    if (mode === 'edit') {
      S.pptMode = 'edit';
      renderPptx(res);
      updatePreviewButtons();
      return;
    }
    if (S.pptDirty) {
      saveOfficeEdits().then(function (ok) {
        if (!ok) return;
        S.pptMode = 'render';
        const stage = document.querySelector('.rp-ppt-stage');
        if (stage) loadPptSlide(res, S.pptIndex, stage);
        updatePreviewButtons();
      });
      return;
    }
    S.pptMode = 'render';
    renderPptx(res);
    updatePreviewButtons();
  }

  function pptTextOf(shape) {
    return (shape.paras || []).map(function (p) {
      return (p.runs || []).map(function (r) { return r.t || ''; }).join('');
    }).join('\n');
  }

  function renderPptStage(res, slide, stage) {
    if (!slide) return;
    stage.innerHTML = '';
    stage.style.aspectRatio = (slide.width || 13.333) + ' / ' + (slide.height || 7.5);
    stage.style.background = slide.bg || '#ffffff';
    stage.classList.toggle('editing', S.pptMode === 'edit');
    const scale = 100 / ((slide.width || 13.333) * 72);
    (slide.shapes || []).forEach(function (shape) {
      const node = makeEl('div', 'rp-ppt-shape rp-ppt-' + shape.type);
      node.style.left = (shape.x * 100).toFixed(3) + '%';
      node.style.top = (shape.y * 100).toFixed(3) + '%';
      node.style.width = (shape.w * 100).toFixed(3) + '%';
      node.style.height = (shape.h * 100).toFixed(3) + '%';
      if (shape.fill) node.style.background = shape.fill;
      if (shape.line) node.style.boxShadow = 'inset 0 0 0 1px ' + shape.line;
      if (shape.round) node.style.borderRadius = '8px';
      if (shape.type === 'image') {
        const img = makeEl('img');
        img.src = shape.src;
        img.alt = '';
        node.appendChild(img);
      } else if (shape.type === 'table' && shape.table) {
        const table = makeEl('table', 'rp-ppt-table');
        shape.table.forEach(function (row, ri) {
          const tr = document.createElement('tr');
          (row || []).forEach(function (value) {
            const td = makeEl(ri === 0 ? 'th' : 'td', null, value);
            td.style.fontSize = (14 * scale * 1.15).toFixed(3) + 'cqw';
            tr.appendChild(td);
          });
          table.appendChild(tr);
        });
        node.appendChild(table);
      } else if (shape.type === 'chart') {
        node.appendChild(makeEl('div', 'rp-ppt-chart', T('图表')));
      } else if (shape.type === 'text') {
        if (shape.anchor === 'middle') node.style.justifyContent = 'center';
        else if (shape.anchor === 'bottom') node.style.justifyContent = 'flex-end';
        (shape.paras || []).forEach(function (para) {
          const p = makeEl('p', 'rp-ppt-para');
          if (para.align) p.style.textAlign = para.align;
          if (para.level) p.style.paddingLeft = (para.level * 2.2) + '%';
          (para.runs || []).forEach(function (run) {
            const span = makeEl('span', null, run.t || '');
            if (run.b) span.style.fontWeight = '700';
            if (run.i) span.style.fontStyle = 'italic';
            if (run.c) span.style.color = run.c;
            if (run.f) span.style.fontFamily = '"' + run.f + '", "Microsoft YaHei", sans-serif';
            span.style.fontSize = ((run.sz || 18) * scale).toFixed(3) + 'cqw';
            p.appendChild(span);
          });
          if (!p.childNodes.length) p.appendChild(makeEl('span', null, ' '));
          node.appendChild(p);
        });
        if (S.pptMode === 'edit' && pptTextOf(shape)) {
          node.classList.add('rp-ppt-editable');
          node.contentEditable = 'true';
          node.spellcheck = false;
          node.dataset.slide = S.pptIndex;
          node.dataset.shape = shape.id;
          const original = pptTextOf(shape);
          node.addEventListener('input', function () {
            const text = node.innerText.replace(/\u00a0/g, ' ');
            const key = S.pptIndex + ':' + shape.id;
            if (text === original) delete S.pptEdits[key];
            else S.pptEdits[key] = text;
            S.pptDirty = Object.keys(S.pptEdits).length > 0;
            updatePreviewButtons();
          });
        }
      }
      stage.appendChild(node);
    });
  }

  function loadPptSlide(res, index, stage) {
    if (!res || !res.path || !stage) return;
    stage.classList.add('loading');
    call('pptx_slide', { path: res.path, index: index }).then(function (out) {
      stage.classList.remove('loading');
      if (!out || !out.ok) { toast((out && out.error) || '读取幻灯片失败'); return; }
      S.pptIndex = out.index;
      S.pptData = out;
      renderPptStage(res, out, stage);
      const strip = document.querySelector('.rp-ppt-strip');
      if (strip) {
        Array.prototype.slice.call(strip.children).forEach(function (btn, i) {
          btn.classList.toggle('active', i === out.index);
        });
      }
    });
  }

  function buildPptStrip(res, strip, stage) {
    strip.innerHTML = '';
    const total = res.slides || 1;
    for (let i = 0; i < total; i++) {
      const btn = makeEl('button', 'rp-ppt-dot', String(i + 1));
      btn.type = 'button';
      btn.classList.toggle('active', i === S.pptIndex);
      btn.addEventListener('click', function () { loadPptSlide(res, i, stage); });
      strip.appendChild(btn);
    }
    strip.title = T('幻灯片');
  }

  async function openBrowser(url) {
    const target = String(url || '').trim();
    if (!target) {
      toast('请输入网址或本地 HTML 路径');
      return;
    }
    if (window.innerWidth < 900) {
      toast('窗口太窄，先放大窗口再看预览');
      return;
    }
    if ($('#rightPanel').hidden) {
      S.rpManualClosed = false;
      await openRightPanel();
    }
    const ws = ensureWorkspace('browser');
    let inner = activeInner(ws);
    if (!inner || inner.kind !== 'browser' || inner.url) inner = addBrowserTab(ws);
    inner.input.value = target;
    inner.open(target);
  }

  function renderPreview(res) {
    const box = $('#rpPreviewBody');
    box.innerHTML = '';
    box.classList.remove('editing', 'sheet-mode');
    if (res.kind === 'image') {
      const img = document.createElement('img');
      img.className = 'rp-image';
      img.src = res.data_url;
      img.addEventListener('click', function () { openLightbox(res.data_url); });
      box.appendChild(img);
    } else if (res.kind === 'markdown') {
      const md = document.createElement('div');
      md.className = 'md rp-md';
      md.innerHTML = renderMarkdown(res.content || '');
      box.appendChild(md);
    } else if (res.kind === 'pdf') {
      renderPdf(res);
    } else if (res.kind === 'docx') {
      renderDocx(res);
    } else if (res.kind === 'xlsx') {
      renderXlsx(res);
    } else if (res.kind === 'pptx') {
      renderPptx(res);
    } else if (res.kind === 'html') {
      const pre = document.createElement('pre');
      pre.className = 'rp-text rp-code';
      pre.textContent = res.content || '';
      box.appendChild(pre);
    } else if (res.kind === 'text') {
      const pre = document.createElement('pre');
      pre.className = 'rp-text';
      pre.textContent = res.content || '';
      box.appendChild(pre);
    } else {
      box.innerHTML = '<div class="rp-placeholder"><div class="rp-ph-title">该类型暂不支持预览</div>' +
        '<div class="rp-ph-sub">' + esc(res.name || '') + ' · ' + fmtSize(res.size) + '</div></div>';
    }
  }

  function showLocalPreview(res) {
    S.rpMode = 'preview';
    S.previewPath = '';
    S.previewData = null;
    S.editMode = false;
    S.mdDirty = false;
    S.mdDraft = null;
    setPreviewHead(res);
    $('#rpPreviewOpen').hidden = true;
    renderPreview(res);
    updatePreviewButtons();
    markTreeActive();
  }

  async function previewDropped(fileList) {
    const files = Array.prototype.slice.call(fileList || []);
    if (!files.length) return;
    const file = files[0];
    const name = file.name || '文件';
    const ext = name.split('.').pop().toLowerCase();
    if ((file.type || '').indexOf('image/') === 0) {
      const url = await readAsDataUrl(file);
      showLocalPreview({ kind: 'image', name: name, data_url: url });
    } else if (ext === 'html' || ext === 'htm') {
      const text = await readAsText(file);
      showLocalPreview({ kind: 'html', name: name, content: text.slice(0, 200000) });
    } else if (TEXT_EXT.indexOf(ext) >= 0) {
      const text = await readAsText(file);
      showLocalPreview({
        kind: (ext === 'md' || ext === 'markdown') ? 'markdown' : 'text',
        name: name,
        content: text.slice(0, 200000),
      });
    } else {
      toast('暂不支持预览该类型');
    }
  }

  /* ---------------- 图片灯箱 ---------------- */
  function openLightbox(src) {
    if (!src) return;
    S.embedSuppress = true;
    syncEmbeds();
    $('#lightboxImg').src = src;
    $('#lightbox').hidden = false;
  }

  function closeLightbox() {
    $('#lightbox').hidden = true;
    $('#lightboxImg').src = '';
    S.embedSuppress = false;
    syncEmbeds();
  }

  /* ---------------- 视图 ---------------- */
  function switchView(view) {
    S.view = view;
    ['chat', 'history', 'settings'].forEach(function (v) {
      const el = $('#view' + v.charAt(0).toUpperCase() + v.slice(1));
      if (el) el.hidden = v !== view;
    });
    Array.prototype.slice.call(document.querySelectorAll('.nav-item[data-view]')).forEach(function (b) {
      b.classList.toggle('active', b.dataset.view === view);
    });
    const skillsBtn = $('#skillsNavBtn');
    if (skillsBtn) skillsBtn.classList.remove('active');
    renderTitle();
    $('#newChatTopBtn').style.visibility = view === 'chat' ? 'visible' : 'hidden';
    if (view === 'history') loadHistory(S.histKind);
    if (view === 'settings') {
      loadSettings();
      refreshPerfStats(true);
      showSettingsPage(S.settingsPage || 'groupAccount');
    }
    if (view === 'chat') setTimeout(function () { $('#input').focus(); }, 30);
  }

  function renderTitle() {
    const text = S.view === 'chat' ? (S.sessionTitle === '新对话' ? T('新对话') : S.sessionTitle)
      : (S.view === 'history' ? T('历史') : T('设置'));
    $('#viewTitle').textContent = text || T('新对话');
  }

  function playWinAnim() {
    const app = document.querySelector('.app');
    if (!app) return;
    app.classList.remove('win-anim');
    void app.offsetWidth;
    app.classList.add('win-anim');
    setTimeout(function () { app.classList.remove('win-anim'); }, 240);
  }

  function newChat() {
    if (S.streaming) call('stop');
    S.sessionId = null;
    S.sessionTitle = '新对话';
    S.lastUserText = '';
    setActiveSkill(null);
    clearMessages();
    renderTodo([]);
    renderTitle();
    S.compressing = false;
    applyContextStats({ used: 0, limit: contextLimitValue(), percent: 0, summarized: false });
    switchView('chat');
    loadSideSessions();
    toast('已开始新对话');
  }

  function clearChat() {
    if (S.streaming) call('stop');
    clearMessages();
    renderTodo([]);
    toast('已清空界面');
  }

  /* ---------------- 侧栏 ---------------- */
  function relativeTime(text) {
    const raw = String(text || '').trim();
    if (!raw) return '';
    const t = new Date(raw.replace(' ', 'T'));
    if (isNaN(t.getTime())) return raw.slice(0, 10);
    const diff = Date.now() - t.getTime();
    if (diff < 60 * 1000) return T('刚刚');
    if (diff < 3600 * 1000) return TF('{n} 分钟', { n: Math.floor(diff / 60000) });
    if (diff < 24 * 3600 * 1000) return TF('{n} 小时', { n: Math.floor(diff / 3600000) });
    if (diff < 7 * 24 * 3600 * 1000) return TF('{n} 天', { n: Math.floor(diff / 86400000) });
    return raw.slice(0, 10);
  }

  async function loadSideSessions() {
    const res = await call('history_list', { kind: 'sessions', limit: 14 });
    if (!res || !res.ok) return;
    S.sideSessions = res.items || [];
    S.sideLoaded = true;
    renderSideSessions();
  }

  function renderSideSessions() {
    const box = $('#sideSessions');
    if (!box) return;
    if (!S.sideSessions.length) {
      box.innerHTML = '<div class="side-empty">' + T('还没有对话') + '</div>';
      return;
    }
    box.innerHTML = '';
    S.sideSessions.forEach(function (it) {
      const row = document.createElement('div');
      row.className = 'side-item' + (String(it.id) === String(S.sessionId) ? ' active' : '');
      row.innerHTML =
        '<span class="side-item-title">' + esc(it.title || T('新对话')) + '</span>' +
        '<span class="side-item-time">' + esc(relativeTime(it.updated_at)) + '</span>' +
        '<button class="side-item-del" title="' + esc(T('删除')) + '">×</button>';
      row.addEventListener('click', function (e) {
        if (e.target.closest('.side-item-del')) return;
        if (String(it.id) === String(S.sessionId) && S.view === 'chat') return;
        openSession(it.id);
        if (window.innerWidth < 900) setSidebar(true);
      });
      row.querySelector('.side-item-del').addEventListener('click', async function (e) {
        e.stopPropagation();
        await call('history_delete', { id: it.id });
        if (String(it.id) === String(S.sessionId)) newChat();
        loadSideSessions();
      });
      box.appendChild(row);
    });
  }

  function setSidebar(collapsed, transient) {
    const app = $('#app');
    app.classList.toggle('collapsed', !!collapsed);
    if (!transient) {
      try { localStorage.setItem('nexus.sidebar', collapsed ? 'collapsed' : 'expanded'); } catch (e) { /* ignore */ }
    }
    // 展开左栏时若放不下对话区最小宽度，就收起右栏
    if (!collapsed && window.innerWidth <= 1100 && S.rightOpen) closeRightPanel();
  }

  function toggleSidebar() {
    setSidebar(!$('#app').classList.contains('collapsed'));
  }

  /* ---------------- 历史 ---------------- */
  async function loadHistory(kind) {
    S.histKind = kind;
    Array.prototype.slice.call(document.querySelectorAll('#histTabs .seg-btn')).forEach(function (b) {
      b.classList.toggle('active', b.dataset.kind === kind);
    });
    const list = $('#historyList');
    list.innerHTML = '<div class="hist-empty">' + T('加载中…') + '</div>';
    const res = kind === 'schedules'
      ? await call('schedule_list')
      : await call('history_list', { kind: kind, limit: 40 });
    if (!res || !res.ok) { list.innerHTML = '<div class="hist-empty">' + T('加载失败') + '</div>'; return; }
    const items = res.items || [];
    if (!items.length) {
      list.innerHTML = '<div class="hist-empty">' + T('还没有记录') + '</div>';
      return;
    }
    list.innerHTML = '';
    items.forEach(function (it) {
      const row = document.createElement('div');
      row.className = 'hist-item';
      if (kind === 'sessions') {
        row.innerHTML = '<button class="hist-del" title="' + esc(T('删除')) + '">×</button>' +
          '<div class="hist-title">' + esc(it.title || T('新对话')) + '</div>' +
          '<div class="hist-sub"><span>' + esc(it.updated_at || '') + '</span><span>' + (it.msg_count || 0) + ' ' + T('条消息') + '</span></div>';
        row.querySelector('.hist-del').addEventListener('click', async function (e) {
          e.stopPropagation();
          await call('history_delete', { id: it.id });
          if (String(it.id) === String(S.sessionId)) newChat();
          loadHistory('sessions');
          loadSideSessions();
        });
        row.addEventListener('click', function () { openSession(it.id); });
      } else if (kind === 'files') {
        row.innerHTML = '<div class="hist-title">' + esc(it.name || it.path) + '</div>' +
          '<div class="hist-sub"><span>' + esc(it.created_at || '') + '</span><span>' + fmtSize(it.size) + '</span></div>' +
          '<div class="hist-sub"><span style="direction:rtl;text-align:left;overflow:hidden;text-overflow:ellipsis;">' + esc(it.path || '') + '</span></div>';
        row.addEventListener('click', function () { previewFile(it.path); });
      } else if (kind === 'tools') {
        row.innerHTML = '<div class="hist-title">' + esc(toolLabel(it.tool)) +
          ' <span style="color:' + (it.ok ? 'var(--success)' : 'var(--error)') + ';font-size:11px;">' + (it.ok ? T('成功') : T('失败')) + '</span></div>' +
          '<div class="hist-sub"><span>' + esc(it.created_at || '') + '</span><span>' + (it.ms || 0) + 'ms</span></div>' +
          '<div class="hist-sub"><span>' + esc((it.summary || '').slice(0, 80)) + '</span></div>';
      } else if (kind === 'schedules') {
        const once = !!it.once;
        const when = once
          ? (it.enabled ? TF('延时任务 · 下次 {time}', { time: it.next_run || '' }) : T('已完成'))
          : TF('每 {n} 分钟', { n: it.interval_minutes || 0 });
        const moment = once
          ? (it.enabled ? T('一次性') : TF('执行于 {time}', { time: it.last_run || '—' }))
          : TF('下次 {time}', { time: it.next_run || '—' });
        row.innerHTML = '<button class="hist-del" title="' + esc(T('删除')) + '">×</button>' +
          (once ? '' : '<button class="mini-btn hist-toggle" style="float:right;margin-left:4px;">' +
            (it.enabled ? T('暂停') : T('启用')) + '</button>') +
          '<div class="hist-title">' + esc(it.title || T('定时任务')) + '</div>' +
          '<div class="hist-sub"><span>' + esc(when) + '</span>' +
          '<span>' + esc(moment) + '</span></div>' +
          '<div class="hist-sub"><span>' + esc((it.prompt || '').slice(0, 90)) + '</span></div>' +
          '<div class="hist-sub"><span>' + esc((it.last_result || T('尚未运行')).slice(0, 90)) + '</span></div>';
        row.querySelector('.hist-del').addEventListener('click', async function (e) {
          e.stopPropagation();
          await call('schedule_delete', { id: it.id });
          loadHistory('schedules');
        });
        const toggle = row.querySelector('.hist-toggle');
        if (toggle) {
          toggle.addEventListener('click', async function (e) {
            e.stopPropagation();
            await call('schedule_toggle', { id: it.id, enabled: !it.enabled });
            loadHistory('schedules');
          });
        }
      }
      list.appendChild(row);
    });
  }

  async function openSession(id) {
    const res = await call('history_get', { id: id });
    if (!res || !res.ok) { toast(res && res.error ? res.error : '打开失败'); return; }
    clearMessages();
    S.sessionId = res.session.id;
    S.sessionTitle = res.session.title || '新对话';
    S.lastUserText = '';
    (res.messages || []).forEach(function (m) {
      if (m.role === 'user') {
        const skillName = m.meta && m.meta.skill_name;
        addUser(m.content || '', [], skillName ? { name: skillName } : null);
        S.lastUserText = m.content || S.lastUserText;
      } else if (m.role === 'assistant') {
        const calls = m.meta && m.meta.tool_calls;
        if (!m.content && !(calls && calls.length)) return;
        const item = ensureAssistant(null);
        item.raw = m.content || '';
        item.md.innerHTML = renderMarkdown(item.raw);
        if (item.tok) item.tok.textContent = '~' + estTokens(item.raw) + ' tok';
        if (calls && calls.length) {
          const note = document.createElement('div');
          note.className = 'tool-restored';
          note.textContent = '调用工具：' + calls.join('、');
          item.wrap.querySelector('.msg-main').appendChild(note);
        }
        S.current = null;
      } else if (m.role === 'tool') {
        const item = ensureAssistant(null);
        item.raw = '';
        item.md.innerHTML = '';
        const note = document.createElement('div');
        note.className = 'tool-restored';
        note.textContent = '工具结果：' + String(m.content || '').replace(/\s+/g, ' ').slice(0, 160);
        item.wrap.querySelector('.msg-main').appendChild(note);
        S.current = null;
      }
    });
    // 历史会话不再回放所有产出文件卡片（那是持久记录，容易和“本轮改动”混淆）；
    // 文件仍可在历史页和右侧文件面板里查看。
    switchView('chat');
    renderTitle();
    loadSideSessions();
    S.compressing = false;
    setCompressStatus('', '');
    refreshContextStats(res.session.id);
    scrollBottom(true);
  }

  function fmtSize(size) {
    const n = Number(size) || 0;
    if (n < 1024) return n + ' B';
    if (n < 1024 * 1024) return (n / 1024).toFixed(1) + ' KB';
    return (n / 1024 / 1024).toFixed(1) + ' MB';
  }

  // 文件树里的紧凑尺寸，给文件名多留点宽度
  function fmtSizeShort(size) {
    const n = Number(size) || 0;
    if (n < 1024) return n + ' B';
    if (n < 1024 * 1024) return Math.round(n / 1024) + 'K';
    return (n / 1024 / 1024).toFixed(1) + 'M';
  }

  /* ---------------- 设置 ---------------- */
  function paintAvatar(el, data, custom) {
    if (!el) return;
    if (custom && data) {
      el.classList.add('has-image');
      el.style.backgroundImage = 'url("' + data + '")';
    } else {
      el.classList.remove('has-image');
      el.style.backgroundImage = '';
    }
  }

  function applyAssistantName(name) {
    S.assistantName = String(name || '').trim() || 'Nexus';
    const avatar = $('#modeAvatar');
    if (avatar) avatar.title = S.assistantName;
    renderAssistantGreeting();
  }

  function renderAssistantGreeting() {
    const el = $('#emptyGreeting');
    if (el) el.textContent = TF('我是{name}，有什么可以帮你？', { name: S.assistantName || 'Nexus' });
  }

  function applyProfile(profile) {
    if (!profile) return;
    S.profile = {
      name: profile.name || '',
      avatar: profile.avatar === 'custom' ? 'custom' : 'default',
      color: profile.color || 'blue',
      avatarData: profile.avatar_data || '',
    };
    S.profileDraft = {
      name: S.profile.name,
      avatar: S.profile.avatar,
      color: S.profile.color,
      avatarData: '',
    };
    const custom = S.profile.avatar === 'custom' && !!S.profile.avatarData;
    paintAvatar($('#modeAvatar'), S.profile.avatarData, custom);
    paintAvatar($('#profilePreview'), S.profile.avatarData, custom);
    const nameInput = $('#setProfileName');
    if (nameInput && document.activeElement !== nameInput) nameInput.value = S.profile.name;
    const identity = $('#profileIdentity');
    if (identity) {
      identity.textContent = S.profile.name
        ? T('本地用户') + ' · ' + S.profile.name
        : T('本地用户');
    }
  }

  function setAccent(accent) {
    S.accent = accent || 'blue';
    document.documentElement.setAttribute('data-accent', S.accent);
    Array.prototype.slice.call(document.querySelectorAll('#accentPicker .color-choice')).forEach(function (btn) {
      btn.classList.toggle('active', btn.dataset.color === S.accent);
    });
  }

  function applyState(st) {
    if (!st) return;
    S.settings = st.settings || S.settings;
    S.scenes = st.scenes || S.scenes;
    const s = st.settings || {};
    if (st.language && window.NexusI18n) window.NexusI18n.setLang(st.language);
    if (st.assistant_name || s.assistant_name) applyAssistantName(st.assistant_name || s.assistant_name);
    if (st.accent || s.accent) setAccent(st.accent || s.accent);
    if (st.profile || s.profile) applyProfile(st.profile || s.profile);
    if (st.theme || s.theme) setTheme(st.theme || s.theme);
    if (st.mode || s.mode) setMode(st.mode || s.mode);
    if (st.version) $('#aboutVersion').textContent = 'v' + st.version;
    if (st.data_dir) $('#aboutData').textContent = st.data_dir;
    if (s.update_info && s.update_info.has_update) showUpdate(s.update_info);
    if (st.scenes) renderScenes(st.scenes);
    if (st.settings) syncModelMenu();
    if (st.settings && S.view === 'settings') loadSettings(st.settings);
  }

  const MODE_META = {
    safe: { badge: '安全', side: '安全模式', color: 'var(--success)', cls: 'safe' },
    supervised: { badge: '监管', side: '监管模式', color: 'var(--accent)', cls: 'supervised' },
    full: { badge: '下放', side: '全部下放', color: 'var(--warn)', cls: 'full' },
  };

  function setMode(mode) {
    if (mode === 'online' || mode === 'pro') mode = 'supervised';
    const meta = MODE_META[mode] || MODE_META.supervised;
    const badge = $('#modeBadge');
    if (badge) {
      badge.className = 'badge ' + meta.cls;
      badge.dataset.i18n = meta.badge;
      badge.textContent = T(meta.badge);
    }
    const sideText = $('#sideModeBtn .side-mode-text');
    if (sideText) {
      sideText.dataset.i18n = meta.side;
      sideText.textContent = T(meta.side);
    }
    const dot = $('#sideModeBtn .side-mode-dot');
    if (dot) dot.style.background = meta.color;
  }

  function loadSettings(st) {
    const data = st || S.settings || {};
    if (!data || (!data.base_url && !data.model && !data.context_limit)) {
      call('settings_get').then(function (res) {
        if (res) loadSettings(res);
      });
      return;
    }
    S.settings = data;
    if ($('#setThinking')) {
      const think = String(data.thinking || 'auto').toLowerCase();
      $('#setThinking').value = ['auto', 'enabled', 'disabled'].indexOf(think) >= 0 ? think : 'auto';
    }
    if ($('#setEffort')) $('#setEffort').value = data.reasoning_effort || 'high';
    if ($('#setTimeout')) $('#setTimeout').value = data.timeout || 90;
    if ($('#setMaxTokens')) $('#setMaxTokens').value = Number(data.max_tokens) >= 98304 ? '131072' : '65536';
    if ($('#setAssistantName')) $('#setAssistantName').value = data.assistant_name || 'Nexus';
    if ($('#setOut')) $('#setOut').value = data.output_dir || '';
    if ($('#setTheme')) $('#setTheme').value = data.theme || 'light';
    if ($('#setHotkey')) $('#setHotkey').value = data.hotkey || 'ctrl+alt+space';
    if ($('#setVoiceHotkey')) $('#setVoiceHotkey').value = data.voice_hotkey || 'ctrl+alt+v';
    if ($('#setAutostart')) $('#setAutostart').checked = !!data.autostart;
    if ($('#setMode')) $('#setMode').value = data.mode || 'supervised';
    if ($('#setNotifyDone')) $('#setNotifyDone').checked = data.notify_done !== false;
    if ($('#setShowApiErrors')) $('#setShowApiErrors').checked = data.show_api_errors !== false;
    if ($('#setContextCompress')) $('#setContextCompress').checked = data.context_compress !== false;
    if ($('#setUpdateRepo')) $('#setUpdateRepo').value = data.update_repo || '';
    if ($('#setUpdateBase')) $('#setUpdateBase').value = data.update_base_url || '';
    if ($('#setUpdateAuto')) $('#setUpdateAuto').checked = data.update_auto_check !== false;
    if ($('#setSkillsAuto')) $('#setSkillsAuto').checked = data.skills_auto !== false;
    if ($('#setMemoryEnabled')) $('#setMemoryEnabled').checked = data.memory_enabled !== false;
    if ($('#setLanguage')) $('#setLanguage').value = data.language || 'zh';
    if (data.profile) applyProfile(data.profile);
    const limit = Number(data.context_limit || 131072) >= 600000 ? 1048576 : 131072;
    S.contextLimit = limit;
    if ($('#setContextPreset')) $('#setContextPreset').value = String(limit);
    if (data.accent) setAccent(data.accent);
    renderProviderGrid();
    syncModelMenu();
    if (S.sessionId) refreshContextStats();
    else { S.contextTokens = 0; S.contextPercent = 0; updateContextUsage(); updateStatusBar(); }
    refreshVoiceStatus();
  }

  /* ---------------- 技能 ---------------- */
  function setActiveSkill(skill) {
    S.activeSkill = skill ? { id: skill.id, name: skill.name } : null;
    renderSkillBar();
  }

  function renderSkillBar() {
    const bar = $('#skillBar');
    if (!bar) return;
    if (!S.activeSkill) {
      bar.hidden = true;
      bar.innerHTML = '';
      return;
    }
    bar.hidden = false;
    bar.innerHTML = '<span class="skill-chip"><b>' + esc(S.activeSkill.name) +
      '</b><button type="button" id="skillChipClear" data-i18n-title="移除技能" title="移除技能" aria-label="移除技能">×</button></span>';
    const clear = $('#skillChipClear');
    if (clear) clear.addEventListener('click', function () { setActiveSkill(null); });
  }

  function renderPlusSkills() {
    const box = $('#plusSkillList');
    if (!box) return;
    const skills = (S.skills || []).filter(function (s) { return s.enabled; });
    const title = $('#plusSkillTitle');
    const sep = $('#plusSkillSep');
    if (title) title.hidden = !skills.length;
    if (sep) sep.hidden = !skills.length;
    if (!skills.length) {
      box.innerHTML = '';
      return;
    }
    const active = S.activeSkill ? S.activeSkill.id : '';
    box.innerHTML = skills.map(function (s) {
      return '<button class="menu-row" data-skill="' + esc(s.id) + '"' +
        (s.id === active ? ' data-selected="1"' : '') +
        ' title="' + esc(s.description || s.when_to_use || s.name) + '">' +
        '<span class="trig-icon">✦</span><span>' + esc(s.name) + '</span>' +
        '<b class="menu-check"></b>' +
        '</button>';
    }).join('');
    Array.prototype.slice.call(box.querySelectorAll('.menu-row')).forEach(function (row) {
      row.addEventListener('click', function () {
        const id = row.dataset.skill;
        let picked = null;
        for (let i = 0; i < skills.length; i++) {
          if (skills[i].id === id) { picked = skills[i]; break; }
        }
        closeMenus();
        if (!picked) return;
        setActiveSkill(picked);
        toast(TF('已选择技能：{name}', { name: picked.name }));
        $('#input').focus();
      });
    });
  }

  async function loadSkills() {
    const res = await call('skills', 'list');
    if (res && res.ok) S.skills = res.items || [];
    if (res && res.dir) S.skillsDir = res.dir;
    renderSkills();
    renderPlusSkills();
  }

  function skillSourceLabel(skill) {
    return skill.source === 'builtin' ? T('内置') : T('我的');
  }

  function renderSkills() {
    const box = $('#skillList');
    if (!box) return;
    const count = $('#skillCount');
    if (count) count.textContent = S.skills.length ? String(S.skills.length) : '';
    if (!S.skills.length) {
      box.innerHTML = '<div class="skill-empty">' + T('还没有技能。新建一个，或把 SKILL.md 放进技能目录。') + '</div>';
      return;
    }
    box.innerHTML = S.skills.map(function (s) {
      const desc = s.description || s.when_to_use || '';
      const when = s.when_to_use && s.description ? s.when_to_use : '';
      return '<div class="skill-card" data-id="' + esc(s.id) + '">' +
        '<div class="skill-head">' +
          '<span class="skill-name">' + esc(s.name) + '</span>' +
          '<span class="skill-src">' + esc(skillSourceLabel(s)) + '</span>' +
          '<div class="skill-actions">' +
            '<label class="skill-toggle"><input type="checkbox" data-act="toggle"' +
              (s.enabled ? ' checked' : '') + '><i></i></label>' +
            '<button class="icon-btn" data-act="edit" title="' + T('编辑') + '" aria-label="' + T('编辑') + '">✎</button>' +
            (s.source === 'user'
              ? '<button class="icon-btn" data-act="delete" title="' + T('删除') + '" aria-label="' + T('删除') + '">×</button>'
              : '') +
          '</div>' +
        '</div>' +
        (desc ? '<p class="skill-desc">' + esc(desc) + '</p>' : '') +
        (when ? '<p class="skill-when">' + T('什么时候用：') + esc(when) + '</p>' : '') +
      '</div>';
    }).join('');
    Array.prototype.slice.call(box.querySelectorAll('[data-act]')).forEach(function (el) {
      el.addEventListener('change', function () {
        if (el.dataset.act !== 'toggle') return;
        toggleSkill(el.closest('.skill-card').dataset.id, el.checked);
      });
      el.addEventListener('click', function (e) {
        const card = el.closest('.skill-card');
        if (!card) return;
        const id = card.dataset.id;
        if (el.dataset.act === 'edit') {
          e.preventDefault();
          openSkillEditor(S.skills.filter(function (s) { return s.id === id; })[0]);
        } else if (el.dataset.act === 'delete') {
          e.preventDefault();
          deleteSkill(id);
        }
      });
    });
  }

  function openSkillEditor(skill) {
    S.editingSkill = skill || null;
    $('#skillModalTitle').textContent = skill ? T('编辑技能') : T('新建技能');
    $('#skillName').value = skill ? skill.name : '';
    $('#skillDesc').value = skill ? (skill.description || '') : '';
    $('#skillWhen').value = skill ? (skill.when_to_use || '') : '';
    $('#skillBody').value = skill ? (skill.body || '') : '';
    $('#skillEnabled').checked = skill ? !!skill.enabled : true;
    $('#skillMask').hidden = false;
    setTimeout(function () { $('#skillName').focus(); }, 30);
  }

  function closeSkillEditor() {
    $('#skillMask').hidden = true;
    S.editingSkill = null;
  }

  async function saveSkillEditor() {
    const name = ($('#skillName').value || '').trim();
    const body = ($('#skillBody').value || '').trim();
    if (!body) { toast(T('请填写提示词正文')); return; }
    const payload = {
      name: name,
      description: ($('#skillDesc').value || '').trim(),
      when_to_use: ($('#skillWhen').value || '').trim(),
      body: body,
      enabled: $('#skillEnabled').checked,
    };
    if (S.editingSkill) payload.id = S.editingSkill.id;
    const res = await call('skills', 'save', payload);
    if (!res || !res.ok) { toast((res && res.error) || T('保存失败')); return; }
    closeSkillEditor();
    await loadSkills();
    const saved = res.skill && res.skill.name;
    toast(!name && saved ? TF('已按内容命名为：{name}', { name: saved }) : T('技能已保存'));
  }

  async function toggleSkill(id, enabled) {
    const res = await call('skills', 'toggle', { id: id, enabled: enabled });
    if (!res || !res.ok) { toast((res && res.error) || T('操作失败')); }
    await loadSkills();
  }

  async function deleteSkill(id) {
    const skill = S.skills.filter(function (s) { return s.id === id; })[0];
    const name = skill ? skill.name : id;
    if (!window.confirm(TF('删除技能「{name}」？此操作不可撤销。', { name: name }))) return;
    const res = await call('skills', 'delete', { id: id });
    if (!res || !res.ok) { toast((res && res.error) || T('删除失败')); return; }
    if (S.activeSkill && S.activeSkill.id === id) setActiveSkill(null);
    await loadSkills();
    toast(T('技能已删除'));
  }

  /* ---------------- 系统提示词 ---------------- */
  async function loadPrompts() {
    const res = await call('prompts', 'list');
    if (res && res.ok) S.prompts = res.items || [];
    if (res && res.dir) S.promptsDir = res.dir;
    renderPrompts();
  }

  function renderPrompts() {
    const box = $('#promptList');
    if (!box) return;
    const count = $('#promptCount');
    if (count) count.textContent = S.prompts.length ? String(S.prompts.length) : '';
    if (!S.prompts.length) {
      box.innerHTML = '<div class="prompt-empty">' + T('还没有系统提示词。新建一条，写清你希望模型长期遵守的规则。') + '</div>';
      return;
    }
    box.innerHTML = S.prompts.map(function (item) {
      const body = String(item.body || '');
      const excerpt = body.split(/\r?\n/).filter(function (line) {
        return line.trim() && !/^#+\s*/.test(line.trim());
      }).join(' ').replace(/[*`>_~\[\]]/g, '').trim().slice(0, 160);
      const stamp = String(item.updated || '').slice(0, 10);
      return '<div class="prompt-card" data-id="' + esc(item.id) + '">' +
        '<div class="prompt-head">' +
          '<span class="prompt-name">' + esc(item.name) + '</span>' +
          (stamp ? '<span class="prompt-time">' + esc(stamp) + '</span>' : '') +
          '<div class="skill-actions">' +
            '<label class="skill-toggle"><input type="checkbox" data-act="toggle"' +
              (item.enabled ? ' checked' : '') + '><i></i></label>' +
            '<button class="icon-btn" data-act="edit" title="' + T('编辑') + '" aria-label="' + T('编辑') + '">✎</button>' +
            '<button class="icon-btn" data-act="delete" title="' + T('删除') + '" aria-label="' + T('删除') + '">×</button>' +
          '</div>' +
        '</div>' +
        (excerpt ? '<p class="prompt-excerpt">' + esc(excerpt) + '</p>' : '') +
      '</div>';
    }).join('');
    Array.prototype.slice.call(box.querySelectorAll('[data-act]')).forEach(function (el) {
      el.addEventListener('change', function () {
        if (el.dataset.act !== 'toggle') return;
        togglePrompt(el.closest('.prompt-card').dataset.id, el.checked);
      });
      el.addEventListener('click', function (e) {
        const card = el.closest('.prompt-card');
        if (!card) return;
        const id = card.dataset.id;
        if (el.dataset.act === 'edit') {
          e.preventDefault();
          openPromptEditor(S.prompts.filter(function (i) { return i.id === id; })[0]);
        } else if (el.dataset.act === 'delete') {
          e.preventDefault();
          deletePrompt(id);
        }
      });
    });
  }

  function updatePromptPreview() {
    const preview = $('#promptPreview');
    if (!preview) return;
    const body = $('#promptBody').value || '';
    preview.innerHTML = body.trim()
      ? renderMarkdown(body)
      : '<p style="color:var(--text-3)">' + T('左侧输入 Markdown，这里实时预览。') + '</p>';
  }

  function openPromptEditor(item) {
    S.editingPrompt = item || null;
    $('#promptModalTitle').textContent = item ? T('编辑系统提示词') : T('新建系统提示词');
    $('#promptName').value = item ? item.name : '';
    $('#promptEnabled').checked = item ? !!item.enabled : true;
    $('#promptBody').value = item ? (item.body || '') : '';
    updatePromptPreview();
    $('#promptMask').hidden = false;
    setTimeout(function () { $('#promptName').focus(); }, 30);
  }

  function closePromptEditor() {
    $('#promptMask').hidden = true;
    S.editingPrompt = null;
  }

  async function savePromptEditor() {
    const name = ($('#promptName').value || '').trim();
    const body = ($('#promptBody').value || '').trim();
    if (!body) { toast(T('提示词正文不能为空')); return; }
    const payload = {
      name: name,
      body: body,
      enabled: $('#promptEnabled').checked,
    };
    if (S.editingPrompt) payload.id = S.editingPrompt.id;
    const res = await call('prompts', 'save', payload);
    if (!res || !res.ok) { toast((res && res.error) || T('保存失败')); return; }
    closePromptEditor();
    await loadPrompts();
    const saved = res.prompt && res.prompt.name;
    toast(!name && saved ? TF('已按内容命名为：{name}', { name: saved }) : T('系统提示词已保存'));
  }

  async function togglePrompt(id, enabled) {
    const res = await call('prompts', 'toggle', { id: id, enabled: enabled });
    if (!res || !res.ok) toast((res && res.error) || T('操作失败'));
    await loadPrompts();
  }

  async function deletePrompt(id) {
    const item = S.prompts.filter(function (i) { return i.id === id; })[0];
    const name = item ? item.name : id;
    if (!window.confirm(TF('删除系统提示词「{name}」？此操作不可撤销。', { name: name }))) return;
    const res = await call('prompts', 'delete', { id: id });
    if (!res || !res.ok) { toast((res && res.error) || T('删除失败')); return; }
    await loadPrompts();
    toast(T('系统提示词已删除'));
  }

  /* ---------------- 记忆 ---------------- */
  function memoryCategoryLabel(cat) {
    if (cat === 'habit') return T('习惯');
    if (cat === 'fact') return T('事实');
    return T('偏好');
  }

  async function loadMemory() {
    const res = await call('memory', 'list');
    if (res && res.ok) S.memories = res.items || [];
    renderMemory();
  }

  function renderMemory() {
    const box = $('#memoryList');
    if (!box) return;
    if (!S.memories.length) {
      box.innerHTML = '<div class="memory-empty">' + T('还没有记忆。模型会在你表达偏好时自动记下，也可以在这里手动添加。') + '</div>';
      return;
    }
    box.innerHTML = S.memories.map(function (m) {
      return '<div class="memory-item" data-id="' + esc(m.id) + '">' +
        '<span class="memory-cat">' + esc(memoryCategoryLabel(m.category)) + '</span>' +
        '<span class="memory-text">' + esc(m.text) + '</span>' +
        '<span class="memory-actions">' +
          '<button class="icon-btn" data-act="edit" title="' + T('编辑') + '" aria-label="' + T('编辑') + '">✎</button>' +
          '<button class="icon-btn" data-act="delete" title="' + T('删除') + '" aria-label="' + T('删除') + '">×</button>' +
        '</span>' +
      '</div>';
    }).join('');
    Array.prototype.slice.call(box.querySelectorAll('[data-act]')).forEach(function (el) {
      el.addEventListener('click', function () {
        const row = el.closest('.memory-item');
        if (!row) return;
        const item = S.memories.filter(function (m) { return String(m.id) === row.dataset.id; })[0];
        if (!item) return;
        if (el.dataset.act === 'edit') openMemoryEditor(item);
        else deleteMemoryItem(item.id);
      });
    });
  }

  function openMemoryEditor(item) {
    S.editingMemory = item || null;
    $('#memoryEditText').value = item ? item.text : '';
    $('#memoryEditCategory').value = item ? (item.category || 'preference') : 'preference';
    $('#memoryEditDelete').hidden = !item;
    $('#memoryMask').hidden = false;
    setTimeout(function () { $('#memoryEditText').focus(); }, 30);
  }

  function closeMemoryEditor() {
    $('#memoryMask').hidden = true;
    S.editingMemory = null;
  }

  async function saveMemoryEditor() {
    const text = ($('#memoryEditText').value || '').trim();
    if (!text) { toast(T('记忆内容不能为空')); return; }
    const category = $('#memoryEditCategory').value;
    const res = S.editingMemory
      ? await call('memory', 'update', { id: S.editingMemory.id, text: text, category: category })
      : await call('memory', 'add', { text: text, category: category });
    if (!res || !res.ok) { toast((res && res.error) || T('保存失败')); return; }
    S.memories = res.items || S.memories;
    closeMemoryEditor();
    renderMemory();
    toast(T('记忆已保存'));
  }

  async function addMemory() {
    const input = $('#memoryInput');
    const text = (input.value || '').trim();
    if (!text) { toast(T('先写一句要记住的内容')); return; }
    const res = await call('memory', 'add', { text: text, category: $('#memoryCategory').value });
    if (!res || !res.ok) { toast((res && res.error) || T('添加失败')); return; }
    input.value = '';
    S.memories = res.items || [];
    renderMemory();
    toast(T('已添加'));
  }

  async function deleteMemoryItem(id) {
    if (!window.confirm(T('删除这条记忆？'))) return;
    const res = await call('memory', 'delete', { id: id });
    if (!res || !res.ok) { toast((res && res.error) || T('删除失败')); return; }
    S.memories = res.items || [];
    renderMemory();
  }

  async function clearMemory() {
    if (!S.memories.length) { toast(T('还没有记忆')); return; }
    if (!window.confirm(T('清空全部长期记忆？此操作不可撤销。'))) return;
    const res = await call('memory', 'clear');
    if (!res || !res.ok) { toast((res && res.error) || T('清空失败')); return; }
    S.memories = [];
    renderMemory();
    toast(T('记忆已清空'));
  }

  /* ---------------- 设置分页与厂商 ---------------- */
  function showSettingsPage(page) {
    const target = page || 'groupAccount';
    const pages = document.querySelectorAll('.settings-page');
    let found = false;
    Array.prototype.slice.call(pages).forEach(function (el) {
      const on = el.dataset.page === target;
      el.hidden = !on;
      if (on) found = true;
    });
    if (!found) return;
    S.settingsPage = target;
    Array.prototype.slice.call(document.querySelectorAll('.settings-nav-item')).forEach(function (btn) {
      const on = btn.dataset.target === target;
      btn.classList.toggle('active', on);
      if (on && btn.scrollIntoView && btn.parentElement &&
          btn.parentElement.scrollWidth > btn.parentElement.clientWidth) {
        btn.scrollIntoView({ inline: 'nearest', block: 'nearest' });
      }
    });
    const box = $('.settings-pages');
    if (box) box.scrollTop = 0;
    if (target === 'groupPerf') refreshPerfStats(true);
    if (target === 'groupModel') renderProviderGrid();
    if (target === 'groupSkills') { loadSkills(); loadPrompts(); }
    if (target === 'groupMemory') loadMemory();
    const skillsBtn = $('#skillsNavBtn');
    if (skillsBtn && target !== 'groupSkills') skillsBtn.classList.remove('active');
  }

  function renderProviderGrid() {
    const grid = $('#providerGrid');
    if (!grid) return;
    const st = S.settings || {};
    const active = st.active_provider || st.provider || '';
    grid.innerHTML = '';
    providerCatalog().forEach(function (info) {
      const state = providerState(info.id);
      const configured = !!state.configured;
      const card = document.createElement('button');
      card.type = 'button';
      card.className = 'provider-card' +
        (configured ? ' configured' : '') +
        (S.settingsProvider === info.id ? ' selected' : '') +
        (active === info.id ? ' active' : '');
      card.style.setProperty('--provider-color', info.color || '#64748b');

      const head = document.createElement('div');
      head.className = 'provider-card-head';
      const mark = document.createElement('span');
      mark.className = 'provider-mark';
      applyProviderMark(mark, info.id);
      const name = document.createElement('span');
      name.className = 'provider-card-name';
      name.textContent = info.id === 'custom' ? (state.name || info.name) : info.name;
      head.appendChild(mark);
      head.appendChild(name);

      const note = document.createElement('div');
      note.className = 'provider-card-note';
      note.textContent = info.id === 'custom'
        ? ((state.base_url || '') || T('OpenAI / Anthropic 兼容接口'))
        : (info.note || '');

      const foot = document.createElement('div');
      foot.className = 'provider-card-foot';
      const status = document.createElement('span');
      status.className = 'provider-state' + (configured ? ' on' : '');
      status.textContent = configured ? T('已配置') : T('未配置');
      foot.appendChild(status);
      if (active === info.id) {
        const current = document.createElement('span');
        current.className = 'provider-current';
        current.textContent = T('当前使用');
        foot.appendChild(current);
      }

      card.appendChild(head);
      card.appendChild(note);
      card.appendChild(foot);
      card.addEventListener('click', function () { openProviderDetail(info.id); });
      grid.appendChild(card);
    });
  }

  function openProviderDetail(id) {
    const info = providerInfo(id);
    if (!info) return;
    const state = providerState(id);
    S.settingsProvider = id;
    const savedModels = (state.models && state.models.length)
      ? state.models.slice()
      : (info.models || []).map(function (m) { return m.id; });
    S.providerDraftModels = savedModels;
    const st = S.settings || {};
    S.providerDraftModel = (st.active_provider === id && st.active_model)
      ? st.active_model
      : (savedModels[0] || '');
    S.providerDraftKind = state.kind || info.kind || 'openai';

    const detail = $('#providerDetail');
    if (!detail) return;
    detail.hidden = false;
    applyProviderMark($('#pdMark'), id);
    if ($('#pdName')) $('#pdName').textContent = id === 'custom' ? (state.name || info.name) : info.name;
    if ($('#pdKind')) $('#pdKind').textContent = S.providerDraftKind === 'anthropic' ? 'Anthropic' : 'OpenAI';
    if ($('#pdBase')) $('#pdBase').value = state.base_url || info.base_url || '';
    if ($('#pdKey')) $('#pdKey').value = '';
    if ($('#pdStatus')) { $('#pdStatus').className = 'field-status'; $('#pdStatus').textContent = ''; }
    const customFields = $('#pdCustomFields');
    if (customFields) customFields.hidden = id !== 'custom';
    if (id === 'custom') {
      if ($('#pdDisplayName')) $('#pdDisplayName').value = state.name || '';
      Array.prototype.slice.call(document.querySelectorAll('#pdKindSeg .seg-btn')).forEach(function (btn) {
        btn.classList.toggle('active', btn.dataset.kind === S.providerDraftKind);
      });
    }
    const docs = $('#pdDocs');
    if (docs) {
      const links = [];
      if (info.docs_url) {
        links.push('<a class="link" href="' + esc(info.docs_url) + '" target="_blank" rel="noreferrer">' + esc(T('厂商文档')) + '</a>');
      }
      if (info.key_url) {
        links.push('<a class="link" href="' + esc(info.key_url) + '" target="_blank" rel="noreferrer">' + esc(T('获取 API Key')) + '</a>');
      }
      docs.innerHTML = links.join(' · ');
    }
    renderProviderModels();
    renderProviderGrid();
    if (detail.scrollIntoView) detail.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }

  function renderProviderModels() {
    const box = $('#pdModels');
    if (!box) return;
    box.innerHTML = '';
    if (!S.providerDraftModels.length) {
      box.innerHTML = '<span class="hint">' + esc(T('还没有模型，点「刷新可用模型」或手动添加')) + '</span>';
      return;
    }
    S.providerDraftModels.forEach(function (model) {
      const chip = document.createElement('span');
      chip.className = 'model-chip' + (S.providerDraftModel === model ? ' on' : '');
      const label = document.createElement('span');
      label.textContent = modelLabel(S.settingsProvider, model);
      label.addEventListener('click', function () {
        S.providerDraftModel = model;
        renderProviderModels();
      });
      const del = document.createElement('span');
      del.className = 'chip-x';
      del.textContent = '×';
      del.title = T('移除');
      del.addEventListener('click', function (e) {
        e.stopPropagation();
        S.providerDraftModels = S.providerDraftModels.filter(function (m) { return m !== model; });
        if (S.providerDraftModel === model) S.providerDraftModel = S.providerDraftModels[0] || '';
        renderProviderModels();
      });
      chip.appendChild(label);
      chip.appendChild(del);
      box.appendChild(chip);
    });
  }

  function addProviderModel() {
    const input = $('#pdModelInput');
    if (!input) return;
    const value = input.value.trim();
    if (!value) return;
    if (S.providerDraftModels.indexOf(value) < 0) S.providerDraftModels.push(value);
    if (!S.providerDraftModel) S.providerDraftModel = value;
    input.value = '';
    renderProviderModels();
  }

  async function saveProviderDetail(activate) {
    const id = S.settingsProvider;
    if (!id) return;
    const status = $('#pdStatus');
    const setStatus = function (text, cls) {
      if (!status) return;
      status.className = 'field-status' + (cls ? ' ' + cls : '');
      status.textContent = text || '';
    };
    if (activate && !S.providerDraftModel && S.providerDraftModels.length) {
      S.providerDraftModel = S.providerDraftModels[0];
    }
    const payload = {
      id: id,
      base_url: $('#pdBase') ? $('#pdBase').value.trim() : '',
      models: S.providerDraftModels,
      activate: !!activate,
      model: S.providerDraftModel,
    };
    if (id === 'custom') {
      payload.name = $('#pdDisplayName') ? $('#pdDisplayName').value.trim() : '';
      payload.kind = S.providerDraftKind;
    }
    const key = $('#pdKey') ? $('#pdKey').value.trim() : '';
    if (key) payload.api_key = key;
    setStatus(T('保存中…'), '');
    const res = await call('provider_save', payload);
    if (!res || !res.ok) {
      setStatus((res && res.error) || T('保存失败'), 'fail');
      return false;
    }
    if (res.state) S.settings = res.state;
    if ($('#pdKey')) $('#pdKey').value = '';
    renderProviderGrid();
    renderModelMenu();
    renderProviderModels();
    const state = providerState(id);
    if ($('#pdName') && id === 'custom') $('#pdName').textContent = state.name || '自定义';
    setStatus(activate ? T('已保存并设为当前') : T('已保存'), 'ok');
    toast(activate ? T('已设为当前模型厂商') : T('厂商配置已保存'));
    return true;
  }

  async function testProviderDetail() {
    const id = S.settingsProvider;
    if (!id) return;
    const status = $('#pdStatus');
    if (status) { status.className = 'field-status'; status.textContent = T('测试中…'); }
    const res = await call('provider_test', {
      id: id,
      base_url: $('#pdBase') ? $('#pdBase').value.trim() : '',
      api_key: $('#pdKey') ? $('#pdKey').value.trim() : '',
      model: S.providerDraftModel || S.providerDraftModels[0] || '',
      kind: id === 'custom' ? S.providerDraftKind : providerState(id).kind,
    });
    if (!status) return;
    if (res && res.ok) {
      status.className = 'field-status ok';
      status.textContent = TF('连接正常：{text}', { text: res.text || 'OK' });
    } else {
      status.className = 'field-status fail';
      let detail = '';
      if (res && res.detail && (S.settings.show_api_errors !== false)) {
        detail = ' ' + (res.status ? 'HTTP ' + res.status + ' ' : '') + res.detail;
      }
      status.textContent = ((res && res.error) || T('连接失败')) +
        (res && res.hint ? '（' + res.hint + '）' : '') + detail;
    }
  }

  async function refreshProviderModels() {
    const id = S.settingsProvider;
    if (!id) return;
    const status = $('#pdStatus');
    if (status) { status.className = 'field-status'; status.textContent = T('读取模型列表…'); }
    const res = await call('provider_models', {
      id: id,
      base_url: $('#pdBase') ? $('#pdBase').value.trim() : '',
      api_key: $('#pdKey') ? $('#pdKey').value.trim() : '',
      kind: id === 'custom' ? S.providerDraftKind : providerState(id).kind,
    });
    if (!res || !res.ok) {
      if (status) {
        status.className = 'field-status fail';
        status.textContent = (res && res.error) || T('读取失败');
      }
      return;
    }
    const list = (res.models || []).map(function (m) { return m.id; });
    if (!list.length) {
      if (status) { status.className = 'field-status fail'; status.textContent = T('接口没有返回模型'); }
      return;
    }
    S.providerDraftModels = list;
    if (list.indexOf(S.providerDraftModel) < 0) S.providerDraftModel = list[0];
    renderProviderModels();
    if (status) {
      status.className = 'field-status ok';
      status.textContent = TF('读取到 {n} 个模型，保存后生效', { n: list.length });
    }
  }

  async function clearProviderKey() {
    const id = S.settingsProvider;
    if (!id) return;
    if (!window.confirm(T('确定清除这个厂商的 API Key 吗？'))) return;
    const res = await call('provider_save', { id: id, clear_key: true });
    if (res && res.ok) {
      if (res.state) S.settings = res.state;
      if ($('#pdKey')) $('#pdKey').value = '';
      renderProviderGrid();
      renderModelMenu();
      if ($('#pdStatus')) {
        $('#pdStatus').className = 'field-status ok';
        $('#pdStatus').textContent = T('已清除 Key');
      }
    } else {
      toast((res && res.error) || T('清除失败'));
    }
  }

  function contextLimitValue() {
    const preset = $('#setContextPreset') ? $('#setContextPreset').value : String(S.contextLimit || 131072);
    return parseInt(preset, 10) >= 600000 ? 1048576 : 131072;
  }

  function applyContextStats(res) {
    S.contextTokens = Number(res.used) || 0;
    S.contextLimit = Number(res.limit) || contextLimitValue();
    S.contextPercent = Number(res.percent) || 0;
    S.contextSummarized = !!res.summarized;
    updateContextUsage();
    updateStatusBar();
  }

  async function refreshContextStats(sessionId) {
    const id = sessionId === undefined ? S.sessionId : sessionId;
    if (!id) {
      applyContextStats({ used: 0, limit: contextLimitValue(), percent: 0, summarized: false });
      return;
    }
    const res = await call('context_stats', { session_id: id });
    if (!res || !res.ok) return;
    if (String(id) !== String(S.sessionId)) return;
    applyContextStats(res);
  }

  function updateContextUsage() {
    const text = $('#contextUsageText');
    const pctEl = $('#contextUsagePct');
    const bar = $('#contextUsageBar');
    const limit = S.contextLimit || contextLimitValue();
    const used = S.contextTokens || 0;
    const pct = Math.max(0, Math.min(100, Math.round(used / limit * 1000) / 10));
    if (text) {
      text.textContent = TF('当前约 {used} / {limit} tokens', {
        used: used.toLocaleString(), limit: limit.toLocaleString(),
      });
    }
    if (pctEl) pctEl.textContent = pct + '%';
    if (bar) {
      bar.style.width = Math.min(100, pct) + '%';
      bar.className = 'context-meter-fill' + (pct >= 80 ? ' danger' : (pct >= 50 ? ' warn' : ''));
    }
  }

  function setCompressStatus(text, cls) {
    const el = $('#compressStatus');
    if (!el) return;
    el.className = 'field-status' + (cls ? ' ' + cls : '');
    el.textContent = text || '';
  }

  async function compressNow() {
    if (!S.sessionId) { toast('请先打开一个会话'); return; }
    if (S.streaming || S.compressing) return;
    S.compressing = true;
    updateStatusBar();
    setCompressStatus(T('正在压缩上下文…'), '');
    const res = await call('compress_context', { session_id: S.sessionId });
    if (!res || !res.ok) {
      S.compressing = false;
      updateStatusBar();
      const msg = (res && res.error) || '压缩失败';
      setCompressStatus(msg, 'fail');
      toast(msg);
    }
  }

  function setPerfText(id, text) {
    const el = document.getElementById(id);
    if (el) el.textContent = text;
  }

  function fmtCpu(value) {
    return (Number(value) || 0).toFixed(2) + '%';
  }

  function fmtMem(value) {
    const n = Number(value) || 0;
    return n >= 1000 ? (n / 1024).toFixed(2) + ' GB' : n.toFixed(1) + ' MB';
  }

  async function refreshPerfStats(force) {
    if (perfBusy) return;
    if (!force && S.view !== 'settings') return;
    perfBusy = true;
    try {
      if (force) {
        // 先采样一次建立基线，再短暂等待后取真实增量，避免首次显示 0.00%
        await call('perf_stats');
        await new Promise(function (resolve) { setTimeout(resolve, 300); });
      }
      const res = await call('perf_stats');
      if (!res || !res.ok) return;
      const backend = res.backend || {};
      const app = res.app || {};
      const system = res.system || {};
      setPerfText('perfBackendCpu', fmtCpu(backend.cpu_percent));
      setPerfText('perfBackendMem', fmtMem(backend.mem_mb));
      setPerfText('perfBackendThreads', String(backend.threads || 0));
      setPerfText('perfAppCpu', fmtCpu(app.cpu_percent));
      setPerfText('perfAppMem', fmtMem(app.mem_mb));
      setPerfText('perfAppProcesses', String(app.processes || 0));
      setPerfText('perfSystemCpu', fmtCpu(system.cpu_percent));
      setPerfText('perfSystemMem', TF('{used} / {total}', {
        used: fmtMem(system.mem_used_mb), total: fmtMem(system.mem_total_mb),
      }));
      const last = res.last_run;
      const lastEl = $('#perfLastRun');
      if (lastEl) {
        lastEl.textContent = last
          ? TF('上次对话：平均 CPU {cpu} · 用时 {sec}s · 结束时内存 {mem}', {
              cpu: fmtCpu(last.avg_cpu_percent),
              sec: Number(last.duration_s || 0).toFixed(1),
              mem: fmtMem(last.mem_mb),
            })
          : T('上次对话：—');
        lastEl.className = 'perf-run' + (last
          ? (Number(last.avg_cpu_percent) <= 1 ? ' ok' : ' warn') : '');
      }
      const updated = $('#perfUpdated');
      if (updated) {
        updated.textContent = TF('更新于 {time}', { time: new Date().toLocaleTimeString() });
      }
    } finally {
      perfBusy = false;
    }
  }

  async function refreshVoiceStatus() {
    const res = await call('voice_status');
    const el = $('#voiceModelState');
    const btn = $('#voiceModelBtn');
    if (!el || !res) return;
    if (res.ready) {
      el.textContent = T('已就绪 · SenseVoice 本地识别');
      el.classList.add('ok');
      if (btn) btn.hidden = true;
    } else if (res.downloading) {
      el.textContent = T('下载中…');
      el.classList.remove('ok');
      if (btn) btn.hidden = true;
    } else {
      el.textContent = T('未下载（约 228MB）');
      el.classList.remove('ok');
      if (btn) btn.hidden = false;
    }
  }

  async function saveSettings() {
    const draft = S.profileDraft || S.profile || {};
    if (S.settingsPage === 'groupModel' && S.settingsProvider &&
        $('#providerDetail') && !$('#providerDetail').hidden) {
      const saved = await saveProviderDetail(false);
      if (!saved) return;
    }
    const payload = {
      thinking: $('#setThinking').value,
      reasoning_effort: $('#setEffort').value,
      timeout: parseInt($('#setTimeout').value, 10) || 90,
      max_tokens: parseInt($('#setMaxTokens').value, 10) || 65536,
      output_dir: $('#setOut').value.trim(),
      theme: $('#setTheme').value,
      accent: S.accent,
      language: $('#setLanguage').value,
      assistant_name: ($('#setAssistantName').value || '').trim() || 'Nexus',
      profile: {
        name: ($('#setProfileName').value || '').trim(),
        avatar: draft.avatar === 'custom' ? 'custom' : 'default',
        color: draft.color || 'blue',
        avatar_data: draft.avatarData || '',
      },
      hotkey: $('#setHotkey').value.trim(),
      voice_hotkey: $('#setVoiceHotkey').value.trim(),
      autostart: $('#setAutostart').checked,
      mode: $('#setMode').value,
      notify_done: $('#setNotifyDone').checked,
      show_api_errors: $('#setShowApiErrors').checked,
      context_limit: contextLimitValue(),
      context_compress: $('#setContextCompress').checked,
      update_repo: $('#setUpdateRepo').value.trim(),
      update_base_url: $('#setUpdateBase') ? $('#setUpdateBase').value.trim() : '',
      update_auto_check: $('#setUpdateAuto').checked,
      skills_auto: $('#setSkillsAuto') ? $('#setSkillsAuto').checked : true,
      memory_enabled: $('#setMemoryEnabled') ? $('#setMemoryEnabled').checked : true,
    };
    const res = await call('settings_save', payload);
    if (!res) return;
    if (!res.ok) { toast(res.error || '保存失败'); return; }
    setTheme(payload.theme);
    setMode(payload.mode);
    setAccent(payload.accent);
    toast('设置已保存');
    const state = await call('get_state');
    if (state) {
      applyState(state);
      if (state.language && window.NexusI18n) window.NexusI18n.setLang(state.language);
      loadSettings(state.settings);
      renderTitle();
    }
  }

  let themeMediaBound = false;
  function setTheme(theme) {
    S.themeMode = theme || 'light';
    if (!themeMediaBound && window.matchMedia) {
      const media = window.matchMedia('(prefers-color-scheme: dark)');
      const onChange = function () {
        if (S.themeMode === 'system') setTheme('system');
      };
      if (media.addEventListener) media.addEventListener('change', onChange);
      else if (media.addListener) media.addListener(onChange);
      themeMediaBound = true;
    }
    let dark = false;
    if (S.themeMode === 'system') {
      dark = !!(window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches);
    } else {
      dark = S.themeMode === 'dark';
    }
    S.theme = dark ? 'dark' : 'light';
    document.documentElement.setAttribute('data-theme', S.theme);
  }

  /* ---------------- 更新弹窗 ---------------- */
  function showUpdate(info) {
    S.updateInfo = info || {};
    if (!S.updateInfo.has_update || S.updateInfo.skipped) return;
    S.updateReady = false;
    $('#updateCurrent').textContent = 'v' + (S.updateInfo.current || '');
    $('#updateLatest').textContent = 'v' + (S.updateInfo.latest || '');
    $('#updateNotes').textContent = S.updateInfo.notes || '';
    const sim = $('#updateSimHint');
    if (sim) sim.hidden = !S.updateInfo.simulate;
    const pageBtn = $('#updatePage');
    if (pageBtn) pageBtn.hidden = S.updateInfo.source === 'manifest' || !S.updateInfo.page;
    $('#updateProgress').hidden = true;
    $('#updateBar').style.width = '0%';
    $('#updateProgressText').textContent = '';
    $('#updateNow').disabled = false;
    $('#updateMask').hidden = false;
  }

  function closeUpdate() {
    if (S.updateReady) return;
    $('#updateMask').hidden = true;
  }

  function updateUpdateProgress(evt) {
    S.updateReady = true;
    const box = $('#updateProgress');
    const bar = $('#updateBar');
    const text = $('#updateProgressText');
    if (!box || !bar || !text) return;
    box.hidden = false;
    $('#updateNow').disabled = true;
    if (evt.phase === 'download') {
      const pct = evt.total ? Math.max(0, Math.min(100, Math.round(evt.done / evt.total * 100))) : 0;
      bar.style.width = pct + '%';
      text.textContent = T('正在下载更新…') + (evt.total ? ' ' + pct + '%' : '');
    } else {
      bar.style.width = '100%';
      text.textContent = T('正在安装，Nexus 即将退出…');
    }
  }

  function updateUpdateFailed(message) {
    S.updateReady = false;
    const text = $('#updateProgressText');
    if (text) text.textContent = TF('更新失败：{msg}', { msg: message });
    $('#updateNow').disabled = false;
  }

  function showUpdateSimulated(evt) {
    S.updateReady = false;
    const box = $('#updateProgress');
    const bar = $('#updateBar');
    const text = $('#updateProgressText');
    if (box) box.hidden = false;
    if (bar) bar.style.width = '100%';
    if (text) text.textContent = evt.message || T('模拟更新完成：安装包已下载并通过校验，未执行安装。');
    const btn = $('#updateNow');
    if (btn) btn.disabled = true;
    if (evt.path) toast('更新包已保存：' + evt.path);
  }

  function renderScenes(scenes) {
    const box = $('#sceneChips');
    box.innerHTML = '';
    (scenes || []).forEach(function (sc) {
      const btn = document.createElement('button');
      btn.className = 'chip';
      btn.textContent = sc.title;
      btn.addEventListener('click', function () {
        if (sc.screenshot) { capture(); return; }
        if (sc.input) {
          $('#input').value = sc.prompt || '';
          $('#input').focus();
          autoGrow();
          return;
        }
        sendText(sc.prompt || sc.title);
      });
      box.appendChild(btn);
    });
  }

  /* ---------------- 输入框 ---------------- */
  function autoGrow() {
    const ta = $('#input');
    ta.style.height = 'auto';
    ta.style.height = Math.min(ta.scrollHeight, 160) + 'px';
  }

  function estTokens(text) {
    const s = String(text || '');
    let ascii = 0;
    for (let i = 0; i < s.length; i++) { if (s.charCodeAt(i) < 128) ascii += 1; }
    return Math.max(1, Math.round(ascii / 4 + (s.length - ascii) / 1.6));
  }

  function updateStatusBar() {
    const el = $('#composerStatus');
    if (!el) return;
    const ctx = S.contextTokens || 0;
    S.contextTokens = ctx;
    const ctxText = ctx >= 1000 ? (ctx / 1000).toFixed(1) + 'k' : String(ctx);
    const limit = S.contextLimit || contextLimitValue();
    const pct = Math.max(0, Math.min(999, Math.round(ctx / limit * 100)));
    const en = window.NexusI18n && window.NexusI18n.lang === 'en';
    const ready = en ? 'Ready' : '就绪';
    const ctxLabel = (en ? 'Context ~' : '上下文 ~') + ctxText + ' tok';
    const ringPct = Math.min(100, pct);
    const ringLen = 2 * Math.PI * 6;
    const ringDash = ringLen * (1 - ringPct / 100);
    const compressBtn = '<button type="button" class="st-ctx" data-action="compress"' +
      ' title="' + TF('上下文已用 {pct}%，点击压缩', { pct: pct }) + '"' +
      ' aria-label="' + T('压缩上下文') + '"' +
      (S.streaming || S.compressing || !S.sessionId ? ' disabled' : '') + '>' +
      '<svg viewBox="0 0 16 16" aria-hidden="true">' +
      '<circle class="st-ctx-track" cx="8" cy="8" r="6"></circle>' +
      '<circle class="st-ctx-arc" cx="8" cy="8" r="6"' +
      ' stroke-dasharray="' + ringLen.toFixed(2) + '"' +
      ' stroke-dashoffset="' + ringDash.toFixed(2) + '"></circle>' +
      '</svg><span>' + pct + '%</span></button>';
    let html = '';
    if (S.streaming) {
      const sec = S.runStart ? ((Date.now() - S.runStart) / 1000).toFixed(1) : '0.0';
      html = '<span class="st-accent">' + (en ? 'Round ' : '第 ') + Math.max(1, S.runRounds) + (en ? '' : ' 轮') + '</span>' +
        '<span>' + S.runSteps + (en ? ' steps' : ' 步') + '</span>' +
        '<span>' + sec + 's</span>' +
        '<span>' + ctxLabel + '</span>' + compressBtn;
    } else if (S.runDuration) {
      html = '<span>' + ready + '</span>' +
        '<span>' + S.runRounds + (en ? ' rounds · ' : ' 轮 · ') + S.runSteps + (en ? ' steps · ' : ' 步 · ') + S.runDuration.toFixed(1) + 's</span>' +
        '<span>' + ctxLabel + '</span>' + compressBtn;
    } else {
      html = '<span>' + ready + '</span><span>' + ctxLabel + '</span>' + compressBtn;
    }
    if (html !== statusHtml) {
      statusHtml = html;
      el.innerHTML = html;
    }
  }

  function startVoice() {
    call('voice_toggle').then(function (res) {
      if (res && res.ok === false && res.error) toast(res.error);
    });
  }

  function renderVoiceWave() {
    const bars = document.querySelectorAll('#voiceBars i');
    if (!bars.length) return;
    const level = Math.max(0.1, Math.min(1, Number(S.voiceLevel) || 0.1));
    const bands = S.voiceBands && S.voiceBands.length === bars.length ? S.voiceBands : null;
    const t = Date.now() / 190;
    Array.prototype.forEach.call(bars, function (bar, i) {
      const wave = 0.5 + 0.5 * Math.sin(t + i * 0.8);
      const energy = bands ? Math.max(0.08, Math.min(1, Number(bands[i]) || 0)) : level;
      const value = Math.min(1, 0.12 + energy * 1.05 + wave * 0.08);
      bar.style.transform = 'scaleY(' + value.toFixed(3) + ')';
      bar.style.opacity = (0.55 + value * 0.45).toFixed(2);
    });
  }

  function applyVoiceLevel(level, bands) {
    S.voiceLevel = Math.max(0, Math.min(1, Number(level) || 0));
    if (bands && bands.length) S.voiceBands = bands.slice(0, 9);
  }

  function tickVoiceTime() {
    const el = $('#voiceTime');
    if (!el) return;
    const sec = S.voiceStart ? Math.floor((Date.now() - S.voiceStart) / 1000) : 0;
    el.textContent = String(Math.floor(sec / 60)).padStart(2, '0') + ':' +
      String(sec % 60).padStart(2, '0');
  }

  function enterVoiceMode() {
    if (S.voiceActive) return;
    const composer = $('#composer');
    const panel = $('#voicePanel');
    const input = $('#input');
    if (!composer || !panel || !input) return;
    S.voiceActive = true;
    S.voiceBase = input.value || '';
    S.voicePartial = '';
    S.voiceStart = Date.now();
    S.voiceLevel = 0;
    S.voiceBands = [];
    input.readOnly = true;
    composer.classList.add('voice-mode');
    panel.hidden = false;
    const hint = $('#voiceHint');
    if (hint) hint.textContent = '正在聆听…';
    renderVoiceWave();
    tickVoiceTime();
    if (S.voiceTimer) clearInterval(S.voiceTimer);
    if (S.voiceWaveTimer) clearInterval(S.voiceWaveTimer);
    S.voiceTimer = setInterval(tickVoiceTime, 400);
    S.voiceWaveTimer = setInterval(renderVoiceWave, 90);
    autoGrow();
  }

  function exitVoiceMode() {
    if (S.voiceTimer) { clearInterval(S.voiceTimer); S.voiceTimer = null; }
    if (S.voiceWaveTimer) { clearInterval(S.voiceWaveTimer); S.voiceWaveTimer = null; }
    S.voiceActive = false;
    S.voiceStart = 0;
    S.voiceLevel = 0;
    S.voiceBands = [];
    const composer = $('#composer');
    const panel = $('#voicePanel');
    const input = $('#input');
    if (composer) composer.classList.remove('voice-mode');
    if (panel) panel.hidden = true;
    if (input) input.readOnly = false;
    autoGrow();
  }

  function handleVoiceState(evt) {
    if (evt.target === 'quick') return;
    const btn = $('#voiceBtn');
    if (btn) btn.classList.toggle('recording', !!evt.recording);
    if (evt.recording) {
      enterVoiceMode();
      return;
    }
    if (evt.cancelled) {
      exitVoiceMode();
      return;
    }
    if (evt.downloading) {
      toast('语音模型下载中 ' + (evt.percent || 0) + '%');
      refreshVoiceStatus();
      return;
    }
    if (evt.ready) {
      toast('语音模型已就绪，再按一次麦克风开始');
      refreshVoiceStatus();
      return;
    }
    if (evt.error) {
      exitVoiceMode();
      toast(evt.error);
      return;
    }
    if (evt.empty) {
      exitVoiceMode();
      toast('没有识别到内容');
      return;
    }
    if (evt.busy) {
      const hint = $('#voiceHint');
      if (hint) hint.textContent = '正在识别…';
      applyVoiceLevel(0.1);
    }
  }

  function handleVoicePartial(text) {
    if (!S.voiceActive) return;
    const input = $('#input');
    if (!input) return;
    S.voicePartial = String(text || '');
    input.value = S.voiceBase + S.voicePartial;
    autoGrow();
  }

  function insertVoiceText(text) {
    if (!text) return;
    const input = $('#input');
    if (!input) return;
    if (S.voiceActive) {
      input.value = S.voiceBase + text;
      autoGrow();
      exitVoiceMode();
      input.focus();
      toast('已识别语音');
      return;
    }
    const start = input.selectionStart || 0;
    const end = input.selectionEnd || 0;
    const val = input.value || '';
    input.value = val.slice(0, start) + text + val.slice(end);
    input.selectionStart = input.selectionEnd = start + text.length;
    input.focus();
    autoGrow();
    toast('已识别语音');
  }

  function openHelp() {
    $('#helpMask').hidden = false;
  }

  function bind() {
    const msgs = $('#messages');
    if (msgs) {
      msgs.addEventListener('scroll', function () {
        followBottom = nearBottom(msgs);
      }, { passive: true });
    }
    const ta = $('#input');
    ta.addEventListener('input', function () {
      autoGrow();
      const ctx = triggerContext();
      if (ctx) {
        if (!S.trigger || S.trigger.trigger !== ctx.trigger) S.triggerIndex = 0;
        openTrigger(ctx);
      } else {
        closeTrigger();
      }
    });
    ta.addEventListener('keydown', function (e) {
      if (S.trigger) {
        if (e.key === 'ArrowDown') {
          e.preventDefault();
          if (S.triggerItems.length) {
            S.triggerIndex = (S.triggerIndex + 1) % S.triggerItems.length;
            renderTrigger();
          }
          return;
        }
        if (e.key === 'ArrowUp') {
          e.preventDefault();
          if (S.triggerItems.length) {
            S.triggerIndex = (S.triggerIndex - 1 + S.triggerItems.length) % S.triggerItems.length;
            renderTrigger();
          }
          return;
        }
        if (e.key === 'Enter' || e.key === 'Tab') {
          if (S.triggerItems.length) {
            e.preventDefault();
            applyTrigger(S.triggerIndex);
            return;
          }
        }
        if (e.key === 'Escape') {
          e.preventDefault();
          closeTrigger();
          return;
        }
      }
      if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
        e.preventDefault();
        if (S.voiceActive) return;
        sendText(ta.value);
      }
    });
    ta.addEventListener('blur', function () {
      setTimeout(function () {
        if ($('#triggerMenu') && !$('#triggerMenu').hidden) closeTrigger();
      }, 120);
    });

    $('#sendBtn').addEventListener('click', function () { sendText(ta.value); });
    $('#stopBtn').addEventListener('click', function () { call('stop'); });
    $('#shotBtn').addEventListener('click', function () { capture(); });
    $('#regionBtn').addEventListener('click', function () { capture('region'); });
    $('#voiceBtn').addEventListener('click', startVoice);
    $('#voiceStopBtn').addEventListener('click', function () { call('voice_toggle'); });
    $('#voiceModelBtn').addEventListener('click', async function () {
      const res = await call('voice_download');
      if (res && res.error) toast(res.error);
      else toast('已开始下载语音模型');
      setTimeout(refreshVoiceStatus, 600);
    });

    $('#plusBtn').addEventListener('click', function (e) {
      e.stopPropagation();
      closeTrigger();
      renderPlusSkills();
      togglePop('#plusMenu');
    });
    Array.prototype.slice.call(document.querySelectorAll('#plusMenu .menu-row')).forEach(function (row) {
      row.addEventListener('click', function () {
        const act = row.dataset.act;
        closeMenus();
        if (act === 'file') pickFileReference();
        else if (act === 'shot') capture();
        else if (act === 'region') capture('region');
      });
    });

    $('#modelPill').addEventListener('click', function (e) {
      e.stopPropagation();
      openModelMenu();
    });
    Array.prototype.slice.call(document.querySelectorAll('#modelMenu [data-effort]')).forEach(function (row) {
      row.addEventListener('click', function () { setEffort(row.dataset.effort); });
    });
    document.addEventListener('mousedown', function (e) {
      if (!e.target.closest('.composer')) closeMenus();
      if (!e.target.closest('.composer')) closeTrigger();
      if (window.innerWidth < 900 && !$('#app').classList.contains('collapsed') &&
          !e.target.closest('.sidebar') && !e.target.closest('#sidebarToggle')) {
        setSidebar(true);
      }
    });

    $('#newChatBtn').addEventListener('click', newChat);
    $('#newChatTopBtn').hidden = true;
    $('#newChatTopBtn').addEventListener('click', newChat);
    $('#collapseBtn').addEventListener('click', function () { setSidebar(true); });
    $('#sidebarToggle').addEventListener('click', function () { setSidebar(false); });
    $('#brandBtn').addEventListener('click', newChat);
    $('#allHistoryBtn').addEventListener('click', function () { switchView('history'); });
    $('#sideModeBtn').addEventListener('click', function () {
      switchView('settings');
      setTimeout(function () { showSettingsPage('groupMode'); }, 60);
    });
    $('#closeBtn').addEventListener('click', function () { call('win', 'hide'); });
    $('#minBtn').addEventListener('click', function () { call('win', 'minimize'); });
    $('#helpBtn').addEventListener('click', openHelp);
    $('#rpToggle').addEventListener('click', toggleRightPanel);
    $('#rpClose').addEventListener('click', closeRightPanel);
    initRpResizer();
    initRpTabs();
    $('#rpTabAdd').addEventListener('click', function (e) {
      e.stopPropagation();
      toggleRpMenu($('#rpTabMenu').hidden);
    });
    $('#rpTabMenu').addEventListener('click', function (e) {
      const btn = e.target.closest('.rp-menu-item');
      if (!btn) return;
      toggleRpMenu(false);
      const kind = btn.dataset.kind;
      if (kind === 'editor') activateRpTab('editor');
      else ensureWorkspace(kind);
    });
    document.addEventListener('click', function (e) {
      if (!e.target.closest('#rpTabMenu') && !e.target.closest('#rpTabAdd')) toggleRpMenu(false);
      S.rpTabs.forEach(function (ws) {
        if (!ws.shellMenu || ws.shellMenu.hidden) return;
        if (e.target.closest('.rp-subadd') || e.target.closest('.rp-shell-menu')) return;
        hideShellMenu(ws);
      });
    });
    $('#rpRefresh').addEventListener('click', function () { loadTree(); });
    $('#rpModeSeg').addEventListener('click', function (e) {
      const btn = e.target.closest('.rp-mode-btn');
      if (btn) setPreviewMode(btn.dataset.mdMode);
    });
    $('#rpSaveBtn').addEventListener('click', function () {
      if (S.previewData && S.previewData.kind === 'markdown') {
        if (S.editMode && S.mdDraft != null) savePreview(S.mdDraft);
      } else {
        saveOfficeEdits(true);
      }
    });
    $('#rpHtmlOpen').addEventListener('click', function () {
      if (S.previewData && S.previewData.path) openBrowser(S.previewData.path);
    });
    $('#rpSearch').addEventListener('input', function () {
      S.rpQuery = this.value;
      $('#rpSearchClear').hidden = !this.value;
      clearTimeout(S.searchTimer);
      S.searchTimer = setTimeout(function () { renderTreeView(); }, 90);
    });
    $('#rpSearchClear').addEventListener('click', function () {
      const input = $('#rpSearch');
      input.value = '';
      S.rpQuery = '';
      this.hidden = true;
      input.focus();
      renderTreeView();
    });
    $('#rpPreviewOpen').addEventListener('click', function () {
      if (S.previewPath) call('open_path', S.previewPath);
    });
    $('#lightbox').addEventListener('click', closeLightbox);
    bindPreviewDrop();
    $('#helpClose').addEventListener('click', function () { $('#helpMask').hidden = true; });
    $('#helpMask').addEventListener('click', function (e) {
      if (e.target === $('#helpMask')) $('#helpMask').hidden = true;
    });

    Array.prototype.slice.call(document.querySelectorAll('.nav-item[data-view]')).forEach(function (btn) {
      btn.addEventListener('click', function () {
        switchView(btn.dataset.view);
        if (window.innerWidth < 900) setSidebar(true);
      });
    });

    $('#themeBtn').addEventListener('click', function () {
      const next = S.theme === 'dark' ? 'light' : 'dark';
      setTheme(next);
      call('settings_save', { theme: next }).then(function (res) {
        if (res && res.ok) { $('#setTheme').value = next; toast(next === 'dark' ? '已切换到深色' : '已切换到浅色'); }
      });
    });

    $('#histTabs').addEventListener('click', function (e) {
      const btn = e.target.closest('.seg-btn');
      if (btn) loadHistory(btn.dataset.kind);
    });

    $('#saveBtn').addEventListener('click', saveSettings);
    $('#setProfileName').addEventListener('input', function () {
      if (!S.profileDraft) S.profileDraft = { name: '', avatar: S.profile.avatar, color: S.profile.color, avatarData: '' };
      S.profileDraft.name = this.value;
      const identity = $('#profileIdentity');
      if (identity) {
        identity.textContent = this.value.trim()
          ? T('本地用户') + ' · ' + this.value.trim()
          : T('本地用户');
      }
    });
    $('#setAssistantName').addEventListener('input', function () {
      S.assistantName = this.value.trim() || 'Nexus';
    });
    $('#avatarUploadBtn').addEventListener('click', function () { $('#avatarFile').click(); });
    $('#avatarDefaultBtn').addEventListener('click', function () {
      if (!S.profileDraft) S.profileDraft = { name: S.profile.name, avatar: S.profile.avatar, color: S.profile.color, avatarData: '' };
      S.profileDraft.avatar = 'default';
      S.profileDraft.avatarData = '';
      paintAvatar($('#profilePreview'), '', false);
      toast(T('已选择默认头像，保存后生效'));
    });
    $('#avatarFile').addEventListener('change', function () {
      const input = this;
      const file = input.files && input.files[0];
      if (!file) return;
      if (!window.NexusAvatar) { toast(T('头像组件未加载')); input.value = ''; return; }
      window.NexusAvatar.read(file, function (data) {
        if (!S.profileDraft) S.profileDraft = { name: S.profile.name, avatar: S.profile.avatar, color: S.profile.color, avatarData: '' };
        S.profileDraft.avatar = 'custom';
        S.profileDraft.avatarData = data;
        paintAvatar($('#profilePreview'), data, true);
        toast(T('头像已选择，保存后生效'));
      }, function (reason) {
        if (reason === 'size') toast(T('图片不能超过 8MB'));
        else if (reason === 'type') toast(T('仅支持 PNG / JPG / WebP 图片'));
        else toast(T('无法读取这张图片'));
      });
      input.value = '';
    });
    Array.prototype.slice.call(document.querySelectorAll('#accentPicker .color-choice')).forEach(function (btn) {
      btn.addEventListener('click', function () { setAccent(btn.dataset.color); });
    });
    $('#setContextPreset').addEventListener('change', function () {
      S.contextLimit = contextLimitValue();
      updateContextUsage();
      updateStatusBar();
    });
    $('#compressNowBtn').addEventListener('click', compressNow);
    const statusBox = $('#composerStatus');
    if (statusBox) {
      statusBox.addEventListener('click', function (e) {
        const btn = e.target.closest('[data-action="compress"]');
        if (btn && !btn.disabled) compressNow();
      });
    }
    $('#openDataBtn').addEventListener('click', function () { call('open_data_dir'); });
    $('#clearHistoryBtn').addEventListener('click', async function () {
      if (!window.confirm(T('确定要清空全部对话历史吗？此操作无法恢复。'))) return;
      const res = await call('clear_history');
      if (res && res.ok) newChat();
    });
    $('#resetSettingsBtn').addEventListener('click', async function () {
      if (!window.confirm(T('确定恢复默认设置吗？API Key、账号资料和历史记录会保留。'))) return;
      const res = await call('reset_settings');
      if (res && res.ok) {
        applyState(res.state);
        loadSettings(res.state.settings);
        toast('已恢复默认设置');
      }
    });
    $('#checkUpdateBtn').addEventListener('click', async function () {
      const status = $('#updateStatus');
      status.className = 'field-status';
      status.textContent = T('检查中…');
      const res = await call('check_update', true);
      if (!res) { status.textContent = ''; return; }
      if (!res.ok) {
        status.className = 'field-status fail';
        status.textContent = TF('检查更新失败：{msg}', { msg: res.error || '' });
        return;
      }
      if (res.has_update) {
        status.textContent = 'v' + res.latest;
        showUpdate(res);
      } else {
        status.className = 'field-status ok';
        status.textContent = T('已是最新版本');
      }
    });
    $('#onboardingBtn').addEventListener('click', function () { call('show_onboarding'); });
    $('#whatsnewBtn').addEventListener('click', function () { call('show_whatsnew'); });
    $('#updateLater').addEventListener('click', function () {
      const latest = (S.updateInfo && S.updateInfo.latest) || '';
      call('update_skip', latest).then(function () { closeUpdate(); });
    });
    $('#updatePage').addEventListener('click', function () {
      call('open_release_page', (S.updateInfo && S.updateInfo.page) || '');
    });
    $('#updateNow').addEventListener('click', async function () {
      $('#updateNow').disabled = true;
      const res = await call('update_install');
      if (res && !res.ok) {
        $('#updateNow').disabled = false;
        updateUpdateFailed((res && res.error) || '');
      }
    });
    $('#updateMask').addEventListener('click', function (e) {
      if (e.target === $('#updateMask')) closeUpdate();
    });
    $('#pickDirBtn').addEventListener('click', async function () {
      const res = await call('pick_folder');
      if (res && res.ok) $('#setOut').value = res.path;
    });
    $('#openDirBtn').addEventListener('click', function () { call('open_path', $('#setOut').value.trim()); });
    $('#shortcutBtn').addEventListener('click', async function () {
      const status = $('#shortcutStatus');
      status.className = 'field-status';
      status.textContent = '创建中…';
      const res = await call('create_shortcut');
      if (res && res.ok) {
        status.className = 'field-status ok';
        status.textContent = '已创建';
      } else {
        status.className = 'field-status fail';
        status.textContent = (res && res.error) || '创建失败';
      }
    });

    Array.prototype.slice.call(document.querySelectorAll('.settings-nav-item')).forEach(function (btn) {
      btn.addEventListener('click', function () {
        showSettingsPage(btn.dataset.target);
      });
    });

    if ($('#skillsNavBtn')) $('#skillsNavBtn').addEventListener('click', function () {
      S.settingsPage = 'groupSkills';
      switchView('settings');
      showSettingsPage('groupSkills');
      Array.prototype.slice.call(document.querySelectorAll('.nav-item[data-view]')).forEach(function (b) {
        b.classList.remove('active');
      });
      $('#skillsNavBtn').classList.add('active');
    });
    if ($('#skillNewBtn')) $('#skillNewBtn').addEventListener('click', function () { openSkillEditor(null); });
    if ($('#skillRefreshBtn')) $('#skillRefreshBtn').addEventListener('click', loadSkills);
    if ($('#skillDirBtn')) $('#skillDirBtn').addEventListener('click', async function () {
      const res = await call('skills', 'open_dir');
      if (res && res.error) toast(res.error);
    });
    if ($('#skillMaskClose')) $('#skillMaskClose').addEventListener('click', closeSkillEditor);
    if ($('#skillCancel')) $('#skillCancel').addEventListener('click', closeSkillEditor);
    if ($('#skillSave')) $('#skillSave').addEventListener('click', saveSkillEditor);
    if ($('#skillMask')) $('#skillMask').addEventListener('click', function (e) {
      if (e.target === $('#skillMask')) closeSkillEditor();
    });

    if ($('#promptNewBtn')) $('#promptNewBtn').addEventListener('click', function () { openPromptEditor(null); });
    if ($('#promptDirBtn')) $('#promptDirBtn').addEventListener('click', async function () {
      const res = await call('prompts', 'open_dir');
      if (res && res.error) toast(res.error);
    });
    if ($('#promptMaskClose')) $('#promptMaskClose').addEventListener('click', closePromptEditor);
    if ($('#promptCancel')) $('#promptCancel').addEventListener('click', closePromptEditor);
    if ($('#promptSave')) $('#promptSave').addEventListener('click', savePromptEditor);
    if ($('#promptMask')) $('#promptMask').addEventListener('click', function (e) {
      if (e.target === $('#promptMask')) closePromptEditor();
    });
    if ($('#promptBody')) $('#promptBody').addEventListener('input', updatePromptPreview);

    if ($('#memoryAddBtn')) $('#memoryAddBtn').addEventListener('click', addMemory);
    if ($('#memoryInput')) $('#memoryInput').addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && !e.isComposing) { e.preventDefault(); addMemory(); }
    });
    if ($('#memoryClearBtn')) $('#memoryClearBtn').addEventListener('click', clearMemory);
    if ($('#memoryMaskClose')) $('#memoryMaskClose').addEventListener('click', closeMemoryEditor);
    if ($('#memoryEditCancel')) $('#memoryEditCancel').addEventListener('click', closeMemoryEditor);
    if ($('#memoryEditSave')) $('#memoryEditSave').addEventListener('click', saveMemoryEditor);
    if ($('#memoryEditDelete')) $('#memoryEditDelete').addEventListener('click', async function () {
      if (!S.editingMemory) return;
      const id = S.editingMemory.id;
      closeMemoryEditor();
      await deleteMemoryItem(id);
    });
    if ($('#memoryMask')) $('#memoryMask').addEventListener('click', function (e) {
      if (e.target === $('#memoryMask')) closeMemoryEditor();
    });

    if ($('#pdClose')) $('#pdClose').addEventListener('click', function () {
      const detail = $('#providerDetail');
      if (detail) detail.hidden = true;
      S.settingsProvider = '';
      renderProviderGrid();
    });
    if ($('#pdSave')) $('#pdSave').addEventListener('click', function () { saveProviderDetail(false); });
    if ($('#pdTest')) $('#pdTest').addEventListener('click', testProviderDetail);
    if ($('#pdActivate')) $('#pdActivate').addEventListener('click', function () { saveProviderDetail(true); });
    if ($('#pdClear')) $('#pdClear').addEventListener('click', clearProviderKey);
    if ($('#pdModelAdd')) $('#pdModelAdd').addEventListener('click', addProviderModel);
    if ($('#pdModelRefresh')) $('#pdModelRefresh').addEventListener('click', refreshProviderModels);
    if ($('#pdModelInput')) {
      $('#pdModelInput').addEventListener('keydown', function (e) {
        if (e.key === 'Enter') { e.preventDefault(); addProviderModel(); }
      });
    }
    Array.prototype.slice.call(document.querySelectorAll('#pdKindSeg .seg-btn')).forEach(function (btn) {
      btn.addEventListener('click', function () {
        S.providerDraftKind = btn.dataset.kind === 'anthropic' ? 'anthropic' : 'openai';
        Array.prototype.slice.call(document.querySelectorAll('#pdKindSeg .seg-btn')).forEach(function (b) {
          b.classList.toggle('active', b.dataset.kind === S.providerDraftKind);
        });
        if ($('#pdKind')) $('#pdKind').textContent = S.providerDraftKind === 'anthropic' ? 'Anthropic' : 'OpenAI';
        if ($('#pdBase') && !$('#pdBase').value.trim()) {
          $('#pdBase').value = S.providerDraftKind === 'anthropic'
            ? 'https://api.anthropic.com' : '';
        }
      });
    });

    $('#confirmCancel').addEventListener('click', function () { closeConfirm(false); });
    $('#confirmAllow').addEventListener('click', function () { closeConfirm(true); });
    $('#confirmMask').addEventListener('click', function (e) {
      if (e.target === $('#confirmMask')) closeConfirm(false);
    });
    $('#askCancel').addEventListener('click', function () { closeAsk(null); });
    $('#askSubmit').addEventListener('click', function () {
      const value = $('#askInput').value.trim();
      closeAsk(value || null);
    });
    $('#askInput').addEventListener('keydown', function (e) {
      if (e.key === 'Enter') {
        e.preventDefault();
        const value = $('#askInput').value.trim();
        closeAsk(value || null);
      }
    });
    $('#askMask').addEventListener('click', function (e) {
      if (e.target === $('#askMask')) closeAsk(null);
    });

    document.addEventListener('keydown', function (e) {
      const key = e.key.toLowerCase();
      if (e.key === 'Escape') {
        if (!$('#lightbox').hidden) { closeLightbox(); return; }
        if (!$('#confirmMask').hidden) { closeConfirm(false); return; }
        if (!$('#updateMask').hidden) { closeUpdate(); return; }
        if (!$('#helpMask').hidden) { $('#helpMask').hidden = true; return; }
        closeMenus();
        closeTrigger();
      }
      if (e.key === 'F11') { e.preventDefault(); playWinAnim(); call('win', 'fullscreen'); }
      if (e.ctrlKey && key === 'n') { e.preventDefault(); newChat(); }
      if (e.ctrlKey && key === 'b') { e.preventDefault(); toggleSidebar(); }
      if (e.ctrlKey && key === 's') {
        const office = S.previewData && ['docx', 'xlsx', 'pptx'].indexOf(S.previewData.kind) >= 0;
        if (office && (S.docxDirty || S.xlsxDirty || S.pptDirty)) {
          e.preventDefault();
          saveOfficeEdits(true);
          return;
        }
      }
      if (e.ctrlKey && (e.key === '/' || e.key === '?')) { e.preventDefault(); openHelp(); }
    });

    $('#maxBtn').addEventListener('click', function () { playWinAnim(); call('win', 'maximize'); });
    $('#topbar').addEventListener('dblclick', function (e) {
      if (e.target.closest('button')) return;
      playWinAnim();
      call('win', 'maximize');
    });

    bindDrag($('#topbar'));
    bindDrop();
    $('#perfRefreshBtn').addEventListener('click', function () { refreshPerfStats(true); });
    setInterval(updateStatusBar, 1000);
    setInterval(function () {
      if (S.view === 'settings') refreshPerfStats();
    }, 2000);
  }

  function bindPreviewDrop() {
    const area = $('#rpPreview');
    if (!area) return;
    let depth = 0;
    function hasFiles(e) {
      return e.dataTransfer &&
        Array.prototype.indexOf.call(e.dataTransfer.types || [], 'Files') >= 0;
    }
    function mark(on) {
      const preview = $('#rpPreview');
      if (preview) preview.classList.toggle('over', on);
    }
    area.addEventListener('dragenter', function (e) {
      if (!hasFiles(e)) return;
      e.preventDefault();
      e.stopPropagation();
      depth += 1;
      mark(true);
    });
    area.addEventListener('dragover', function (e) {
      if (!hasFiles(e)) return;
      e.preventDefault();
      e.stopPropagation();
      e.dataTransfer.dropEffect = 'copy';
    });
    area.addEventListener('dragleave', function (e) {
      if (!hasFiles(e)) return;
      e.stopPropagation();
      depth = Math.max(0, depth - 1);
      if (!depth) mark(false);
    });
    area.addEventListener('drop', function (e) {
      if (!e.dataTransfer || !e.dataTransfer.files || !e.dataTransfer.files.length) return;
      e.preventDefault();
      e.stopPropagation();
      depth = 0;
      mark(false);
      previewDropped(e.dataTransfer.files);
    });
  }

  function bindDrop() {
    window.addEventListener('dragenter', function (e) {
      if (!e.dataTransfer || Array.prototype.indexOf.call(e.dataTransfer.types || [], 'Files') < 0) return;
      e.preventDefault();
      S.dragDepth += 1;
      showDrop(true);
    });
    window.addEventListener('dragover', function (e) {
      if (!e.dataTransfer || Array.prototype.indexOf.call(e.dataTransfer.types || [], 'Files') < 0) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = 'copy';
    });
    window.addEventListener('dragleave', function (e) {
      if (!e.dataTransfer || Array.prototype.indexOf.call(e.dataTransfer.types || [], 'Files') < 0) return;
      S.dragDepth = Math.max(0, S.dragDepth - 1);
      if (!S.dragDepth) showDrop(false);
    });
    window.addEventListener('drop', function (e) {
      if (!e.dataTransfer || !e.dataTransfer.files || !e.dataTransfer.files.length) return;
      e.preventDefault();
      S.dragDepth = 0;
      showDrop(false);
      handleFiles(e.dataTransfer.files);
    });
  }

  function bindDrag(el) {
    let active = false;
    let last = 0;
    el.addEventListener('pointerdown', function (e) {
      if (e.button !== 0 || e.target.closest('button')) return;
      active = true;
      try { el.setPointerCapture(e.pointerId); } catch (err) { /* ignore */ }
      call('win', 'drag_start');
    });
    el.addEventListener('pointermove', function (e) {
      if (!active) return;
      const now = Date.now();
      if (now - last < 16) return;
      last = now;
      call('win', 'drag_move');
    });
    function end() {
      if (!active) return;
      active = false;
      call('win', 'drag_end');
    }
    el.addEventListener('pointerup', end);
    el.addEventListener('pointercancel', end);
  }

  /* ---------------- Toast ---------------- */
  let toastTimer = null;
  function toast(text) {
    const el = $('#toast');
    el.textContent = T(text || '');
    el.hidden = false;
    requestAnimationFrame(function () { el.classList.add('show'); });
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () {
      el.classList.remove('show');
      setTimeout(function () { el.hidden = true; }, 220);
    }, 2400);
  }

  /* ---------------- 启动 ---------------- */
  async function boot() {
    if (S.booted) return;
    if (!api()) {
      window.addEventListener('pywebviewready', boot, { once: true });
      return;
    }
    S.booted = true;
    window.addEventListener('error', function (e) {
      try {
        call('log_js', 'JS: ' + (e.message || '') + ' @ ' + (e.filename || '') + ':' + (e.lineno || 0));
      } catch (err) { /* ignore */ }
    });
    window.addEventListener('unhandledrejection', function (e) {
      var r = e && e.reason;
      try { call('log_js', 'PROMISE: ' + (r && r.message ? r.message : r)); } catch (err) { /* ignore */ }
    });
    try {
      if (localStorage.getItem('nexus.sidebar') === 'collapsed') setSidebar(true);
      S.rpWidth = parseInt(localStorage.getItem(RP_W_KEY), 10) || 0;
    } catch (e) { /* ignore */ }
    if (window.innerWidth < 900) setSidebar(true);
    let rpResizeTimer = null;
    window.addEventListener('resize', function () {
      if (window.innerWidth < 760) setSidebar(true);
      if (window.innerWidth < 900 && S.rightOpen) closeRightPanel();
      if (S.rpWidth) applyRpWidth(S.rpWidth, false);
      clearTimeout(rpResizeTimer);
      rpResizeTimer = setTimeout(function () {
        const inner = activeInner(rpTabById(S.rpActive));
        if (inner && inner.kind === 'browser' && inner.viewId && S.rightOpen) {
          syncBrowserRect(inner);
        }
      }, 160);
    });
    window.addEventListener('focus', function () {
      if (S.rightOpen && S.rpMode === 'tree') loadTree(true);
    });
    bind();
    if (S.rpWidth) applyRpWidth(S.rpWidth, false);
    // 上一次页面会话可能留下原生浏览器子窗口（例如 WebView 崩溃后自动重载）
    call('browser_embed_close_all');
    const st = await call('get_state');
    if (st && st.ok) {
      if (st.language && window.NexusI18n) window.NexusI18n.setLang(st.language);
      if (st.accent) setAccent(st.accent);
      if (st.profile) applyProfile(st.profile);
      applyState(st);
      setTheme(st.theme);
      loadSettings(st.settings);
      loadSkills();
      loadPrompts();
    }
    window.addEventListener('nexus:lang', function () {
      renderTitle();
      renderAssistantGreeting();
      setMode(S.settings.mode || 'supervised');
      syncModelMenu();
      renderScenes(S.scenes);
      updateContextUsage();
      updateStatusBar();
      if (S.view === 'settings') loadSettings(S.settings);
      renderSkills();
      renderPrompts();
      renderMemory();
    });
    renderTitle();
    updateStatusBar();
    loadSideSessions();
    autoGrow();
    setTimeout(function () { $('#input').focus(); }, 60);
  }

  if (window.pywebview && window.pywebview.api) boot();
  else window.addEventListener('pywebviewready', boot, { once: true });
})();
