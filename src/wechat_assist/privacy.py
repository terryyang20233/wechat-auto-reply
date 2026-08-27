from __future__ import annotations

import re
from typing import Iterable

PHONE_RE = re.compile(r"(?<!\d)(?:\+?\d[\d\-\s]{8,}\d)")
ID_LIKE_RE = re.compile(r"(?<![A-Za-z0-9])[A-Za-z0-9._-]{18,}(?![A-Za-z0-9])")
SELF_NAMES = {"me", "我", "self"}
SYSTEM_NAMES = {"system", "系统", "系统消息"}


def redact_text(text: str) -> str:
    """Scrub obvious identifiers before a message leaves the machine."""
    cleaned = PHONE_RE.sub("[电话]", text)
    cleaned = ID_LIKE_RE.sub("[编号]", cleaned)
    return cleaned


def _is_self_name(name: str) -> bool:
    return (name or "").strip().lower() in SELF_NAMES


def _is_system_name(name: str) -> bool:
    return (name or "").strip().lower() in SYSTEM_NAMES


def _other_names(messages: Iterable[dict]) -> list[str]:
    seen: list[str] = []
    for item in messages:
        for raw in (item.get("sender_name"), item.get("quote_sender")):
            name = str(raw or "").strip()
            if not name or _is_self_name(name) or _is_system_name(name):
                continue
            if name not in seen:
                seen.append(name)
    return seen


def _alias_map(messages: Iterable[dict]) -> dict[str, str]:
    others = _other_names(messages)
    if len(others) <= 1:
        return {name: "对方" for name in others}
    return {name: f"成员{index + 1}" for index, name in enumerate(others)}


def _label_for(name: str, sender_code: str, aliases: dict[str, str]) -> str:
    if sender_code == "ME" or _is_self_name(name):
        return "我"
    if _is_system_name(name):
        return "系统"
    key = (name or "").strip()
    return aliases.get(key, "对方")


def _scrub_names(text: str, aliases: dict[str, str]) -> str:
    cleaned = text
    for name, label in sorted(aliases.items(), key=lambda item: len(item[0]), reverse=True):
        if len(name) < 2:
            continue
        cleaned = cleaned.replace(name, f"[{label}]")
    return redact_text(cleaned)


def anonymize_messages(
    messages: Iterable[dict],
    chat_name: str | None = None,
    include_chat_name: bool = False,
) -> list[dict]:
    """Replace personal names with stable role labels before calling the model."""
    rows = list(messages)
    aliases = _alias_map(rows)
    out: list[dict] = []
    for item in rows:
        sender_name = str(item.get("sender_name") or "")
        label = _label_for(sender_name, str(item.get("sender") or "OTHER"), aliases)
        text = _scrub_names(str(item.get("text") or ""), aliases)
        quote = _scrub_names(str(item.get("quote_text") or ""), aliases)
        row = {"sender": label, "text": text}
        if quote:
            q_who = str(item.get("quote_sender") or "")
            row["quote_sender"] = _label_for(q_who, "", aliases)
            row["quote_text"] = quote
        out.append(row)
    if len(aliases) > 1:
        out.insert(0, {"sender": "说明", "text": "这是群聊，发言者已匿名为 我 / " + " / ".join(aliases.values())})
    return out


def describe_quote_for_model(quote: dict, context: list[dict]) -> str:
    aliases = _alias_map(list(context) + [quote])
    label = _label_for(str(quote.get("sender_name") or ""), str(quote.get("sender") or ""), aliases)
    text = _scrub_names(str(quote.get("text") or ""), aliases)
    return f"[{label}] {text}"


def build_transcript(messages: list[dict], chat_name: str | None, include_chat_name: bool) -> str:
    lines: list[str] = []
    if include_chat_name and chat_name:
        lines.append(f"会话：{redact_text(chat_name)}")
    for item in messages:
        sender = item.get("sender") or "对方"
        text = item.get("text") or ""
        quote = item.get("quote_text") or ""
        if sender == "说明":
            lines.append(text)
            continue
        if quote:
            q_who = item.get("quote_sender") or "对方"
            lines.append(f"[{sender}] （回复[{q_who}]「{quote}」）{text}")
        else:
            lines.append(f"[{sender}] {text}")
    return "\n".join(lines)
