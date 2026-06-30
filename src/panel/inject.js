/**
 * Agentic Playwright MCP — Interactive Panel Injection Script
 *
 * 通过 BrowserContext.addInitScript 注入到所有页面。
 * 使用 Shadow DOM (mode: 'closed') 封装，与宿主页面完全隔离。
 *
 * window.__agentic_panel__ API:
 *   .data        — 用户输入的最新数据 { action, value, timestamp }
 *   .events      — 事件队列 [{ action, value, timestamp }, ...]
 *   .log(msg)    — 向面板日志区写入消息
 *   .setTitle(t) — 设置面板标题
 *   .prompt(q, cb) — 程序向用户提问，用户回答后触发 cb(answer)
 *   .setFields(f)  — 动态设置表单字段 [{ name, label, type, placeholder, options? }]
 */
(function () {
  "use strict";

  // 防止重复注入
  if (window.__agentic_panel__) return;

  // ── 状态 ──────────────────────────────────────────────
  const state = {
    data: null,
    events: [],
    title: "Agentic Panel",
    fields: [
      { name: "input", label: "输入", type: "text", placeholder: "输入内容..." },
    ],
    promptQueue: [], // { question, resolve }
    currentPrompt: null,
    logEntries: [],
    minimized: true, // 默认最小化
  };

  // ── 暴露到 window 的 API ─────────────────────────────
  window.__agentic_panel__ = {
    get data() {
      return state.data;
    },
    get events() {
      return [...state.events];
    },
    /** 读取并清空事件队列 */
    flushEvents() {
      const evts = [...state.events];
      state.events = [];
      return evts;
    },
    /** 向面板日志区写入消息 */
    log(msg) {
      const entry = { text: String(msg), time: new Date().toLocaleTimeString() };
      state.logEntries.push(entry);
      if (state.logEntries.length > 50) state.logEntries.shift();
      renderLogs();
    },
    /** 设置面板标题 */
    setTitle(text) {
      state.title = String(text);
      renderTitle();
    },
    /** 程序向用户提问，返回 Promise */
    prompt(question) {
      return new Promise((resolve) => {
        state.promptQueue.push({ question, resolve });
        if (!state.currentPrompt) showNextPrompt();
      });
    },
    /** 动态设置表单字段 */
    setFields(fields) {
      state.fields = fields;
      renderForm();
    },
    /** 显示面板 */
    show() {
      state.minimized = false;
      syncVisibility();
    },
    /** 隐藏面板 */
    hide() {
      state.minimized = true;
      syncVisibility();
    },
    /** 切换显隐 */
    toggle() {
      state.minimized = !state.minimized;
      syncVisibility();
    },
  };

  // ── 面板 DOM 构建 ────────────────────────────────────
  const PANEL_ID = "__agentic_panel__";
  let host = null;
  let shadow = null;
  let panelEl = null;

  function createPanel() {
    host = document.createElement("div");
    host.id = PANEL_ID;
    // 防止宿主页面通过 shadowRoot 访问内部
    shadow = host.attachShadow({ mode: "closed" });

    const style = document.createElement("style");
    style.textContent = `
      * { box-sizing: border-box; margin: 0; padding: 0; }
      :host { all: initial; }

      .panel {
        position: fixed;
        top: 12px;
        right: 12px;
        width: 320px;
        max-height: calc(100vh - 24px);
        background: #1a1a2e;
        color: #e0e0e0;
        border-radius: 12px;
        box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        font-size: 13px;
        z-index: 2147483647;
        display: flex;
        flex-direction: column;
        overflow: hidden;
        transition: width 0.2s, max-height 0.2s;
      }
      .panel.minimized {
        width: 48px;
        max-height: 48px;
        border-radius: 50%;
        cursor: pointer;
      }
      .panel.minimized .panel-body,
      .panel.minimized .panel-footer { display: none; }

      .panel-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 10px 14px;
        background: #16213e;
        cursor: pointer;
        user-select: none;
        flex-shrink: 0;
      }
      .panel.minimized .panel-header {
        padding: 12px;
        justify-content: center;
      }
      .panel-title {
        font-weight: 600;
        font-size: 13px;
        color: #e94560;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }
      .panel.minimized .panel-title { display: none; }
      .panel-icon {
        display: none;
        font-size: 20px;
        line-height: 1;
      }
      .panel.minimized .panel-icon { display: block; }
      .panel-btns { display: flex; gap: 6px; }
      .panel.minimized .panel-btns { display: none; }
      .btn-icon {
        background: none;
        border: none;
        color: #888;
        cursor: pointer;
        font-size: 14px;
        padding: 2px 4px;
        border-radius: 4px;
      }
      .btn-icon:hover { color: #e94560; background: rgba(233,69,96,0.1); }

      .panel-body {
        flex: 1;
        overflow-y: auto;
        padding: 12px 14px;
        display: flex;
        flex-direction: column;
        gap: 10px;
      }

      /* 表单区域 */
      .form-group { display: flex; flex-direction: column; gap: 4px; }
      .form-label { font-size: 11px; color: #888; text-transform: uppercase; letter-spacing: 0.5px; }
      .form-input, .form-select, .form-textarea {
        background: #0f3460;
        border: 1px solid #1a1a4e;
        color: #e0e0e0;
        padding: 8px 10px;
        border-radius: 6px;
        font-size: 13px;
        font-family: inherit;
        outline: none;
        transition: border-color 0.15s;
      }
      .form-input:focus, .form-select:focus, .form-textarea:focus {
        border-color: #e94560;
      }
      .form-textarea { min-height: 60px; resize: vertical; }
      .btn-submit {
        background: #e94560;
        color: #fff;
        border: none;
        padding: 8px 16px;
        border-radius: 6px;
        font-size: 13px;
        font-weight: 600;
        cursor: pointer;
        transition: background 0.15s;
        align-self: flex-end;
      }
      .btn-submit:hover { background: #c73652; }

      /* 提问区域 */
      .prompt-area {
        background: #16213e;
        border-radius: 8px;
        padding: 12px;
        display: flex;
        flex-direction: column;
        gap: 8px;
      }
      .prompt-question { color: #e94560; font-weight: 600; font-size: 13px; }
      .prompt-actions { display: flex; gap: 6px; flex-wrap: wrap; }
      .btn-answer {
        background: #0f3460;
        color: #e0e0e0;
        border: 1px solid #1a1a4e;
        padding: 6px 12px;
        border-radius: 6px;
        font-size: 12px;
        cursor: pointer;
        transition: all 0.15s;
      }
      .btn-answer:hover { border-color: #e94560; color: #e94560; }
      .prompt-free-input {
        display: flex;
        gap: 6px;
      }
      .prompt-free-input .form-input { flex: 1; }
      .btn-send {
        background: #e94560;
        color: #fff;
        border: none;
        padding: 6px 12px;
        border-radius: 6px;
        font-size: 12px;
        cursor: pointer;
      }

      /* 日志区域 */
      .log-area {
        background: #0a0a1a;
        border-radius: 6px;
        padding: 8px;
        max-height: 120px;
        overflow-y: auto;
        font-family: 'Cascadia Code', 'Fira Code', monospace;
        font-size: 11px;
      }
      .log-entry { padding: 2px 0; color: #888; word-break: break-all; }
      .log-entry .log-time { color: #555; margin-right: 6px; }
      .log-empty { color: #444; font-style: italic; text-align: center; padding: 8px; }

      .panel-footer {
        padding: 8px 14px;
        background: #16213e;
        border-top: 1px solid #1a1a2e;
        font-size: 11px;
        color: #555;
        text-align: center;
        flex-shrink: 0;
      }

      /* 滚动条 */
      ::-webkit-scrollbar { width: 4px; }
      ::-webkit-scrollbar-track { background: transparent; }
      ::-webkit-scrollbar-thumb { background: #333; border-radius: 2px; }
    `;
    shadow.appendChild(style);

    panelEl = document.createElement("div");
    panelEl.className = "panel minimized";
    shadow.appendChild(panelEl);

    document.documentElement.appendChild(host);
    render();
  }

  // ── 渲染函数 ─────────────────────────────────────────
  function render() {
    panelEl.innerHTML = "";

    // Header
    const header = el("div", "panel-header");
    header.addEventListener("click", (e) => {
      if (e.target.closest(".btn-icon")) return;
      state.minimized = !state.minimized;
      syncVisibility();
    });

    const icon = el("span", "panel-icon");
    icon.textContent = "🤖";
    header.appendChild(icon);

    const title = el("span", "panel-title");
    title.textContent = state.title;
    title._isTitle = true;
    header.appendChild(title);

    const btns = el("div", "panel-btns");
    const minBtn = el("button", "btn-icon");
    minBtn.textContent = "—";
    minBtn.title = "最小化";
    minBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      state.minimized = true;
      syncVisibility();
    });
    btns.appendChild(minBtn);
    header.appendChild(btns);

    panelEl.appendChild(header);

    // Body
    const body = el("div", "panel-body");

    // Prompt area (if active)
    if (state.currentPrompt) {
      body.appendChild(renderPrompt(state.currentPrompt));
    }

    // Form
    body.appendChild(renderForm());

    // Log area
    body.appendChild(renderLogArea());

    panelEl.appendChild(body);

    // Footer
    const footer = el("div", "panel-footer");
    footer.textContent = "Agentic Playwright MCP";
    panelEl.appendChild(footer);

    syncVisibility();
  }

  function renderForm() {
    const form = el("div");
    form.style.display = "flex";
    form.style.flexDirection = "column";
    form.style.gap = "8px";
    form._isForm = true;

    for (const field of state.fields) {
      const group = el("div", "form-group");
      const label = el("label", "form-label");
      label.textContent = field.label || field.name;
      group.appendChild(label);

      if (field.type === "select" && field.options) {
        const select = el("select", "form-select");
        for (const opt of field.options) {
          const option = document.createElement("option");
          option.value = typeof opt === "string" ? opt : opt.value;
          option.textContent = typeof opt === "string" ? opt : opt.label;
          select.appendChild(option);
        }
        select._fieldName = field.name;
        isolateKeyboard(select);
        group.appendChild(select);
      } else if (field.type === "textarea") {
        const textarea = el("textarea", "form-textarea");
        textarea.placeholder = field.placeholder || "";
        textarea._fieldName = field.name;
        isolateKeyboard(textarea);
        group.appendChild(textarea);
      } else {
        const input = el("input", "form-input");
        input.type = field.type || "text";
        input.placeholder = field.placeholder || "";
        input._fieldName = field.name;
        isolateKeyboard(input);
        group.appendChild(input);
      }

      form.appendChild(group);
    }

    // Submit button
    const submitBtn = el("button", "btn-submit");
    submitBtn.textContent = "提交";
    submitBtn.addEventListener("click", handleSubmit);
    form.appendChild(submitBtn);

    return form;
  }

  function renderPrompt(promptObj) {
    const area = el("div", "prompt-area");

    const q = el("div", "prompt-question");
    q.textContent = promptObj.question;
    area.appendChild(q);

    // Quick answer buttons (if question suggests options)
    const options = extractOptions(promptObj.question);
    if (options.length > 0) {
      const actions = el("div", "prompt-actions");
      for (const opt of options) {
        const btn = el("button", "btn-answer");
        btn.textContent = opt;
        btn.addEventListener("click", () => {
          resolvePrompt(opt);
        });
        actions.appendChild(btn);
      }
      area.appendChild(actions);
    }

    // Free text input
    const freeInput = el("div", "prompt-free-input");
    const input = el("input", "form-input");
    input.placeholder = "输入回答...";
    isolateKeyboard(input);
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.isComposing) {
        resolvePrompt(input.value);
      }
    });
    const sendBtn = el("button", "btn-send");
    sendBtn.textContent = "发送";
    sendBtn.addEventListener("click", () => resolvePrompt(input.value));
    freeInput.appendChild(input);
    freeInput.appendChild(sendBtn);
    area.appendChild(freeInput);

    return area;
  }

  function renderLogArea() {
    const container = el("div");
    container._isLogArea = true;
    container.style.display = "flex";
    container.style.flexDirection = "column";
    container.style.gap = "4px";

    const label = el("div", "form-label");
    label.textContent = "日志";
    container.appendChild(label);

    const logArea = el("div", "log-area");
    logArea._isLog = true;

    if (state.logEntries.length === 0) {
      const empty = el("div", "log-empty");
      empty.textContent = "暂无日志";
      logArea.appendChild(empty);
    } else {
      for (const entry of state.logEntries.slice(-20)) {
        const line = el("div", "log-entry");
        const time = el("span", "log-time");
        time.textContent = entry.time;
        line.appendChild(time);
        line.appendChild(document.createTextNode(entry.text));
        logArea.appendChild(line);
      }
    }

    container.appendChild(logArea);
    return container;
  }

  function renderLogs() {
    if (!shadow) return;
    const logContainer = shadow.querySelector("[_isLogArea]");
    if (!logContainer) return;
    const parent = logContainer.parentNode;
    if (!parent) return;
    const newLog = renderLogArea();
    parent.replaceChild(newLog, logContainer);
    // Auto-scroll
    const logEl = newLog.querySelector("[_isLog]");
    if (logEl) logEl.scrollTop = logEl.scrollHeight;
  }

  function renderTitle() {
    if (!shadow) return;
    const titleEl = shadow.querySelector("[_isTitle]");
    if (titleEl) titleEl.textContent = state.title;
  }

  function syncVisibility() {
    if (!panelEl) return;
    if (state.minimized) {
      panelEl.classList.add("minimized");
    } else {
      panelEl.classList.remove("minimized");
    }
  }

  // ── 交互处理 ─────────────────────────────────────────
  function handleSubmit() {
    const formData = {};
    const inputs = shadow.querySelectorAll("[_fieldName]");
    inputs.forEach((input) => {
      formData[input._fieldName] = input.value;
    });

    const entry = {
      action: "submit",
      value: formData,
      timestamp: Date.now(),
    };
    state.data = entry;
    state.events.push(entry);
    window.__agentic_panel__.log("表单已提交: " + JSON.stringify(formData));
  }

  function resolvePrompt(answer) {
    if (!state.currentPrompt) return;
    state.currentPrompt.resolve(String(answer));
    state.currentPrompt = null;
    showNextPrompt();
    render();
  }

  function showNextPrompt() {
    if (state.promptQueue.length > 0) {
      state.currentPrompt = state.promptQueue.shift();
      state.minimized = false;
      render();
    }
  }

  function extractOptions(question) {
    // 尝试从问题中提取选项，如 "请选择: A/B/C" 或 "[是] [否]"
    const bracketMatches = question.match(/\[([^\]]+)\]/g);
    if (bracketMatches) {
      return bracketMatches.map((m) => m.slice(1, -1));
    }
    const slashMatch = question.match(/[:：]\s*(.+?)(?:\?|？|$)/);
    if (slashMatch && slashMatch[1].includes("/")) {
      return slashMatch[1].split("/").map((s) => s.trim()).filter(Boolean);
    }
    return [];
  }

  // ── 键盘事件隔离 ─────────────────────────────────────
  function isolateKeyboard(el) {
    ["keydown", "keypress", "keyup", "input"].forEach((eventType) => {
      el.addEventListener(eventType, (e) => e.stopPropagation());
    });
  }

  // ── 辅助 ─────────────────────────────────────────────
  function el(tag, className) {
    const elem = document.createElement(tag);
    if (className) elem.className = className;
    return elem;
  }

  // ── 面板存活保护 ─────────────────────────────────────
  function setupSurvival() {
    const observer = new MutationObserver(() => {
      if (!document.getElementById(PANEL_ID)) {
        document.documentElement.appendChild(host);
        window.__agentic_panel__.log("面板已被页面移除，已自动重建");
      }
    });
    observer.observe(document.documentElement, { childList: true });
  }

  // ── 初始化 ───────────────────────────────────────────
  function init() {
    // 等待 DOM 就绪
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", () => {
        createPanel();
        setupSurvival();
      });
    } else {
      createPanel();
      setupSurvival();
    }
  }

  init();
})();
