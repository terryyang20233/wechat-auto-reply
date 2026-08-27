from __future__ import annotations

import os
import random
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from wechat_assist.ai.suggest import MAX_BUBBLES, normalize_tone, suggest_replies, test_connection
from wechat_assist.config import AppSettings, load_settings, save_settings
from wechat_assist.safety import SendGuard
from wechat_assist.wechat.ax import dump_tree, open_accessibility_settings
from wechat_assist.wechat.reader import permission_status, read_current_chat, request_permission
from wechat_assist.wechat.sender import send_or_fill

WEB_DIR = Path(__file__).resolve().parent / "web"
send_guard = SendGuard()
app = FastAPI(title="WeChat Assist", docs_url=None, redoc_url=None, openapi_url=None)


class SettingsUpdate(BaseModel):
    provider: str | None = None
    api_key: str | None = None
    api_base: str | None = None
    model: str | None = None
    n_suggestions: int | None = Field(default=None, ge=1, le=6)
    context_messages: int | None = Field(default=None, ge=4, le=80)
    anonymize_names: bool | None = None
    include_chat_name: bool | None = None
    reply_tone: str | None = None
    system_style: str | None = None
    send_mode: str | None = None
    min_send_interval_seconds: float | None = None
    max_sends_per_hour: int | None = None
    human_delay_min: float | None = None
    human_delay_max: float | None = None


class QuoteBody(BaseModel):
    sender: str = ""
    sender_name: str = ""
    text: str = ""
    quote_text: str = ""
    quote_sender: str = ""


class SendBody(BaseModel):
    text: str = ""
    messages: list[str] | None = None
    chat_name: str
    press_enter: bool | None = None
    quote: QuoteBody | None = None


class SuggestBody(BaseModel):
    quote: QuoteBody | None = None
    tone: str | None = None
    intent: str = Field(default="", max_length=800)


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


@app.get("/api/status")
def status() -> dict:
    info = permission_status()
    settings = load_settings()
    return {
        **info,
        "provider": settings.provider,
        "model": settings.model,
        "send_mode": settings.send_mode,
        "reply_tone": settings.reply_tone,
        "has_api_key": bool(settings.api_key)
        or settings.provider == "ollama"
        or (settings.api_key or "").startswith("AIza"),
    }


@app.post("/api/permission")
def permission() -> dict:
    trusted = request_permission()
    info = permission_status()
    info["ax_trusted"] = trusted
    return info


@app.post("/api/permission/open-settings")
def permission_open_settings() -> dict:
    open_accessibility_settings()
    return {"ok": True}


@app.get("/api/chat/current")
def current_chat() -> dict:
    settings = load_settings()
    snap = read_current_chat(last_n=settings.context_messages)
    return snap.to_dict()


@app.post("/api/ai/test")
def ai_test() -> dict:
    settings = load_settings()
    try:
        return test_connection(settings)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, f"调用 AI 失败：{exc}") from exc


@app.post("/api/suggest")
def suggest(body: SuggestBody = SuggestBody()) -> dict:
    settings = load_settings()
    snap = read_current_chat(last_n=settings.context_messages)
    if not snap.ax_trusted:
        raise HTTPException(400, snap.note or "缺少辅助功能权限。")
    if not snap.messages:
        raise HTTPException(400, snap.note or "当前没有可读的消息。请在微信中打开一个聊天。")
    quote = body.quote.model_dump() if body and body.quote and body.quote.text.strip() else None
    if body and body.tone:
        settings = settings.model_copy(update={"reply_tone": normalize_tone(body.tone)})
    intent = (body.intent or "").strip() if body else ""
    try:
        items = suggest_replies(
            settings,
            snap.chat_name,
            [m.to_dict() for m in snap.messages],
            quote=quote,
            user_intent=intent or None,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, f"调用 AI 失败：{exc}") from exc
    return {
        "chat_name": snap.chat_name,
        "messages": [m.to_dict() for m in snap.messages],
        "suggestions": items,
        "quoted": bool(quote),
        "used_intent": bool(intent),
    }


def _send_parts(body: SendBody) -> list[str]:
    parts = [str(item).strip() for item in (body.messages or []) if str(item).strip()]
    if not parts and (body.text or "").strip():
        parts = [body.text.strip()]
    return parts[:MAX_BUBBLES]


@app.post("/api/send")
def send(body: SendBody) -> dict:
    settings = load_settings()
    parts = _send_parts(body)
    if not parts:
        raise HTTPException(400, "回复内容为空。")
    press_enter = settings.send_mode == "fill_and_send" if body.press_enter is None else body.press_enter
    quote = body.quote.model_dump() if body.quote and body.quote.text.strip() else None
    if press_enter:
        blocked = send_guard.check(
            settings.min_send_interval_seconds,
            settings.max_sends_per_hour,
            n_sends=len(parts),
        )
        if blocked:
            raise HTTPException(429, blocked)

    sent_count = 0
    quoted_any = False
    last = None
    for index, part in enumerate(parts):
        if not press_enter and index > 0:
            break
        if press_enter and index > 0:
            blocked = send_guard.check(
                0,
                settings.max_sends_per_hour,
                n_sends=1,
                enforce_interval=False,
            )
            if blocked:
                payload = last.to_dict() if last else {}
                payload["ok"] = True
                payload["sent"] = sent_count > 0
                payload["sent_count"] = sent_count
                payload["total"] = len(parts)
                payload["warning"] = f"已发出前 {sent_count} 条。{blocked}"
                return payload
        result = send_or_fill(
            text=part,
            expected_chat=body.chat_name,
            press_enter=press_enter,
            delay_min=settings.human_delay_min,
            delay_max=settings.human_delay_max,
            quote=quote if index == 0 else None,
        )
        last = result
        if not result.ok:
            if sent_count:
                payload = result.to_dict()
                payload["ok"] = True
                payload["sent"] = True
                payload["sent_count"] = sent_count
                payload["total"] = len(parts)
                payload["warning"] = f"已发出前 {sent_count} 条，后面停下：{result.error}"
                return payload
            raise HTTPException(400, result.error or "发送失败。")
        quoted_any = quoted_any or result.quoted
        if result.sent:
            send_guard.mark_sent()
            sent_count += 1
            if index < len(parts) - 1:
                time.sleep(random.uniform(0.45, 1.1))

    payload = last.to_dict() if last else {}
    payload["quoted"] = quoted_any
    payload["sent_count"] = sent_count
    payload["total"] = len(parts)
    if last and last.error:
        payload["warning"] = last.error
    elif not press_enter and len(parts) > 1:
        payload["warning"] = f"已填入第 1 条（共 {len(parts)} 条）。其余请你在微信里接着发，或改用「发送到微信」。"
    return payload


@app.get("/api/settings")
def get_settings() -> dict:
    return load_settings().masked()


@app.put("/api/settings")
def put_settings(update: SettingsUpdate) -> dict:
    current = load_settings()
    data = current.model_dump()
    incoming = update.model_dump(exclude_unset=True)
    if incoming.get("api_key") and "…" in incoming["api_key"]:
        incoming.pop("api_key")
    if "reply_tone" in incoming:
        incoming["reply_tone"] = normalize_tone(incoming.get("reply_tone"))
    data.update({k: v for k, v in incoming.items() if v is not None})
    saved = AppSettings.model_validate(data)
    save_settings(saved)
    return saved.masked()


@app.get("/api/diagnostics/ax")
def diagnostics() -> dict:
    return {"tree": dump_tree()}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


def run() -> None:
    import uvicorn

    try:
        request_permission()
    except Exception:
        pass

    host = os.environ.get("WECHAT_ASSIST_HOST", "127.0.0.1")
    port = int(os.environ.get("WECHAT_ASSIST_PORT", "8765"))
    uvicorn.run("wechat_assist.app:app", host=host, port=port, reload=False)
