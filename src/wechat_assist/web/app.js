const $ = (id) => document.getElementById(id);

const state = {
  chat: null,
  polling: true,
  status: null,
  quote: null,
  quoteChat: "",
  suggestQuote: null,
  replyTone: "daily",
};

const TONE_META = {
  daily: { mode: "daily", hint: "最正常的日常微信，像平时聊天，不策略、不装。" },
  dating_tease: { mode: "dating", hint: "制造神秘感或无害的玩笑，若即若离。" },
  dating_care: { mode: "dating", hint: "细腻关心，有温度但有边界，不显得舔狗。" },
  dating_open: { mode: "dating", hint: "用开放式问题把话题接下去。" },
  work_efficient: { mode: "work", hint: "直接给方案，或确认收到。" },
  work_deflect: { mode: "work", hint: "高情商打太极，不伤和气地拒绝或推迟。" },
  work_confirm: { mode: "work", hint: "稳妥的下级对上级回复，把选择权交回对方。" },
  clash_sarcastic: { mode: "clash", hint: "不带脏字地怼回去，点到为止。" },
  clash_distance: { mode: "clash", hint: "礼貌冷处理，把话题收住。" },
};
const TONE_MODE_DEFAULT = {
  daily: "daily",
  dating: "dating_tease",
  work: "work_efficient",
  clash: "clash_sarcastic",
};

const lastToneByMode = { ...TONE_MODE_DEFAULT };

function applyToneUI(value) {
  const tone = TONE_META[value] ? value : "daily";
  const meta = TONE_META[tone];
  state.replyTone = tone;
  $("reply-tone").value = tone;
  lastToneByMode[meta.mode] = tone;
  document.querySelectorAll(".tone-mode").forEach((btn) => {
    btn.classList.toggle("is-on", btn.dataset.mode === meta.mode);
  });
  document.querySelectorAll(".tone-choices").forEach((box) => {
    box.hidden = box.dataset.mode !== meta.mode;
  });
  document.querySelectorAll("input[name='tone-opt']").forEach((input) => {
    input.checked = input.value === tone;
  });
  $("tone-hint").textContent = meta.hint;
}

async function persistTone(value) {
  applyToneUI(value);
  try {
    await api("/api/settings", { method: "PUT", body: JSON.stringify({ reply_tone: state.replyTone }) });
  } catch (err) {
    $("action-note").textContent = err.message;
  }
}

function setPill(id, ok, warnText, okText, badText) {
  const el = $(id);
  el.classList.remove("ok", "bad", "warn");
  if (ok === true) {
    el.classList.add("ok");
    el.textContent = okText;
  } else if (ok === "warn") {
    el.classList.add("warn");
    el.textContent = warnText;
  } else {
    el.classList.add("bad");
    el.textContent = badText;
  }
}

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = data.detail || data.error || res.statusText;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return data;
}

function quoteKey(m) {
  return `${m.sender_name || ""}\n${m.text || ""}\n${m.quote_text || ""}`;
}

function isPicked(m) {
  return state.quote && quoteKey(state.quote) === quoteKey(m);
}

function chatKey(name) {
  return String(name || "").trim().toLowerCase().replace(/\s+/g, " ");
}

function clearQuote() {
  state.quote = null;
  state.quoteChat = "";
  state.suggestQuote = null;
  updateQuoteBanner();
}

function syncQuoteButton() {
  const btn = $("btn-clear-quote");
  const on = Boolean(state.quote);
  btn.hidden = !on;
  btn.classList.toggle("hidden", !on);
}

function dropQuoteIfChatChanged(chat) {
  const incoming = chatKey(chat.chat_name);
  if (!incoming) return;
  const previous = chatKey(state.chat?.chat_name);
  const bound = chatKey(state.quoteChat);
  const from = bound || previous;
  if ((state.quote || state.suggestQuote) && from && from !== incoming) {
    clearQuote();
    return;
  }
  if (state.quote && !bound) {
    state.quoteChat = chat.chat_name;
  }
}

function updateQuoteBanner() {
  const banner = $("quote-banner");
  const q = state.quote;
  syncQuoteButton();
  if (!q) {
    banner.textContent = "点左侧一条消息，可针对它生成建议，发送时也会在微信里引用。";
    return;
  }
  const who = q.sender_name || (q.sender === "ME" ? "Me" : "未知");
  const preview = (q.text || "").slice(0, 40);
  banner.textContent = `将引用 ${who}：${preview}${(q.text || "").length > 40 ? "…" : ""}`;
}

function renderMessages(chat) {
  $("chat-name").textContent = chat.chat_name || "未识别当前聊天";
  $("chat-note").textContent = chat.note || (chat.messages?.length ? "来自当前微信窗口的可见消息。" : "请把微信聊天窗口放到前台。");
  const box = $("messages");
  if (!chat.messages || chat.messages.length === 0) {
    box.innerHTML = `<div class="empty-state">${chat.note || "暂无消息"}</div>`;
    updateQuoteBanner();
    return;
  }
  box.innerHTML = chat.messages
    .map((m, i) => {
      const cls = m.sender === "ME" ? "me" : "other";
      const picked = isPicked(m) ? " picked" : "";
      const who = m.sender_name || (m.sender === "ME" ? "Me" : "未知");
      let quote = "";
      if (m.quote_text) {
        const qWho = m.quote_sender || "未知";
        quote = `<div class="quote">回复 ${escapeHtml(qWho)}：${escapeHtml(m.quote_text)}</div>`;
      }
      return `<div class="bubble ${cls}${picked}" data-idx="${i}"><span class="who">${escapeHtml(who)}</span>${quote}${escapeHtml(m.text)}</div>`;
    })
    .join("");
  box.querySelectorAll(".bubble").forEach((el) => {
    el.addEventListener("click", () => {
      const idx = Number(el.dataset.idx);
      const msg = chat.messages[idx];
      if (!msg) return;
      state.quote = isPicked(msg) ? null : msg;
      state.quoteChat = state.quote ? (chat.chat_name || "") : "";
      if (!state.quote) state.suggestQuote = null;
      renderMessages(chat);
      box.scrollTop = box.scrollHeight;
    });
  });
  box.scrollTop = box.scrollHeight;
  updateQuoteBanner();
}

function escapeHtml(text) {
  return String(text)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function suggestionBubbles(item) {
  const fromList = (item.messages || []).map((m) => String(m || "").trim()).filter(Boolean);
  if (fromList.length) return fromList;
  const text = String(item.text || "").trim();
  return text ? [text] : [];
}

function renderSuggestions(items, chatName) {
  const box = $("suggestions");
  if (!items?.length) {
    box.classList.add("empty-state");
    box.textContent = "没有生成出建议。";
    return;
  }
  box.classList.remove("empty-state");
  box.innerHTML = items
    .map((item, i) => {
      const bubbles = suggestionBubbles(item);
      const count = bubbles.length > 1 ? ` · ${bubbles.length}条` : "";
      const fields = bubbles
        .map((text, bi) => {
          const label = bubbles.length > 1 ? `<span>第 ${bi + 1} 条</span>` : "";
          return `<label class="bubble-edit">${label}<textarea data-bubble="${bi}">${escapeHtml(text)}</textarea></label>`;
        })
        .join("");
      return `
        <article class="card" data-index="${i}">
          <span class="tone">${escapeHtml(item.tone || "建议")}${count}</span>
          ${fields}
          <div class="card-actions">
            <button class="primary send" type="button" data-enter="1">发送到微信</button>
            <button class="ghost fill" type="button" data-enter="0">只填入输入框</button>
          </div>
        </article>`;
    })
    .join("");
  box.querySelectorAll("button").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const card = btn.closest(".card");
      const messages = [...card.querySelectorAll("textarea")]
        .map((el) => el.value.trim())
        .filter(Boolean);
      const pressEnter = btn.dataset.enter === "1";
      if (!messages.length) return;
      if (pressEnter) {
        const quoting = state.suggestQuote || state.quote;
        const extra = quoting ? "\n第一句会先在微信里引用所选消息。" : "";
        const preview = messages.map((m, i) => (messages.length > 1 ? `${i + 1}. ${m}` : m)).join("\n\n");
        const ok = window.confirm(
          `将把下面 ${messages.length} 条依次发送到「${chatName}」：\n\n${preview}${extra}\n\n确定？助手不会自动连发下一轮。`
        );
        if (!ok) return;
      }
      $("action-note").textContent = pressEnter
        ? (messages.length > 1 ? `正在依次发送 ${messages.length} 条…` : "正在发送…")
        : "正在填入输入框…";
      try {
        const result = await api("/api/send", {
          method: "POST",
          body: JSON.stringify({
            text: messages.join("\n"),
            messages,
            chat_name: chatName,
            press_enter: pressEnter,
            quote: state.suggestQuote || state.quote || null,
          }),
        });
        if (result.warning) {
          $("action-note").textContent = result.warning;
        } else if (result.sent) {
          const n = result.sent_count || messages.length;
          $("action-note").textContent = result.quoted
            ? `已引用所选消息，并依次发出 ${n} 条。`
            : (n > 1 ? `已依次通过微信官方客户端发出 ${n} 条。` : "已通过微信官方客户端发出。");
        } else {
          $("action-note").textContent = "已写入输入框，请你在微信里确认后按回车。";
        }
      } catch (err) {
        $("action-note").textContent = err.message;
      }
    });
  });
}

async function refreshStatus() {
  try {
    const s = await api("/api/status");
    state.status = s;
    setPill("pill-ax", s.ax_trusted, "辅助功能", "辅助功能已开", "需要辅助功能权限");
    setPill("pill-wechat", s.wechat_running, "微信", "微信运行中", "微信未打开");
    setPill("pill-ai", s.has_api_key, "AI", "AI 已配置", "未配置 API");
    if (s.reply_tone) applyToneUI(s.reply_tone);
    return s;
  } catch (err) {
    setPill("pill-ax", false, "", "", "服务未连接");
    return null;
  }
}

async function refreshChat() {
  const chat = await api("/api/chat/current");
  dropQuoteIfChatChanged(chat);
  state.chat = chat;
  renderMessages(chat);
}

async function generate() {
  $("btn-suggest").disabled = true;
  state.suggestQuote = state.quote;
  const intent = ($("user-intent").value || "").trim();
  $("action-note").textContent = intent
    ? "正在按你想说的结合当前聊天生成建议…"
    : state.quote
      ? "正在按你选中的消息生成引用回复…"
      : "正在根据当前聊天生成建议…聊天内容只发往你配置的 AI 接口。";
  try {
    const data = await api("/api/suggest", {
      method: "POST",
      body: JSON.stringify({
        quote: state.quote,
        tone: $("reply-tone").value,
        intent,
      }),
    });
    renderSuggestions(data.suggestions, data.chat_name);
    $("user-intent").value = "";
    const bits = [`已为「${data.chat_name}」生成 ${data.suggestions.length} 套备选`];
    if (data.used_intent) bits.push("已结合你想说的");
    if (data.quoted) bits.push("发送时会在微信里引用所选消息");
    $("action-note").textContent = bits.join("。") + "。";
  } catch (err) {
    $("action-note").textContent = err.message;
  } finally {
    $("btn-suggest").disabled = false;
  }
}

function fillForm(settings) {
  const form = $("settings-form");
  for (const [key, value] of Object.entries(settings)) {
    const field = form.elements[key];
    if (!field) continue;
    if (field.type === "checkbox") field.checked = Boolean(value);
    else field.value = value ?? "";
  }
  if (settings.reply_tone) applyToneUI(settings.reply_tone);
}

async function openSettings() {
  const settings = await api("/api/settings");
  fillForm(settings);
  $("settings-mask").classList.remove("hidden");
}

function closeSettings() {
  $("settings-mask").classList.add("hidden");
}

$("btn-refresh").addEventListener("click", () => refreshChat().catch((e) => {
  $("chat-note").textContent = e.message;
}));
$("btn-permission").addEventListener("click", async () => {
  try {
    const result = await api("/api/permission", { method: "POST" });
    $("chat-note").textContent = result.ax_trusted
      ? "辅助功能已授权。"
      : result.hint || "请把「微信回复助手」加进辅助功能后再重启助手。";
    await refreshStatus();
    await refreshChat();
  } catch (err) {
    $("chat-note").textContent = err.message;
  }
});
$("btn-ax-settings").addEventListener("click", async () => {
  try {
    await api("/api/permission/open-settings", { method: "POST" });
    const target = state.status?.launcher_app || state.status?.ax_target;
    $("chat-note").textContent = target
      ? `已尝试打开系统设置。请打开「微信回复助手」（或添加）：\n${target}\n打开开关后完全退出助手再打开一次。`
      : "已尝试打开系统设置。请勾选「微信回复助手」，只勾选 Cursor 在关掉 Cursor 后会失效。";
  } catch (err) {
    $("chat-note").textContent = err.message;
  }
});
const PROVIDER_PRESETS = {
  gemini: {
    api_base: "",
    model: "gemini-3.6-flash",
  },
  openai: {
    api_base: "",
    model: "gpt-4o-mini",
  },
  anthropic: {
    api_base: "",
    model: "claude-3-5-sonnet-latest",
  },
  ollama: {
    api_base: "http://127.0.0.1:11434/v1",
    model: "llama3.1",
  },
  custom: {
    api_base: "",
    model: "",
  },
};

$("provider").addEventListener("change", (e) => {
  const preset = PROVIDER_PRESETS[e.target.value];
  if (!preset) return;
  const form = $("settings-form");
  const currentModel = form.model.value.trim();
  const looksDefault =
    !currentModel ||
    /^(gpt-4o-mini|gemini-2\.5-flash|gemini-3\.6-flash|claude-3-5-sonnet-latest|llama3\.1)$/.test(currentModel);
  if (looksDefault && preset.model) form.model.value = preset.model;
  if (!form.api_base.value.trim() && preset.api_base) form.api_base.value = preset.api_base;
});
$("btn-suggest").addEventListener("click", generate);
document.querySelectorAll(".tone-mode").forEach((btn) => {
  btn.addEventListener("click", () => {
    const mode = btn.dataset.mode;
    persistTone(lastToneByMode[mode] || TONE_MODE_DEFAULT[mode]);
  });
});
document.querySelectorAll("input[name='tone-opt']").forEach((input) => {
  input.addEventListener("change", () => {
    if (input.checked) persistTone(input.value);
  });
});
$("btn-clear-quote").addEventListener("click", () => {
  clearQuote();
  if (state.chat) renderMessages(state.chat);
});
$("btn-settings").addEventListener("click", () => openSettings().catch((e) => alert(e.message)));
$("btn-close-settings").addEventListener("click", closeSettings);
$("settings-mask").addEventListener("click", (e) => {
  if (e.target.id === "settings-mask") closeSettings();
});
$("settings-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = e.currentTarget;
  const body = {
    provider: form.provider.value,
    api_key: form.api_key.value,
    api_base: form.api_base.value,
    model: form.model.value,
    n_suggestions: Number(form.n_suggestions.value),
    context_messages: Number(form.context_messages.value),
    reply_tone: form.reply_tone.value,
    system_style: form.system_style.value,
    anonymize_names: form.anonymize_names.checked,
    include_chat_name: form.include_chat_name.checked,
    send_mode: form.send_mode.value,
    min_send_interval_seconds: Number(form.min_send_interval_seconds.value),
    max_sends_per_hour: Number(form.max_sends_per_hour.value),
  };
  await api("/api/settings", { method: "PUT", body: JSON.stringify(body) });
  applyToneUI(body.reply_tone);
  closeSettings();
  refreshStatus();
  $("action-note").textContent = "设置已保存到本机。";
});

async function loop() {
  await refreshStatus();
  try {
    await refreshChat();
  } catch (err) {
    $("chat-note").textContent = err.message;
  }
  setTimeout(loop, 4000);
}

loop();
