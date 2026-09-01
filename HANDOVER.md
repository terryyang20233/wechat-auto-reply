# Hand-over prompt

把下面整段复制给下一个 Agent / 协作者，即可从当前进度继续。不要把本机 `~/.wechat-assist/settings.json`、API Key、聊天原文或 `/api/diagnostics/ax` 的完整 dump 贴进对话或 Issue。

---

You are continuing a local macOS project: a **WeChat AI reply assistant** (not an auto-bot).

## Goal and hard constraints

- Read the **currently open** WeChat for Mac chat, call the user’s own AI API for several reply options, and send a chosen reply into **official WeChat only after the user clicks**.
- **Privacy:** no project cloud; do not log or store chats; anonymize names before the model; API keys live only in `~/.wechat-assist/settings.json` (mode 600). User “我想说的” notes are **not** persisted; they go to the model only for that generate, after name scrub.
- **Ban-risk:** Accessibility API + official client only. No WeChat web/iPad protocol, WeChatFerry, process injection, DB decrypt, or SIP-off memory scraping. No auto-send without a click. Rate limits: 8s min interval **between user-initiated send bursts**, 20/hour (configurable). Optional fill-only (user hits Enter). Intra-burst bubbles from **one** confirmed click use a short human delay, not the full 8s gap; each bubble still counts toward the hourly cap.
- Local UI at `http://127.0.0.1:8765` only.

## Stack

- Python 3.11+ / FastAPI / uvicorn, package `src/wechat_assist/`
- WeChat I/O: macOS Accessibility (pyobjc), not unofficial protocols
- UI: vanilla `src/wechat_assist/web/{index.html,styles.css,app.js}`
- Run: `python -m wechat_assist` (no uvicorn reload). After **Python** changes, restart the process. Static HTML/JS/CSS are served from disk; a hard refresh is enough for UI-only edits.

## What already works

- Read the **main chat** via `AXTable` whose **description is `Messages`** (not title). Do **not** scrape the `Chats` table (that produced chrome like “Hide Stickied Chats”).
- Cell **description** patterns (English WeChat 3.8.x): `MeSaid:text`, `NameSaid:text`, `MeSaid:reply,quoted,Name: original`, `Me:Sent aPhoto`, `System Message:…`, timestamps including `Today`, `08/20`, `20:44`, `Yesterday 22:12`, `Jul 31, 2026 00:29`.
- Chat name from the **selected Chats row** (first comma field of cell description).
- Input: prefer `AXTextArea`, not the left search `AXTextField`.
- UI shows real nicknames; AI gets `我 / 对方` (1:1) or `成员1, 成员2…` (groups). Own messages display as `Me`.
- Gemini provider uses native generateContent; new-user accounts may reject `gemini-2.5-flash` → use `gemini-3.6-flash` (user may also have `gemini-3.5-flash-lite` in local settings).
- **Quote flow:** click a bubble in the assistant UI → generate with that message as the reply target → on send, right-click the matching WeChat bubble, choose Quote/引用 (fallback Reply/回复), then fill/send. If quote was requested and the menu fails, **abort** (do not send unquoted). Quote applies to the **first** bubble only when sending a multi-bubble pack.
- **Clear quote on chat switch:** `state.quoteChat` + previous `chat_name`; `dropQuoteIfChatChanged` before assigning `state.chat`. Same-chat 4s poll must **keep** the selection (`quoteKey`). Empty incoming `chat_name` must not wipe the quote. 「取消引用」 is **hidden** unless a quote is selected (`hidden` attribute + `.hidden`).
- **Reply tone:** `reply_tone` in settings and the generate panel (`natural` / `concise` / `friendly` / `professional` / `warm` / `humorous` / `firm` / `varied`). Extra free-text is `system_style`.
- **User intent:** optional `#user-intent` (max 800). POST `/api/suggest` field `intent`. Scrub via `privacy.scrub_user_note`.
- **Multi-bubble suggestions:** each suggestion is `{tone, messages[], text}`. `MAX_BUBBLES = 3`. Prompt requires, when `n_suggestions >= 2`, at least one 1-bubble pack and at least one 2–3 bubble pack (models otherwise always emit length 1). POST `/api/send` accepts `messages: string[]`; fill-only fills **only the first** bubble. Confirm once, then send in order.
- Accessibility: granting Cursor is not enough. Add **微信回复助手** (`/Applications/微信回复助手.app`) and/or **Python.app**, then restart the assistant.
- Docs: English `README.md` + `README.zh.md`. Remote: `https://github.com/terryyang20233/wechat-auto-reply`. MIT `LICENSE` still has no personal copyright name.

## Important bugs already fixed (do not regress)

1. Full AX tree walk hung — skip web areas, cap nodes, don’t fetch AXValue/geometry on every node; cache snapshots ~1.5s.
2. Wrong message source — Messages table + cell `description` only.
3. Timestamps — `TIMESTAMP_RE` must allow date + time together (`Yesterday 22:12`).
4. Quoted replies in AX — parse `,quoted,Name: original` into `quote_sender` / `quote_text`.
5. AX coordinates were garbage — `str(AXValue)` includes a hex pointer. Unpack with `AXValueGetValue` + `kAXValueCGPointType` / `kAXValueCGSizeType` before clicking.
6. `AXShowMenu` may fail (`-25204`); quote uses real CGPoint right-click, then find `AXMenuItem`. Collect menu items **without walking `AXTable`**, or the 250-node cap never reaches the popup.
7. Quote leaked across chats after switching conversations — clear on `chat_name` change only, not on every poll.
8. Models ignored multi-bubble unless the prompt **required** a mix of 1-bubble and 2–3-bubble packs; JSON example must show a multi-element `messages` array first. Do not describe N **packs** as N 「条」.

## Key files

- `src/wechat_assist/app.py` — FastAPI: `/api/chat/current`, `/api/suggest` (`intent`), `/api/send` (`messages[]`), `/api/ai/test`, `/api/settings`
- `src/wechat_assist/wechat/reader.py` — parse AX, timestamps, quotes, names, `find_message_button`
- `src/wechat_assist/wechat/sender.py` — fill/send + quote menu (one text at a time)
- `src/wechat_assist/wechat/ax.py` — AX helpers, CGPoint unpack, right-click, `collect_menu_items`
- `src/wechat_assist/ai/suggest.py` — Gemini native + OpenAI-compat + Anthropic; tones; intent; `messages[]` parse (`MAX_BUBBLES`)
- `src/wechat_assist/privacy.py` — 我/对方 vs 成员N; `scrub_user_note`
- `src/wechat_assist/safety.py` — `SendGuard.check(..., n_sends=, enforce_interval=)`
- `src/wechat_assist/config.py` — `reply_tone`, `system_style`
- `src/wechat_assist/web/app.js` — poll ~4s; `quoteKey` survives re-render; `dropQuoteIfChatChanged`; intent; multi-bubble cards

## Known fragility / next work

- Quote depends on visible bubbles, English/Chinese menu labels, and correct geometry. If WeChat UI changes, dump **menu item titles only** after a right-click — never paste real chat text into tickets.
- Duplicate identical messages: `find_message_button` uses the last matching row.
- UI is English-WeChat-biased (`Me`, `Messages`, `Chats`). Chinese UI needs parallel labels (already partially present).
- No tests. No Windows/Android.
- `/api/diagnostics/ax` can include message text in descriptions — treat dumps as sensitive.
- Multi-bubble is prompt-enforced; a stubborn model can still emit all length-1. Do not log raw model JSON if it contains chat text.
- Keep `HANDOVER.md` off a public default branch if you want less copy-paste of Accessibility internals. Repo name `wechat-auto-reply` still reads like an auto-bot.

## Do not

- Print or commit real chat text, API keys, or `settings.json`.
- Add protocol bots, hooks, or auto-send without a click.
- Force-push or rewrite published history that might have leaked secrets (this initial repo should be clean).
