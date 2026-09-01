# WeChat Reply Assistant

[中文说明](README.zh.md)

A **local AI reply helper** for WeChat on Mac: it reads the chat that is already open, asks **your** AI API for a few draft replies, and writes into the official WeChat client **only after you click**.

It is not a 24/7 auto-bot. Use it on your own Mac. Do not turn it into a mass-messaging tool.

## How it works

```text
Official WeChat for Mac (foreground chat)
        │  macOS Accessibility (same idea as looking at the screen)
        ▼
Local helper  http://127.0.0.1:8765
        │  Only anonymized recent lines go to the AI you configured
        ▼
UI shows several drafts → you pick one → fill WeChat / send after you confirm
```

Optional: click a bubble on the left to **quote** it. Suggestions target that message; send will Quote/引用 in WeChat first.

### Reply tone

On the suggestion panel (and in Settings) you can pick a tone before generating:

| Option | Effect |
|---|---|
| Natural | Casual WeChat voice (default) |
| Concise | One or two short lines |
| Friendly | Warm but not gushy |
| Professional | Polite, work-safe |
| Warm | Softer / caring |
| Humorous | Light, not mocking |
| Direct | Clear and firm |
| Mixed | One suggestion per different tone |

You can still add a free-text style note in Settings (for example: “reply in English if they used English”).

### Design choices

**Privacy**

- The server binds to `127.0.0.1` only. There is no project cloud and no account on our side.
- Chat text is not logged or stored by default.
- Before the model runs, speakers become `我 / 对方 / 成员N`, and obvious phone numbers are stripped.
- API keys live in `~/.wechat-assist/settings.json` with mode `600`. **Do not commit this file.**
- To keep content off the network: choose **Ollama** and a local model.

**Ban risk**

Personal WeChat has no official bot API. Rough ranking:

| Approach | Risk | This project |
|---|---|---|
| Protocol / web / iPad login | High | Not used |
| Inject or hook the WeChat process | Medium–high | Not used |
| Decrypt the local DB, disable SIP, scrape memory | Lower read risk, weaker OS security | Not used |
| Drive the official client via Accessibility | Relatively lower; behavior heuristics still exist | **Used** |
| You click before send; rate limits | Closer to a human | **Required** |

Not zero risk: high-volume blasts, instant replies, and overnight auto-reply can still look abusive. Defaults: minimum interval between sends and a per-hour cap. You can switch to **fill only** and press Enter yourself.

## Requirements

- macOS
- Python 3.11+
- **WeChat for Mac** installed and signed in (developed against English UI 3.8.x)
- System Settings → Privacy & Security → Accessibility: add **Python** (usually `Python.app`, e.g. a python.org install at  
  `/Library/Frameworks/Python.framework/Versions/3.12/Resources/Python.app`).  
  Checking only Cursor or Terminal is not enough — the process that reads WeChat is Python. Restart the helper after granting access.

## Run

Double-click `/Applications/微信回复助手.app` (same folder as 唱机). The first launch may install dependencies and then opens a browser; quitting from the Dock stops the local server.

If the icon is missing:

```bash
./scripts/install-app.sh
```

For development:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[macos]"
python -m wechat_assist
```

Open [http://127.0.0.1:8765](http://127.0.0.1:8765) (this machine only).

1. Open WeChat and select the chat you want to answer.
2. Confirm the helper shows that context.
3. In Settings, paste your AI key, or switch to Ollama.
4. (Optional) Click a message to quote it. Pick a reply tone.
5. Click **Generate**, edit a draft, then **Send to WeChat** or **Fill input only**.

## Suggested AI setup

- **Google Gemini**: provider Gemini, AI Studio key (usually starts with `AIza`), model e.g. `gemini-3.6-flash`, Base can be empty. Some new accounts cannot use `gemini-2.5-flash`.
- **Privacy first**: Ollama + a local model; leave API Base empty (default `http://127.0.0.1:11434/v1`).
- **Other**: OpenAI / Anthropic / DeepSeek, etc., with the matching compatible Base URL.

## Limits

- Reading is unreliable if WeChat is minimized, the screen is locked, or the chat is fully covered.
- This is not WeCom / Work WeChat Open Platform. It only helps **your own Mac client**.
- After a WeChat UI change, the Accessibility tree may break. Use `/api/diagnostics/ax` to inspect controls, then adapt.  
  **Do not paste diagnostics, raw chat, or `settings.json` into a public issue.**

By using this tool you understand that automating personal WeChat may violate WeChat’s software license. Account risk is yours. The helper stays on localhost and, by default, sends only after you confirm.

## Publishing this repo (evaluation)

The git remote already points at GitHub. Publishing as a **public** repo is possible but not free of product and policy risk. Recommended if you publish:

1. **Keep it framed as a click-to-send helper**, never as an unattended bot. The current repo name `wechat-auto-reply` works against that story; `wechat-reply-assist` (or similar) is clearer.
2. **Stay private until you are sure** no `settings.json`, API keys, Accessibility dumps, or real chat text ever landed in git history (`git log -p` / `gitleaks`). This snapshot looks clean: keys live under `~/.wechat-assist/`, and `.gitignore` already drops `settings.json`, `.env`, and dump files.
3. **Do not ship `HANDOVER.md` on a public default branch** if you want less copy-paste of Accessibility internals. It is useful for local agents, not for end users. `LICENSE` should name a copyright holder before a public release.
4. **GitHub ToS / WeChat ToS**: driving the official Mac client via Accessibility is not a protocol bot, but WeChat’s license still discourages automation. A public README must keep the risk table and “you click first” rule. GitHub may still take the repo down if it is marketed for spam or ban evasion.
5. **If you go public**: MIT is already here; add Topics (`macos`, `accessibility`, `wechat`); pin the English README; link `README.zh.md`; never enable a hosted demo. Prefer **private** if this is only for you.

This evaluation is not legal advice.
