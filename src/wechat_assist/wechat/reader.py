from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass, asdict
from typing import Any

from . import ax

GENERIC_WINDOW_TITLES = {
    "wechat",
    "微信",
    "window",
    "wechat (chats)",
    "wechat (contacts)",
}

SKIP_SYSTEM = {
    "you recalled a message",
    "你撤回了一条消息",
    "recalled a message",
}

TIMESTAMP_RE = re.compile(
    r"""^(
        (?:
            today|yesterday|now|
            今天|昨天|刚才|刚刚|
            monday|tuesday|wednesday|thursday|friday|saturday|sunday|
            星期[一二三四五六日天]|
            \d{1,2}/\d{1,2}(?:/\d{2,4})?|
            \d{4}[-/.]\d{1,2}[-/.]\d{1,2}|
            (?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{1,2},?\s*(?:\d{2,4})?|
            \d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s*(?:\d{2,4})?
        )
        (?:\s+\d{1,2}:\d{2}(?::\d{2})?(?:\s*[ap]m)?)?
        |
        \d{1,2}:\d{2}(?::\d{2})?(?:\s*[ap]m)?
    )$""",
    re.IGNORECASE | re.VERBOSE,
)


class WeChatError(RuntimeError):
    pass


@dataclass
class Message:
    sender: str  # ME | OTHER | UNKNOWN
    text: str
    sender_name: str = ""
    quote_sender: str = ""
    quote_text: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ChatSnapshot:
    chat_name: str
    messages: list[Message]
    input_ready: bool
    wechat_running: bool
    ax_trusted: bool
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "chat_name": self.chat_name,
            "messages": [m.to_dict() for m in self.messages],
            "input_ready": self.input_ready,
            "wechat_running": self.wechat_running,
            "ax_trusted": self.ax_trusted,
            "note": self.note,
        }


def permission_status() -> dict:
    ident = ax.process_identity()
    hint = ax.permission_hint()
    try:
        trusted = ax.is_trusted(prompt=False)
    except ax.AccessibilityUnavailable as exc:
        return {
            "ax_trusted": False,
            "wechat_running": False,
            "error": str(exc),
            "hint": hint,
            **ident,
        }
    running = False
    try:
        ax.find_wechat_app()
        running = True
    except ax.AccessibilityUnavailable:
        running = False
    return {
        "ax_trusted": trusted,
        "wechat_running": running,
        "error": None,
        "hint": None if trusted else hint,
        **ident,
    }


def request_permission() -> bool:
    try:
        return ax.is_trusted(prompt=True)
    except ax.AccessibilityUnavailable:
        return False


_CACHE_LOCK = threading.Lock()
_CACHE: ChatSnapshot | None = None
_CACHE_AT = 0.0
_CACHE_TTL = 1.5
_INFLIGHT: threading.Event | None = None
_INFLIGHT_SNAP: ChatSnapshot | None = None

_TABLE_ROLES = {"AXTable", "AXList", "AXOutline"}
_CHATS_LABELS = {"chats", "会话"}
_SKIP_LIST_LABELS = {"chats", "会话", "contacts", "联系人"}
_MSG_KEYS = ("messages", "消息", "chat history", "聊天记录", "search results")


def read_current_chat(last_n: int = 20) -> ChatSnapshot:
    global _CACHE, _CACHE_AT, _INFLIGHT, _INFLIGHT_SNAP
    now = time.monotonic()
    with _CACHE_LOCK:
        if _CACHE is not None and now - _CACHE_AT < _CACHE_TTL:
            return _CACHE
        if _INFLIGHT is not None:
            waiter = _INFLIGHT
            leader = False
        else:
            waiter = threading.Event()
            _INFLIGHT = waiter
            _INFLIGHT_SNAP = None
            leader = True
    if not leader:
        waiter.wait(timeout=60)
        with _CACHE_LOCK:
            return _INFLIGHT_SNAP or _CACHE or ChatSnapshot(
                chat_name="",
                messages=[],
                input_ready=False,
                wechat_running=False,
                ax_trusted=False,
                note="正在读取微信窗口。",
            )
    try:
        snap = _read_current_chat_uncached(last_n=last_n)
        with _CACHE_LOCK:
            _CACHE = snap
            _CACHE_AT = time.monotonic()
            _INFLIGHT_SNAP = snap
        return snap
    finally:
        with _CACHE_LOCK:
            done = _INFLIGHT
            _INFLIGHT = None
        if done is not None:
            done.set()


def _read_current_chat_uncached(last_n: int = 20) -> ChatSnapshot:
    status = permission_status()
    if not status["ax_trusted"]:
        return ChatSnapshot(
            chat_name="",
            messages=[],
            input_ready=False,
            wechat_running=status["wechat_running"],
            ax_trusted=False,
            note=status.get("hint") or ax.permission_hint(),
        )
    if not status["wechat_running"]:
        return ChatSnapshot(
            chat_name="",
            messages=[],
            input_ready=False,
            wechat_running=False,
            ax_trusted=True,
            note="微信未在运行。请先打开 Mac 版微信并进入一个聊天窗口。",
        )

    try:
        ax_app, _, _ = ax.find_wechat_app()
        window = ax.main_window(ax_app)
    except ax.AccessibilityUnavailable as exc:
        return ChatSnapshot(
            chat_name="",
            messages=[],
            input_ready=False,
            wechat_running=True,
            ax_trusted=True,
            note=str(exc),
        )

    messages_table, chats_table, input_areas = _scan_main_controls(window)
    chat_name = _read_chat_name(window, chats_table=chats_table, input_areas=input_areas)
    input_node = _pick_input(input_areas)
    if input_node is None and not input_areas:
        input_node = _find_input_field(window)
    messages = _read_messages(window, last_n=last_n, table=messages_table)
    note = ""
    if not messages:
        note = "已打开微信，但当前窗口没有读到文本消息。请把某个聊天放到前台，并确保窗口未被遮挡。"
    return ChatSnapshot(
        chat_name=chat_name,
        messages=messages,
        input_ready=input_node is not None,
        wechat_running=True,
        ax_trusted=True,
        note=note,
    )


def _scan_main_controls(window) -> tuple[Any | None, Any | None, list[ax.AXNode]]:
    """One cheap pass: Messages table, Chats table, composer text areas."""
    messages_table = None
    chats_table = None
    areas: list[ax.AXNode] = []
    stack: list[tuple[Any, int]] = [(window, 0)]
    seen = 0
    while stack:
        current, depth = stack.pop()
        seen += 1
        if seen > 450:
            break
        role = ax.ax_role(current)
        if role in ax.SKIP_DESCEND_ROLES:
            continue
        if role in _TABLE_ROLES:
            title = ax.ax_str(ax.ax_get(current, ax.AX_TITLE))
            desc = ax.ax_str(ax.ax_get(current, ax.AX_DESCRIPTION))
            blob = f"{title} {desc}".lower()
            stripped = blob.strip()
            if stripped in _CHATS_LABELS:
                if chats_table is None:
                    chats_table = current
            elif stripped not in _SKIP_LIST_LABELS and any(key in blob for key in _MSG_KEYS):
                if messages_table is None:
                    messages_table = current
        elif role == "AXTextArea":
            title = ax.ax_str(ax.ax_get(current, ax.AX_TITLE))
            ident = ax.ax_str(ax.ax_get(current, ax.AX_IDENTIFIER))
            desc = ax.ax_str(ax.ax_get(current, ax.AX_DESCRIPTION))
            blob = f"{title} {ident} {desc}".lower()
            if "search" not in blob and "搜索" not in title and "搜索" not in desc:
                areas.append(ax.describe(current, geometry=True, value=False))
        if depth >= 10:
            continue
        children = list(ax.ax_get(current, ax.AX_CHILDREN) or [])
        for child in reversed(children[:40]):
            stack.append((child, depth + 1))
    return messages_table, chats_table, areas


def _read_chat_name(
    window,
    chats_table: Any | None = None,
    input_areas: list[ax.AXNode] | None = None,
) -> str:
    title = ax.ax_str(ax.ax_get(window, ax.AX_TITLE))
    if title and not _is_generic_title(title):
        return _strip_member_count(title)

    from_session = _chat_name_from_session_list(window, chats_table=chats_table)
    if from_session:
        return from_session

    input_node = _pick_input(input_areas or [])
    if input_node is None and not input_areas:
        input_node = _find_input_field(window)
    if input_node and input_node.title and not _is_generic_title(input_node.title):
        return _strip_member_count(input_node.title)

    header = ax.dfs(
        window,
        lambda n: n.role == "AXStaticText"
        and bool(n.value)
        and 1 < len(n.value) <= 40
        and not _is_generic_title(n.value)
        and not TIMESTAMP_RE.match(n.value)
        and not ax.is_chrome_text(n.value)
        and n.value.lower() not in {"field", "chats", "messages"},
        max_depth=8,
        max_nodes=200,
        value=True,
    )
    if header and header.value:
        return _strip_member_count(header.value)

    selected = ax.dfs(
        window,
        lambda n: n.role in {"AXRow", "AXCell", "AXButton", "AXStaticText", "AXGroup"}
        and bool(ax.ax_get(n.element, ax.AX_SELECTED)),
        max_depth=6,
        max_nodes=120,
    )
    if selected:
        name = selected.title or selected.description.split(",")[0]
        if name and not _is_generic_title(name):
            return _strip_member_count(name)

    session = ax.dfs(
        window,
        lambda n: n.identifier.startswith("session_item_"),
        max_depth=6,
        max_nodes=120,
    )
    if session:
        name = session.identifier.removeprefix("session_item_") or session.title
        if name:
            return _strip_member_count(name)
    return "当前聊天"


def _chat_name_from_session_list(window, chats_table: Any | None = None) -> str:
    table_el = chats_table
    if table_el is None:
        table = ax.dfs(
            window,
            lambda n: n.role == "AXTable" and n.description.lower() in {"chats", "会话"},
            max_depth=10,
            max_nodes=400,
        )
        table_el = table.element if table else None
    if table_el is None:
        return ""
    rows = ax.selected_table_rows(table_el)
    for row in rows:
        raw = _row_description(row)
        name = raw.split(",")[0].strip()
        if name and not _is_generic_title(name) and not ax.is_chrome_text(name):
            return _strip_member_count(name)
    return ""


def _is_generic_title(name: str) -> bool:
    return name.strip().lower() in GENERIC_WINDOW_TITLES or name.strip().lower().startswith("wechat (")


def _strip_member_count(name: str) -> str:
    text = name.strip()
    if text.endswith(")") and "(" in text:
        head, _, tail = text.rpartition("(")
        if tail[:-1].isdigit():
            return head.strip()
    if text.endswith("）") and "（" in text:
        head, _, tail = text.rpartition("（")
        if tail[:-1].isdigit():
            return head.strip()
    return text


def _is_composer_field(node: ax.AXNode) -> bool:
    blob = f"{node.title} {node.identifier} {node.description}".lower()
    return "search" not in blob and "搜索" not in node.title and "搜索" not in node.description


def _pick_input(areas: list[ax.AXNode]) -> ax.AXNode | None:
    if not areas:
        return None

    def score(node: ax.AXNode) -> tuple:
        y = node.y or 0.0
        w = node.w or 0.0
        titled = 1 if node.title else 0
        known = 1 if node.identifier in ax.INPUT_IDENTIFIERS else 0
        return (known, titled, y, w)

    ranked = [n for n in areas if _is_composer_field(n)]
    if not ranked:
        return None
    ranked.sort(key=score, reverse=True)
    return ranked[0]


def _find_input_field(window) -> ax.AXNode | None:
    areas = ax.collect(
        window,
        lambda n: n.role == "AXTextArea" and _is_composer_field(n),
        max_depth=10,
        max_nodes=220,
        geometry=False,
        value=False,
    )
    if areas:
        return _pick_input([ax.describe(n.element, geometry=True) for n in areas])
    fields = ax.collect(
        window,
        lambda n: n.role == "AXTextField"
        and _is_composer_field(n)
        and not n.identifier.endswith("18"),
        max_depth=8,
        max_nodes=160,
        geometry=False,
        value=False,
    )
    if not fields:
        return None
    return _pick_input([ax.describe(n.element, geometry=True) for n in fields])


def _read_messages(window, last_n: int, table: Any | None = None) -> list[Message]:
    table_el = table
    if table_el is None:
        found = _find_transcript_table(window)
        table_el = found.element if found else None
    if table_el is not None:
        parsed = _messages_from_table(table_el, last_n=last_n)
        if parsed:
            return parsed[-last_n:]

    # Fallback for layouts that only expose raw static text (e.g. some Chat History views).
    text_nodes = ax.collect(
        window,
        lambda n: n.role in {"AXStaticText", "AXTextArea"}
        and bool(n.value or n.title)
        and not ax.is_chrome_text(n.value or n.title),
        max_depth=8,
        max_nodes=220,
        geometry=False,
        value=True,
    )
    parsed = []
    seen: set[str] = set()
    for node in text_nodes:
        item = parse_accessible_text(node.value or node.title)
        if item is None:
            continue
        key = f"{item.sender}:{item.text}:{item.quote_text}"
        if key in seen:
            continue
        seen.add(key)
        parsed.append(item)
    return parsed[-last_n:]


def _find_transcript_table(window) -> ax.AXNode | None:
    def match(node: ax.AXNode) -> bool:
        if node.role not in {"AXTable", "AXList", "AXOutline"}:
            return False
        blob = f"{node.title} {node.description}".lower()
        if blob.strip() in {"chats", "会话", "contacts", "联系人"}:
            return False
        return any(
            key in blob
            for key in ("messages", "消息", "chat history", "聊天记录", "search results")
        )

    found = ax.dfs(window, match, max_depth=10, max_nodes=400)
    return found


def _messages_from_table(table_el, last_n: int | None = None) -> list[Message]:
    visible = ax.ax_get(table_el, ax.AX_VISIBLE_ROWS)
    if visible:
        parsed = _parse_table_rows(list(visible), last_n=None)
        if parsed and (not last_n or len(parsed) >= last_n):
            return parsed
    rows = ax.table_rows(table_el)
    return _parse_table_rows(rows, last_n=last_n)


def _parse_table_rows(rows: list[Any], last_n: int | None = None) -> list[Message]:
    if not rows:
        return []
    if last_n:
        slack = max(8, last_n * 3)
        rows = rows[-slack:]
    out: list[Message] = []
    seen: set[str] = set()
    for row in rows:
        raw = _row_description(row)
        if not raw:
            continue
        item = parse_accessible_text(raw)
        if item is None:
            continue
        key = f"{item.sender}:{item.text}:{item.quote_text}"
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def find_message_button(window, target: dict) -> ax.AXNode | None:
    table = _find_transcript_table(window)
    if table is None:
        return None
    wanted = _message_key(target)
    match_el = None
    for row in ax.table_rows(table.element):
        item = parse_accessible_text(_row_description(row))
        if item is None or _message_key(item.to_dict()) != wanted:
            continue
        button = _first_button(row)
        if button is None:
            continue
        match_el = ax.describe(button, geometry=True)
    return match_el


def _message_key(item: dict) -> tuple[str, str, str]:
    return (
        str(item.get("sender_name") or item.get("sender") or ""),
        str(item.get("text") or "").strip(),
        str(item.get("quote_text") or "").strip(),
    )


def _first_button(row_el):
    queue = [row_el]
    seen = 0
    while queue and seen < 12:
        el = queue.pop(0)
        seen += 1
        if ax.ax_str(ax.ax_get(el, ax.AX_ROLE)) == "AXButton":
            return el
        queue.extend(list(ax.ax_get(el, ax.AX_CHILDREN) or [])[:6])
    children = list(ax.ax_get(row_el, ax.AX_CHILDREN) or [])
    return children[0] if children else row_el


def _row_description(row_el) -> str:
    desc = ax.ax_str(ax.ax_get(row_el, ax.AX_DESCRIPTION))
    if desc:
        return desc
    title = ax.ax_str(ax.ax_get(row_el, ax.AX_TITLE))
    if title:
        return title
    queue = [row_el]
    seen = 0
    while queue and seen < 8:
        el = queue.pop(0)
        seen += 1
        if el is not row_el:
            text = (
                ax.ax_str(ax.ax_get(el, ax.AX_DESCRIPTION))
                or ax.ax_str(ax.ax_get(el, ax.AX_VALUE))
                or ax.ax_str(ax.ax_get(el, ax.AX_TITLE))
            )
            if text:
                return text
        queue.extend(list(ax.ax_get(el, ax.AX_CHILDREN) or [])[:4])
    return ""


def _sender_fields(who: str) -> tuple[str, str]:
    name = (who or "").strip() or "未知"
    if name.lower() == "me" or name == "我":
        return "ME", "Me" if name.lower() == "me" else name
    if name.lower() in {"system", "系统"}:
        return "OTHER", name
    return "OTHER", name


def _split_quoted(body: str) -> tuple[str, str, str]:
    """Split WeChat AX `reply,quoted,Name: original` into (reply, quote_sender, quote_text)."""
    text = body or ""
    lower = text.lower()
    for token in (",quoted,", "，quoted，", ",引用,", "，引用，"):
        idx = lower.find(token) if token.isascii() else text.find(token)
        if idx < 0:
            continue
        reply = text[:idx].strip()
        rest = text[idx + len(token) :].strip()
        named = re.match(r"^(.+?)\s*[:：]\s*(.*)$", rest, re.DOTALL)
        if named:
            return reply, named.group(1).strip(), named.group(2).strip()
        return reply, "", rest
    return text.strip(), "", ""


def parse_accessible_text(raw: str) -> Message | None:
    text = " ".join((raw or "").split())
    if not text or ax.is_chrome_text(text):
        return None
    if TIMESTAMP_RE.match(text):
        return None
    lowered = text.lower()
    if any(flag in lowered for flag in SKIP_SYSTEM):
        return None
    if lowered.startswith("hide stickied") or "stickied chats" in lowered:
        return None

    if lowered.startswith("system message:"):
        body = text.split(":", 1)[1].strip()
        if body.lower() in SKIP_SYSTEM or any(flag in body.lower() for flag in SKIP_SYSTEM):
            return None
        return Message("OTHER", f"[系统] {body}", sender_name="System")

    media = re.match(r"^(Me|.+?):Sent a\s*(.+)$", text, re.IGNORECASE)
    if media:
        who, kind = media.group(1), media.group(2).strip()
        role, name = _sender_fields(who)
        reply, quote_sender, quote_text = _split_quoted(kind)
        return Message(role, f"[{reply}]", name, quote_sender, quote_text)

    said = re.match(r"^(Me|.+?)Said:(.*)$", text, re.DOTALL)
    if said:
        who, body = said.group(1), said.group(2)
        role, name = _sender_fields(who)
        reply, quote_sender, quote_text = _split_quoted(body)
        if not reply:
            return None
        return Message(role, reply, name, quote_sender, quote_text)

    chinese = re.match(r"^(我|.+?)[说說][：:](.*)$", text, re.DOTALL)
    if chinese:
        who, body = chinese.group(1), chinese.group(2).strip()
        role, name = _sender_fields(who)
        reply, quote_sender, quote_text = _split_quoted(body)
        if not reply:
            return None
        return Message(role, reply, name, quote_sender, quote_text)

    # Chat History rows are often plain text without MeSaid prefixes.
    reply, quote_sender, quote_text = _split_quoted(text)
    if len(reply) <= 2 and not quote_text:
        return None
    return Message("UNKNOWN", reply, "", quote_sender, quote_text)


def find_input_or_raise(window) -> ax.AXNode:
    node = _find_input_field(window)
    if node is None:
        raise WeChatError("找不到微信输入框。请把聊天窗口放到前台后再试。")
    return node
