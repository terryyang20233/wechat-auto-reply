from __future__ import annotations

import json
import re
from typing import Any

import httpx

from wechat_assist.config import AppSettings, normalize_tone
from wechat_assist.privacy import (
    anonymize_messages,
    build_transcript,
    describe_quote_for_model,
    redact_text,
    scrub_user_note,
)

MAX_BUBBLES = 3

SYSTEM_PROMPT = """你是用户本人的微信回复参考助手，不是自动机器人。
根据给定的聊天上下文，为用户起草若干套「可以直接发出去」的回复备选。

硬性要求：
- 严格模仿真人微信：口语、短句、符合上下文语气
- 使用与对话相同的语言（中文就回中文）
- 不要标题、不要编号、不要解释、不要加引号包裹整句
- 不要编造用户没确认过的时间、地点、承诺
- 不要过度热情或过度使用表情；仅在对方也在用表情时偶尔带一个
- 若某条带有「回复[我/对方/成员N]『…』」，说明它是针对那条被引用消息发出的；建议也要能接得上，但不要把引用原文整段复述进去
- 如果用户指定了「请引用某条消息来回复」，建议必须针对那条被引用内容，不要写成在回整段聊天里的另一句
- 若提供了「用户想说的」，必须把这些要点写进回复：结合上下文改成自然微信口吻，不要漏掉关键信息；不要像备忘录那样逐条编号；不要添加用户没写的事实、时间或承诺
- 每一套备选是一次回复，用 messages 字符串数组表示将要连续发出的微信气泡。长度可以是 1，也可以是 2 或 3
- 真人微信常把两件独立的事拆成两条（先应一声，再补一句；答应一件事，再问另一句）。这种该拆。不要把一个完整短句切成碎片
- 分开发气泡不是写编号清单：每条都是能单独发出去的口语
- 只输出一个 JSON 对象，不要 markdown 代码块，不要在后面再追加第二个 JSON 或数组。多条时 messages 必须有多个元素，不要把几句话塞进同一个字符串：
{"suggestions":[{"tone":"日常","messages":["行啊","那你定个点我看"]},{"tone":"日常","messages":["今晚我去不了了"]}]}
"""

TONE_GUIDES: dict[str, str] = {
    "daily": (
        "日常模式：写最正常的微信回复，像朋友或熟人平时聊天。"
        "口语、自然、该短就短；不要暧昧推拉，不要职场套话，不要阴阳或刻意冷处理。"
        "不要装策略、不要客服腔。"
    ),
    "dating_tease": (
        "恋爱/暧昧 · 推拉俏皮：带一点神秘感和无害玩笑，若即若离，不要把话一次说满。"
        "可以打趣、轻轻不接招、或把问题抛回去；不要油腻、不要连声夸奖、不要嘲讽对方的外貌或真心。"
        "不要变成审讯或冷暴力；保持轻松、还能继续聊。"
    ),
    "dating_care": (
        "恋爱/暧昧 · 情绪价值：接住对方的情绪，细腻关心，让人觉得被看见。"
        "有温度但有边界：不要过度迎合、不要连发殷勤、不要把对方捧上天，不要显得舔狗或卑微。"
        "关心要具体、克制，像在乎的人而不是讨好。"
    ),
    "dating_open": (
        "恋爱/暧昧 · 延展话题：先接住对方刚说的，再用一个开放式问题把聊天往下带。"
        "问题要好答、跟上下文有关；不要审讯、不要连续追问、不要尬聊清单。"
        "目标是让对方愿意继续说，而不是把球踢死。"
    ),
    "work_efficient": (
        "职场 · 专业高效：直接、清楚、可执行。优先确认收到、给结论或下一步。"
        "少语气词、不卖萌、不闲聊；不要官腔堆砌，也不要越权承诺。"
    ),
    "work_deflect": (
        "职场 · 委婉拒绝/延后：高情商打太极。表达理解，但不轻易答应；给出合理推迟或含蓄拒绝。"
        "不伤和气、不甩锅、不编造尚未确认的时间或资源；给对方台阶，同时保住自己的边界。"
    ),
    "work_confirm": (
        "职场 · 请示确认：下级对上级的稳妥回复。先复述关键信息，再请对方拍板或确认。"
        "不擅自做主、不顶撞、不过度解释；礼貌、短、把选择权交回上级。"
    ),
    "clash_sarcastic": (
        "怼人/防守 · 阴阳怪气：不带脏字、不人身攻击地怼回去，点到为止。"
        "可以用轻嘲、反问或装听不懂来回击；不要升级成辱骂、威胁或翻旧账。"
        "保持微信短句，像聪明人在回，不是在写吵架稿。"
    ),
    "clash_distance": (
        "怼人/防守 · 礼貌保持距离：冷处理，礼貌但明显不想继续。"
        "短、淡、收束话题；可以点头式结束，不要解释太多、不要继续争对错、不要假装热情。"
        "不失礼，但让这段对话停住。"
    ),
}

TONE_LABELS: dict[str, str] = {
    "daily": "日常",
    "dating_tease": "推拉/俏皮",
    "dating_care": "情绪价值",
    "dating_open": "延展话题",
    "work_efficient": "专业高效",
    "work_deflect": "委婉拒绝/延后",
    "work_confirm": "请示/确认",
    "clash_sarcastic": "阴阳怪气",
    "clash_distance": "礼貌距离",
}


def test_connection(settings: AppSettings) -> dict[str, Any]:
    """Send a tiny dummy prompt. Does not include WeChat messages."""
    raw = _complete(
        settings,
        '只输出 JSON：{"suggestions":[{"tone":"测试","messages":["pong"]}]}',
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
    user_intent: str | None = None,
) -> list[dict]:
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
        extra += (
            "用户指定要在微信里引用下面这条消息来回复，请专门针对它写建议：\n"
            f"{quoted}\n\n"
        )
    intent = (user_intent or "").strip()
    if intent:
        alias_source = list(messages[-settings.context_messages :])
        if quote:
            alias_source.append(quote)
        safe_intent = scrub_user_note(intent, alias_source)
        extra += (
            "用户想说的（请结合上下文改成自然回复，必须覆盖这些要点，不要逐条复述、不要添油加醋）：\n"
            f"{safe_intent}\n\n"
        )
    tone = normalize_tone(settings.reply_tone)
    style_bits = [
        f"当前策略：{TONE_LABELS[tone]}。{TONE_GUIDES[tone]}",
        (
            f"这 {settings.n_suggestions} 套备选都保持这一策略；"
            f"JSON 里 tone 字段统一写成「{TONE_LABELS[tone]}」。"
            "若与上面的通用要求冲突，以当前策略为准。"
        ),
    ]
    custom = (settings.system_style or "").strip()
    if custom:
        style_bits.append(f"用户额外风格说明：{custom}")
    count_hint = (
        f"请给出 {settings.n_suggestions} 套回复备选。"
        f"每套 messages 长度 1～{MAX_BUBBLES}。"
    )
    if settings.n_suggestions >= 2:
        count_hint += (
            f"其中至少 1 套 messages 只有 1 条，至少 1 套 messages 有 2 或 3 条"
            "（两件独立的事、先回应再补充、或「用户想说的」里有多个要点时，优先拆开）。"
        )
    elif intent:
        count_hint += "若「用户想说的」含两个以上要点，这套请拆成 2 或 3 条气泡。"
    else:
        count_hint += "若上下文里其实有两件独立的事，请拆成 2 条；只有一句就保持 1 条。"
    user_prompt = (
        "\n".join(style_bits)
        + "\n\n"
        + extra
        + count_hint
        + "\n\n"
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
AI_TIMEOUT = httpx.Timeout(connect=15.0, read=90.0, write=30.0, pool=15.0)
AI_TIMEOUT_MESSAGE = "AI 接口等待超时。请再试一次；若经常出现，可换更快的模型（例如 gemini-3.1-flash-lite）。"


def _post_json(url: str, *, headers: dict[str, str], payload: dict[str, Any]) -> httpx.Response:
    try:
        with httpx.Client(timeout=AI_TIMEOUT, trust_env=True) as client:
            return client.post(url, headers=headers, json=payload)
    except httpx.TimeoutException as exc:
        raise ValueError(AI_TIMEOUT_MESSAGE) from exc


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
            if AI_TIMEOUT_MESSAGE in str(exc):
                raise
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


def _gemini_generation_config(model: str) -> dict[str, Any]:
    config: dict[str, Any] = {
        "responseMimeType": "application/json",
        "maxOutputTokens": 2048,
    }
    if model.startswith("gemini-3"):
        # Gemini 3 defaults to medium thinking, which can exceed our HTTP read timeout.
        config["thinkingConfig"] = {"thinkingLevel": "MINIMAL"}
    else:
        config["temperature"] = 0.7
        config["thinkingConfig"] = {"thinkingBudget": 0}
    return config


def _gemini_generate(base: str, api_key: str, model: str, user_prompt: str) -> str:
    url = f"{base}/models/{model}:generateContent"
    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": api_key,
    }
    payload = {
        "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
        "generationConfig": _gemini_generation_config(model),
    }
    response = _post_json(url, headers=headers, payload=payload)
    if response.status_code >= 400:
        lowered = (response.text or "").lower()
        if "thinking" in lowered or "temperature" in lowered:
            payload["generationConfig"] = {
                "responseMimeType": "application/json",
                "maxOutputTokens": 2048,
            }
            response = _post_json(url, headers=headers, payload=payload)
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
    response = _post_json(url, headers=headers, payload=payload)
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
        "max_tokens": 1200,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": user_prompt}],
    }
    response = _post_json(f"{base}/v1/messages", headers=headers, payload=payload)
    response.raise_for_status()
    data = response.json()
    parts = data.get("content") or []
    text = "".join(p.get("text", "") for p in parts if p.get("type") == "text")
    if not text:
        raise ValueError(f"AI 返回为空：{data}")
    return text


def _normalize_bubbles(item: Any) -> list[str]:
    raw_parts: list[str] = []
    if isinstance(item, str):
        raw_parts = [item]
    elif isinstance(item, dict):
        msgs = item.get("messages")
        if isinstance(msgs, str):
            raw_parts = [p for p in re.split(r"\n+", msgs) if p.strip()]
        elif isinstance(msgs, list):
            raw_parts = []
            for part in msgs:
                if isinstance(part, list):
                    raw_parts.extend(str(x) for x in part)
                else:
                    raw_parts.append(str(part))
        if not raw_parts:
            body = str(item.get("text") or item.get("reply") or "")
            if body.strip():
                raw_parts = [p for p in re.split(r"\n\n+", body) if p.strip()] or [body]
    bubbles = [redact_text(part.strip()) for part in raw_parts if str(part).strip()]
    return bubbles[:MAX_BUBBLES]


def _pack_suggestion(tone: str, bubbles: list[str]) -> dict:
    return {"tone": tone, "messages": bubbles, "text": "\n".join(bubbles)}


def _strip_fences(raw: str) -> str:
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _iter_json_values(raw: str):
    decoder = json.JSONDecoder()
    i = 0
    n = len(raw)
    while i < n:
        while i < n and raw[i] not in "{[":
            i += 1
        if i >= n:
            return
        try:
            value, end = decoder.raw_decode(raw, i)
        except json.JSONDecodeError:
            i += 1
            continue
        yield value
        i = max(end, i + 1)


def _items_from_value(value: Any) -> list[Any]:
    if isinstance(value, list):
        items: list[Any] = []
        for el in value:
            items.extend(_items_from_value(el))
        return items
    if isinstance(value, dict):
        nested = value.get("suggestions")
        if nested is None:
            nested = value.get("replies")
        if isinstance(nested, list):
            return _items_from_value(nested)
        if value.get("messages") or value.get("text") or value.get("reply"):
            return [value]
    if isinstance(value, str) and value.strip():
        return [value]
    return []


def _suggestion_from_item(item: Any) -> dict | None:
    bubbles = _normalize_bubbles(item)
    if not bubbles:
        return None
    tone = "建议"
    if isinstance(item, dict):
        tone = str(item.get("tone") or item.get("style") or "建议").strip() or "建议"
    return _pack_suggestion(tone, bubbles)


def _parse_suggestions(raw: str, n: int) -> list[dict]:
    text = _strip_fences(raw)
    out: list[dict] = []
    seen: set[str] = set()
    for value in _iter_json_values(text):
        for item in _items_from_value(value):
            packed = _suggestion_from_item(item)
            if not packed or packed["text"] in seen:
                continue
            seen.add(packed["text"])
            out.append(packed)
            if len(out) >= n:
                return out
    if out:
        return out[:n]

    lines = [ln.strip(" -•\t") for ln in raw.splitlines() if ln.strip()]
    fallback: list[dict] = []
    for ln in lines:
        if ln[:1] in "{[":
            continue
        packed = _pack_suggestion("建议", [redact_text(ln)])
        if packed["text"] and packed["text"] not in seen:
            seen.add(packed["text"])
            fallback.append(packed)
    if not fallback:
        raise ValueError("AI 没有给出可用的回复。")
    return fallback[:n]
