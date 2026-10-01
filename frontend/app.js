"use strict";

(() => {
  /* ================= STATE ================= */
  const state = {
    selectedAI: "auto",
    compareMode: false,
    providers: [],
    chats: [],
    currentChatId: null,
    pending: false,
  };

  const $ = (id) => document.getElementById(id);
  const DOM = {
    chat: $("chat"),
    emptyState: $("emptyState"),
    textarea: $("query"),
    chatHistory: $("chatHistory"),
    providerToggle: $("providerToggle"),
    compareToggle: $("compareToggle"),
    sendBtn: $("sendBtn"),
    micBtn: $("micBtn"),
    searchInput: $("searchInput"),
    newChatBtn: $("newChatBtn"),
  };

  /* ================= HELPERS ================= */
  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function currentChat() {
    return state.chats.find((c) => c.id === state.currentChatId);
  }

  function providerLabel(name) {
    const p = state.providers.find((x) => x.name === name);
    return p ? p.display_name : name;
  }

  function scrollToBottom() {
    DOM.chat.scrollTop = DOM.chat.scrollHeight;
  }

  /* Markdown is always sanitized before it touches the DOM. */
  function renderMarkdown(target, text) {
    if (window.marked && window.DOMPurify) {
      const html = window.marked.parse(text, { gfm: true, breaks: true });
      target.innerHTML = window.DOMPurify.sanitize(html, {
        FORBID_TAGS: ["style"],
        FORBID_ATTR: ["style", "id", "name", "class"],
      });
    } else {
      target.textContent = text;
    }
  }

  function initSanitizer() {
    if (!window.DOMPurify) return;
    window.DOMPurify.addHook("afterSanitizeAttributes", (node) => {
      if (node.tagName === "A") {
        node.setAttribute("target", "_blank");
        node.setAttribute("rel", "noopener noreferrer");
      }
    });
  }

  /* ================= API ================= */
  async function postJSON(url, payload) {
    let res;
    try {
      res = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
    } catch {
      throw new Error("Could not reach the server. Is it running?");
    }

    let data = null;
    try {
      data = await res.json();
    } catch {
      /* non-JSON body: fall through to the generic message */
    }
    if (!res.ok) {
      const message = data && data.error && data.error.message;
      throw new Error(message || `Request failed (${res.status}).`);
    }
    return data;
  }

  function askProvider(query, choice, failover) {
    return postJSON("/ask", { query, ai_choice: choice, failover });
  }

  async function generateTitle(text) {
    try {
      const data = await postJSON("/generate-title", { text });
      return data.title || text.slice(0, 30);
    } catch {
      return text.slice(0, 30);
    }
  }

  async function loadProviders() {
    try {
      const res = await fetch("/providers");
      const data = await res.json();
      state.providers = Array.isArray(data.providers) ? data.providers : [];
    } catch {
      state.providers = [];
    }
    renderProviderToggle();
  }

  /* ================= PROVIDER TOGGLE ================= */
  function renderProviderToggle() {
    DOM.providerToggle.replaceChildren();

    const options = [{ name: "auto", display_name: "Auto", available: true }, ...state.providers];
    const selectable = options.find((o) => o.name === state.selectedAI && o.available);
    if (!selectable) state.selectedAI = "auto";

    options.forEach((p) => {
      const btn = el("button", "ai-option", p.display_name);
      btn.type = "button";
      btn.dataset.model = p.name;
      btn.disabled = !p.available;
      if (!p.available) btn.title = "Not configured on this server";
      btn.classList.toggle("active", p.name === state.selectedAI);
      btn.setAttribute("aria-pressed", String(p.name === state.selectedAI));
      btn.addEventListener("click", () => {
        state.selectedAI = p.name;
        renderProviderToggle();
      });
      DOM.providerToggle.appendChild(btn);
    });
  }

  function toggleCompare() {
    state.compareMode = !state.compareMode;
    DOM.compareToggle.classList.toggle("active", state.compareMode);
    DOM.compareToggle.setAttribute("aria-pressed", String(state.compareMode));
  }

  /* ================= CHAT LIST ================= */
  function newChat() {
    const existing = currentChat();
    if (existing && existing.messages.length === 0) {
      showChat(existing.id);
      return;
    }
    const id = Date.now();
    state.chats.push({ id, title: "New Chat", pinned: false, messages: [] });
    state.currentChatId = id;
    renderHistory();
    showChat(id);
  }

  function renderHistory() {
    const filter = DOM.searchInput.value.trim().toLowerCase();
    DOM.chatHistory.replaceChildren();

    [...state.chats]
      .sort((a, b) => Number(b.pinned) - Number(a.pinned))
      .filter((chat) => !filter || chat.title.toLowerCase().includes(filter))
      .forEach((chat) => DOM.chatHistory.appendChild(createChatItem(chat)));
  }

  function createChatItem(chat) {
    const item = el("div", "chat-item");
    item.classList.toggle("active", chat.id === state.currentChatId);

    const title = el("div", "chat-title", (chat.pinned ? "📌 " : "") + chat.title);
    title.addEventListener("click", () => showChat(chat.id));

    const actions = el("div", "chat-actions");
    actions.append(
      createAction("📌", "Pin chat", () => togglePin(chat.id)),
      createAction("🗑", "Delete chat", () => deleteChat(chat.id))
    );

    item.append(title, actions);
    return item;
  }

  function createAction(icon, label, handler) {
    const btn = el("button", "", icon);
    btn.type = "button";
    btn.title = label;
    btn.setAttribute("aria-label", label);
    btn.addEventListener("click", (event) => {
      event.stopPropagation();
      handler();
    });
    return btn;
  }

  function togglePin(id) {
    const chat = state.chats.find((c) => c.id === id);
    if (chat) chat.pinned = !chat.pinned;
    renderHistory();
  }

  function deleteChat(id) {
    state.chats = state.chats.filter((c) => c.id !== id);
    if (state.currentChatId !== id) {
      renderHistory();
    } else if (state.chats.length) {
      showChat(state.chats[state.chats.length - 1].id);
    } else {
      state.currentChatId = null;
      newChat();
    }
  }

  function showChat(id) {
    state.currentChatId = id;
    const chat = currentChat();
    DOM.chat.querySelectorAll(".message, .compare-container, .typing").forEach((n) => n.remove());
    DOM.emptyState.hidden = Boolean(chat && chat.messages.length);
    if (chat) chat.messages.forEach((m) => DOM.chat.appendChild(buildMessage(m)));
    renderHistory();
    scrollToBottom();
  }

  /* ================= MESSAGES ================= */
  function metaText(meta) {
    if (!meta) return "";
    const parts = [providerLabel(meta.provider)];
    if (typeof meta.latency_ms === "number") parts.push(`${(meta.latency_ms / 1000).toFixed(1)} s`);
    if (meta.fallback_used) parts.push("fallback used");
    return parts.join(" · ");
  }

  function buildMessage(m) {
    if (m.role === "compare") return buildCompare(m);

    const node = el("div", `message ${m.role}`);
    if (m.role === "ai") {
      const body = el("div", "message-body");
      renderMarkdown(body, m.text);
      node.appendChild(body);
      if (m.meta) node.appendChild(el("div", "meta", metaText(m.meta)));
    } else {
      node.textContent = m.text;
    }
    return node;
  }

  function fillCompareBox(box, item) {
    box.replaceChildren(el("div", "compare-title", providerLabel(item.provider).toUpperCase()));
    const content = el("div", "message-body");
    if (item.error) {
      box.classList.add("failed");
      content.textContent = item.error;
    } else if (item.text) {
      renderMarkdown(content, item.text);
      if (item.meta) content.appendChild(el("div", "meta", metaText(item.meta)));
    } else {
      content.textContent = "...";
    }
    box.appendChild(content);
  }

  function buildCompare(m) {
    const container = el("div", "compare-container");
    m.items.forEach((item) => {
      const box = el("div", "compare-box");
      fillCompareBox(box, item);
      item.box = box;
      container.appendChild(box);
    });
    return container;
  }

  function addMessage(message) {
    const chat = currentChat();
    if (!chat) return null;
    chat.messages.push(message);
    DOM.emptyState.hidden = true;
    const node = buildMessage(message);
    DOM.chat.appendChild(node);
    scrollToBottom();
    return node;
  }

  function showTyping() {
    const t = el("div", "typing");
    t.id = "typing";
    t.append(el("span"), el("span"), el("span"));
    DOM.chat.appendChild(t);
    scrollToBottom();
  }

  function removeTyping() {
    const t = $("typing");
    if (t) t.remove();
  }

  /* ================= SEND ================= */
  async function titleFirstMessage(chat, text) {
    chat.title = "Generating...";
    renderHistory();
    chat.title = await generateTitle(text);
    renderHistory();
  }

  async function sendQuery() {
    const query = DOM.textarea.value.trim();
    if (!query || state.pending) return;

    const chat = currentChat();
    state.pending = true;
    DOM.sendBtn.disabled = true;
    DOM.textarea.value = "";
    autoGrow();

    addMessage({ role: "user", text: query });
    if (chat && chat.messages.length === 1) titleFirstMessage(chat, query);

    showTyping();
    try {
      if (state.compareMode) {
        await runCompare(query);
      } else {
        const data = await askProvider(query, state.selectedAI, true);
        removeTyping();
        addMessage({
          role: "ai",
          text: data.response,
          meta: { provider: data.provider, latency_ms: data.latency_ms, fallback_used: data.fallback_used },
        });
      }
    } catch (err) {
      removeTyping();
      addMessage({ role: "error", text: err.message });
    } finally {
      removeTyping();
      state.pending = false;
      DOM.sendBtn.disabled = false;
      DOM.textarea.focus();
    }
  }

  async function runCompare(query) {
    const targets = state.providers.filter((p) => p.available).map((p) => p.name);
    if (!targets.length) throw new Error("No providers are available to compare.");

    removeTyping();
    const message = { role: "compare", items: targets.map((provider) => ({ provider })) };
    addMessage(message);

    await Promise.all(
      message.items.map(async (item) => {
        try {
          const data = await askProvider(query, item.provider, false);
          item.text = data.response;
          item.meta = { provider: data.provider, latency_ms: data.latency_ms, fallback_used: false };
        } catch (err) {
          item.error = err.message;
        }
        if (item.box) fillCompareBox(item.box, item);
        scrollToBottom();
      })
    );
  }

  /* ================= INPUT ================= */
  function autoGrow() {
    DOM.textarea.style.height = "auto";
    DOM.textarea.style.height = `${Math.min(DOM.textarea.scrollHeight, 160)}px`;
  }

  function bindVoiceInput() {
    const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!Recognition) return;
    DOM.micBtn.hidden = false;
    DOM.micBtn.addEventListener("click", () => {
      try {
        const recognition = new Recognition();
        recognition.lang = navigator.language || "en-US";
        recognition.onresult = (event) => {
          const spoken = event.results[0][0].transcript;
          DOM.textarea.value = `${DOM.textarea.value} ${spoken}`.trim();
          autoGrow();
        };
        recognition.start();
      } catch {
        /* recognition already running or unavailable */
      }
    });
  }

  function bindEvents() {
    DOM.sendBtn.addEventListener("click", sendQuery);
    DOM.newChatBtn.addEventListener("click", newChat);
    DOM.compareToggle.addEventListener("click", toggleCompare);
    DOM.searchInput.addEventListener("input", renderHistory);
    DOM.textarea.addEventListener("input", autoGrow);
    DOM.textarea.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        sendQuery();
      }
    });
    document.querySelectorAll(".chip").forEach((chip) => {
      chip.addEventListener("click", () => {
        DOM.textarea.value = chip.dataset.prompt || "";
        DOM.textarea.focus();
        autoGrow();
      });
    });
    bindVoiceInput();
  }

  /* ================= INIT ================= */
  initSanitizer();
  bindEvents();
  renderProviderToggle();
  newChat();
  loadProviders();
})();
