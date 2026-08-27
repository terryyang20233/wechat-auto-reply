from __future__ import annotations

import json
import re
from typing import Any

import httpx

from wechat_assist.config import AppSettings, ReplyTone
from wechat_assist.privacy import anonymize_messages, build_transcript, describe_quote_for_model, redact_text

SYSTEM_PROMPT = """你是用户本人的微信回复参考助手，不是自动机器人。
根据给定的聊天上下文，为用户起草若干条「可以直接发出去」的回复备选。

硬性要求：
- 严格模仿真人微信：口语、短句、符合上下文语气
- 使用与对话相同的语言（中文就回中文）
- 不要标题、不要编号、不要解释、不要加引号包裹整句
- 不要编造用户没确认过的时间、地点、承诺
- 不要过度热情或过度使用表情；仅在对方也在用表情时偶尔带一个
- 若某条带有「回复[我/对方/成员N]『…』」，说明它是针对那条被引用消息发出的；建议也要能接得上，但不要把引用原文整段复述进去
- 如果用户指定了「请引用某条消息来回复」，建议必须针对那条被引用内容，不要写成在回整段聊天里的另一句
- 只输出 JSON，格式如下：
{"suggestions":[{"tone":"简洁","text":"..."},{"tone":"友好","text":"..."},{"tone":"认真","text":"..."}]}
"""

TONE_GUIDES: dict[str, str] = {
    "natural": "自然口语：像真人微信，短句、不书面、不客服腔。",
    "concise": "简洁：尽量一两句说完，不铺垫、不重复。",
    "friendly": "友好轻松：语气亲近，但不油腻、不堆表情。",
    "professional": "得体克制：适合工作或不太熟的人，礼貌、清楚、不卖萌。",
    "warm": "温柔关心：体贴、软一点，但仍像聊天而不是鸡汤。",
    "humorous": "轻松幽默：可以轻微俏皮，但不嘲讽对方、不开过火的玩笑。",
    "firm": "直接明确：态度清楚，不绕弯、不道歉过头。",
    "varied": "几条建议用不同语气（如简洁 / 友好 / 认真），让用户好挑选。",
}

TONE_LABELS: dict[str, str] = {
    "natural": "自然",
    "concise": "简洁",
    "friendly": "友好",
    "professional": "得体",
    "warm": "温柔",
    "humorous": "幽默",
    "firm": "直接",
    "varied": "多样",
}


def normalize_tone(value: str | None) -> ReplyTone:
    key = (value or "natural").strip().lower()
    if key in TONE_GUIDES:
        return key  # type: ignore[return-value]
    return "natural"


def test_connection(settings: AppSettings) -> dict[str, Any]:
    """Send a tiny dummy prompt. Does not include WeChat messages."""
    raw = _complete(
        settings,
        '只输出 JSON：{"suggestions":[{"tone":"测试","text":"pong"}]}',
    )
    items = _parse_suggestions(raw, 1)
    sample = items[0]["text"] if items else raw[:80]
    return {
        "ok": True,
        "provider": settings.provider,
        "model": settings.model or "",
        "sample": sample[:80],
    }


def suggest_replies(
    settings: AppSettings,
    chat_name: str,
    messages: list[dict],
    quote: dict | None = None,
) -> list[dict[str, str]]:
    if not messages:
        raise ValueError("当前没有可读的聊天上下文。")

    context = messages[-settings.context_messages :]
    if quote and (quote.get("text") or "").strip():
        context = list(context) + [quote]
    safe_messages = anonymize_messages(
        context,
        chat_name=chat_name,
        include_chat_name=settings.include_chat_name,
    )
    transcript = build_transcript(
        safe_messages,
        chat_name=chat_name if settings.include_chat_name else None,
        include_chat_name=settings.include_chat_name,
    )
    extra = ""
    if quote and (quote.get("text") or "").strip():
        quoted = describe_quote_for_model(quote, messages[-settings.context_messages :])
        extra = (
            "用户指定要在微信里引用下面这条消息来回复，请专门针对它写建议：\n"
            f"{quoted}\n\n"
        )
    tone = normalize_tone(settings.reply_tone)
    style_bits = [f"语气要求：{TONE_GUIDES[tone]}"]
    if tone != "varied":
        style_bits.append(
            f"这 {settings.n_suggestions} 条都保持同一语气；JSON 里 tone 字段统一写成「{TONE_LABELS[tone]}」。"
        )
    custom = (settings.system_style or "").strip()
    if custom:
        style_bits.append(f"用户额外风格说明：{custom}")
    user_prompt = (
        "\n".join(style_bits)
        + "\n\n"
        + extra
        + f"请给出 {settings.n_suggestions} 条回复备选。\n\n"
        + f"聊天记录：\n{transcript}"
    )
    raw = _complete(settings, user_prompt)
    return _parse_suggestions(raw, settings.n_suggestions)


def _complete(settings: AppSettings, user_prompt: str) -> str:
    if settings.provider == "anthropic":
        return _complete_anthropic(settings, user_prompt)
    if _use_gemini(settings):
        return _complete_gemini(settings, user_prompt)
    return _complete_openai_compatible(settings, user_prompt)


def _use_gemini(settings: AppSettings) -> bool:
    if settings.provider == "gemini":
        return True
    base = (settings.api_base or "").lower()
    if "generativelanguage.googleapis.com" in base:
        return True
    key = settings.api_key or ""
    return key.startswith("AIza")


GEMINI_DEFAULT_MODEL = "gemini-3.6-flash"
GEMINI_FALLBACK_MODELS = ("gemini-3.6-flash", "gemini-flash-latest", "gemini-2.5-flash")


def _complete_gemini(settings: AppSettings, user_prompt: str) -> str:
    if not settings.api_key:
        raise ValueError("尚未配置 Gemini API Key（Google AI Studio 的密钥一般以 AIza 开头）。")

    base = (settings.api_base or "").rstrip("/")
    if "/openai" in base:
        patched = settings.model_copy(
            update={
                "provider": "custom",
                "api_base": base,
                "model": settings.model or GEMINI_DEFAULT_MODEL,
            }
        )
        return _complete_openai_compatible(patched, user_prompt)

    base = base or "https://generativelanguage.googleapis.com/v1beta"
    requested = (settings.model or GEMINI_DEFAULT_MODEL).removeprefix("models/")
    if requested.startswith("gpt-"):
        requested = GEMINI_DEFAULT_MODEL
    tried: list[str] = []
    last_error = None
    for model in (requested, *GEMINI_FALLBACK_MODELS):
        if model in tried:
            continue
        tried.append(model)
        try:
            text = _gemini_generate(base, settings.api_key, model, user_prompt)
            if model != (settings.model or ""):
                _persist_gemini_model(settings, model)
            return text
        except ValueError as exc:
            last_error = exc
            msg = str(exc).lower()
            if "no longer available" in msg or "not found" in msg or "not supported" in msg:
                continue
            raise
    raise last_error or ValueError("Gemini 调用失败。")


def _persist_gemini_model(settings: AppSettings, model: str) -> None:
    try:
        from wechat_assist.config import save_settings

        save_settings(settings.model_copy(update={"model": model}))
    except Exception:
        pass


def _gemini_generate(base: str, api_key: str, model: str, user_prompt: str) -> str:
    url = f"{base}/models/{model}:generateContent"
    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": api_key,
    }
    payload = {
        "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
        "generationConfig": {
            "temperature": 0.7,
            "responseMimeType": "application/json",
        },
    }
    with httpx.Client(timeout=60.0) as client:
        response = client.post(url, headers=headers, json=payload)
        if response.status_code >= 400:
            raise ValueError(_gemini_error(response))
        data = response.json()
    try:
        parts = data["candidates"][0]["content"]["parts"]
        text = "".join(str(p.get("text") or "") for p in parts)
    except Exception as exc:
        raise ValueError(f"Gemini 返回格式异常：{data}") from exc
    if not text.strip():
        raise ValueError("Gemini 返回为空，请检查模型名是否与 AI Studio 中一致。")
    return text


def _gemini_error(response: httpx.Response) -> str:
    try:
        payload = response.json()
        err = payload.get("error") or payload
        if isinstance(err, dict):
            return f"Gemini 调用失败：{err.get('message') or err}"
        return f"Gemini 调用失败：{err}"
    except Exception:
        return f"Gemini 调用失败（HTTP {response.status_code}）。"


def _complete_openai_compatible(settings: AppSettings, user_prompt: str) -> str:
    base = (settings.api_base or "").rstrip("/")
    if settings.provider == "ollama":
        base = base or "http://127.0.0.1:11434/v1"
    elif settings.provider == "openai":
        base = base or "https://api.openai.com/v1"
    elif not base:
        raise ValueError("自定义接口需要填写 API Base，例如 https://api.deepseek.com/v1")

    headers = {"Content-Type": "application/json"}
    if settings.api_key:
        headers["Authorization"] = f"Bearer {settings.api_key}"
    elif settings.provider != "ollama":
        raise ValueError("尚未配置 API Key。请在设置中填写，密钥只保存在本机。")

    payload: dict[str, Any] = {
        "model": settings.model,
        "temperature": 0.7,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
    }
    url = f"{base}/chat/completions"
    with httpx.Client(timeout=60.0) as client:
        response = client.post(url, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()
    try:
        return data["choices"][0]["message"]["content"]
    except Exception as exc:
        raise ValueError(f"AI 返回格式异常：{data}") from exc


def _complete_anthropic(settings: AppSettings, user_prompt: str) -> str:
    if not settings.api_key:
        raise ValueError("尚未配置 Anthropic API Key。")
    base = (settings.api_base or "https://api.anthropic.com").rstrip("/")
    headers = {
        "Content-Type": "application/json",
        "x-api-key": settings.api_key,
        "anthropic-version": "2023-06-01",
    }
    payload = {
        "model": settings.model or "claude-3-5-sonnet-latest",
        "max_tokens": 800,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": user_prompt}],
    }
    with httpx.Client(timeout=60.0) as client:
        response = client.post(f"{base}/v1/messages", headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()
    parts = data.get("content") or []
    text = "".join(p.get("text", "") for p in parts if p.get("type") == "text")
    if not text:
        raise ValueError(f"AI 返回为空：{data}")
    return text


def _parse_suggestions(raw: str, n: int) -> list[dict[str, str]]:
    text = raw.strip()
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        text = match.group(0)
    try:
        data = json.loads(text)
        items = data.get("suggestions") or data.get("replies") or []
        out: list[dict[str, str]] = []
        for item in items:
            if isinstance(item, str):
                out.append({"tone": "建议", "text": redact_text(item.strip())})
            elif isinstance(item, dict):
                body = str(item.get("text") or item.get("reply") or "").strip()
                tone = str(item.get("tone") or item.get("style") or "建议").strip()
                if body:
                    out.append({"tone": tone, "text": redact_text(body)})
        if out:
            return out[:n]
    except json.JSONDecodeError:
        pass

    lines = [ln.strip(" -•\t") for ln in raw.splitlines() if ln.strip()]
    fallback = [{"tone": "建议", "text": redact_text(ln)} for ln in lines if ln]
    if not fallback:
        raise ValueError("AI 没有给出可用的回复。")
    return fallback[:n]
