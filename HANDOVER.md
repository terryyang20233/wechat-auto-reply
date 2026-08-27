# Hand-over prompt

把下面整段复制给下一个 Agent / 协作者，即可从当前进度继续。不要把本机 `~/.wechat-assist/settings.json`、API Key、聊天原文或 `/api/diagnostics/ax` 的完整 dump 贴进对话或 Issue。

---

You are continuing a local macOS project: a **WeChat AI reply assistant** (not an auto-bot).

## Goal and hard constraints

- Read the **currently open** WeChat for Mac chat, call the user’s own AI API for several reply options, and send a chosen reply into **official WeChat only after the user clicks**.
- **Privacy:** no project cloud; do not log or store chats; anonymize names before the model; API keys live only in `~/.wechat-assist/settings.json` (mode 600).
- **Ban-risk:** Accessibility API + official client only. No WeChat web/iPad protocol, WeChatFerry, process injection, DB decrypt, or SIP-off memory scraping. No auto-send without a click. Rate limits: 8s min interval, 20/hour (configurable). Optional fill-only (user hits Enter).
- Local UI at `http://127.0.0.1:8765` only.

## Stack

- Python 3.11+ / FastAPI / uvicorn, package `src/wechat_assist/`
- WeChat I/O: macOS Accessibility (pyobjc), not unofficial protocols
- UI: vanilla `src/wechat_assist/web/{index.html,styles.css,app.js}`
- Run: `python -m wechat_assist` (no uvicorn reload). After code changes, restart the process.

## What already works

- Read the **main chat** via `AXTable` whose **description is `Messages`** (not title). Do **not** scrape the `Chats` table (that produced chrome like “Hide Stickied Chats”).
- Cell **description** patterns (English WeChat 3.8.x): `MeSaid:text`, `NameSaid:text`, `MeSaid:reply,quoted,Name: original`, `Me:Sent aPhoto`, `System Message:…`, timestamps including `Today`, `08/20`, `20:44`, `Yesterday 22:12`, `Jul 31, 2026 00:29`.
- Chat name from the **selected Chats row** (first comma field of cell description).
- Input: prefer `AXTextArea`, not the left search `AXTextField`.
- UI shows real nicknames; AI gets `我 / 对方` (1:1) or `成员1, 成员2…` (groups). Own messages display as `Me`.
- Gemini provider uses native generateContent; new-user accounts may reject `gemini-2.5-flash` → use `gemini-3.6-flash`.
- **Quote flow:** click a bubble in the assistant UI → generate with that message as the reply target → on send, right-click the matching WeChat bubble, choose Quote/引用 (fallback Reply/回复), then fill/send. If quote was requested and the menu fails, **abort** (do not send unquoted).
- Accessibility: granting Cursor is not enough. Add **Python.app**, e.g. `/Library/Frameworks/Python.framework/Versions/3.12/Resources/Python.app`, then restart the assistant.

## Important bugs already fixed (do not regress)

1. Full AX tree walk hung — skip web areas, cap nodes, don’t fetch AXValue/geometry on every node; cache snapshots ~1.5s.
2. Wrong message source — Messages table + cell `description` only.
3. Timestamps — `TIMESTAMP_RE` must allow date + time together (`Yesterday 22:12`).
4. Quoted replies in AX — parse `,quoted,Name: original` into `quote_sender` / `quote_text`.
5. AX coordinates were garbage — `str(AXValue)` includes a hex pointer. Unpack with `AXValueGetValue` + `kAXValueCGPointType` / `kAXValueCGSizeType` before clicking.
6. `AXShowMenu` may fail (`-25204`); quote uses real CGPoint right-click, then find `AXMenuItem`. Collect menu items **without walking `AXTable`**, or the 250-node cap never reaches the popup.

## Key files

- `src/wechat_assist/app.py` — FastAPI: `/api/chat/current`, `/api/suggest`, `/api/send`, `/api/ai/test`, `/api/settings`
- `src/wechat_assist/wechat/reader.py` — parse AX, timestamps, quotes, names, `find_message_button`
- `src/wechat_assist/wechat/sender.py` — fill/send + quote menu
- `src/wechat_assist/wechat/ax.py` — AX helpers, CGPoint unpack, right-click, `collect_menu_items`
- `src/wechat_assist/ai/suggest.py` — Gemini native + OpenAI-compat + Anthropic
- `src/wechat_assist/privacy.py` — 我/对方 vs 成员N; scrub names in body
- `src/wechat_assist/web/app.js` — poll ~4s; quote selection must survive re-render via `quoteKey`

## Known fragility / next work

- Quote depends on visible bubbles, English/Chinese menu labels, and correct geometry. If WeChat UI changes, dump **menu item titles only** after a right-click — never paste real chat text into tickets.
- Duplicate identical messages: `find_message_button` uses the last matching row.
- UI is English-WeChat-biased (`Me`, `Messages`, `Chats`). Chinese UI needs parallel labels (already partially present).
- No tests. No Windows/Android.
- `/api/diagnostics/ax` can include message text in descriptions — treat dumps as sensitive.
- English `README.md` + `README.zh.md` and reply-tone presets (`reply_tone` in settings / panel) are in. GitHub publish eval is in the English README; keep `HANDOVER.md` off a public default branch if you publish.

## Do not

- Print or commit real chat text, API keys, or `settings.json`.
- Add protocol bots, hooks, or auto-send without a click.
- Force-push or rewrite published history that might have leaked secrets (this initial repo should be clean).
