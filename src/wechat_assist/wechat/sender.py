from __future__ import annotations

import random
import re
import time
from dataclasses import dataclass

from . import ax
from .reader import WeChatError, _read_chat_name, find_input_or_raise, find_message_button


@dataclass
class SendResult:
    ok: bool
    sent: bool
    filled: bool
    chat_name: str
    message: str
    quoted: bool = False
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "sent": self.sent,
            "filled": self.filled,
            "chat_name": self.chat_name,
            "message": self.message,
            "quoted": self.quoted,
            "error": self.error,
        }


def send_or_fill(
    text: str,
    expected_chat: str,
    press_enter: bool,
    delay_min: float,
    delay_max: float,
    quote: dict | None = None,
) -> SendResult:
    text = (text or "").strip()
    if not text:
        return SendResult(False, False, False, expected_chat, text, error="回复内容为空。")
    if len(text) > 2000:
        return SendResult(False, False, False, expected_chat, text, error="回复过长，请缩短后再发送。")
    if not ax.is_trusted():
        return SendResult(
            False,
            False,
            False,
            expected_chat,
            text,
            error="没有辅助功能权限，无法操作微信输入框。",
        )

    try:
        ax.activate_wechat()
        time.sleep(0.25)
        ax_app, _, _ = ax.find_wechat_app()
        window = ax.main_window(ax_app)
    except ax.AccessibilityUnavailable as exc:
        return SendResult(False, False, False, expected_chat, text, error=str(exc))

    current = _read_chat_name(window)
    if expected_chat and current and _norm(current) != _norm(expected_chat):
        return SendResult(
            False,
            False,
            False,
            current,
            text,
            error=f"当前微信窗口是「{current}」，与要回复的「{expected_chat}」不一致，已取消发送，避免发错人。",
        )

    quoted = False
    if quote and (quote.get("text") or "").strip():
        quoted = _quote_message(ax_app, window, quote)
        if not quoted:
            return SendResult(
                False,
                False,
                False,
                current,
                text,
                error="没能在微信里点开「引用」。请确认那条消息仍在当前窗口可见，或改成普通发送。",
            )
        window = ax.main_window(ax_app)

    try:
        input_node = find_input_or_raise(window)
    except WeChatError as exc:
        return SendResult(False, False, False, current, text, quoted=quoted, error=str(exc))

    time.sleep(random.uniform(max(0.2, delay_min), max(delay_min, delay_max)))
    ax.click_center(input_node)
    time.sleep(0.12)

    filled = False
    if ax.ax_set(input_node.element, ax.AX_VALUE, text):
        filled = True
    else:
        try:
            ax.paste_via_clipboard(text)
            filled = True
        except Exception as exc:
            return SendResult(False, False, False, current, text, quoted=quoted, error=f"无法写入输入框：{exc}")

    if not filled:
        return SendResult(False, False, False, current, text, quoted=quoted, error="写入输入框失败。")

    sent = False
    if press_enter:
        latest = _read_chat_name(ax.main_window(ax_app))
        if expected_chat and latest and _norm(latest) != _norm(expected_chat):
            return SendResult(
                True,
                False,
                True,
                latest,
                text,
                quoted=quoted,
                error=f"内容已填入，但当前聊天变成了「{latest}」，已停止按回车。",
            )
        ax.press_return()
        sent = True

    return SendResult(True, sent, True, current, text, quoted=quoted)


def _quote_message(ax_app, window, quote: dict) -> bool:
    button = find_message_button(window, quote)
    if button is None:
        return False
    opened = ax.ax_show_menu(button.element)
    if not opened:
        opened = ax.right_click_center(button)
    if not opened:
        ax.ax_press(button.element)
        time.sleep(0.2)
        opened = ax.right_click_center(button)
    time.sleep(0.5)
    item = _find_quote_menu_item(ax_app)
    if item is None:
        ax.press_key(ax.KEYCODE_ESCAPE, 0)
        return False
    if not ax.ax_press(item.element):
        ax.click_center(item)
    time.sleep(0.35)
    return True


def _find_quote_menu_item(ax_app) -> ax.AXNode | None:
    preferred = None
    fallback = None
    for node in ax.collect_menu_items(ax_app):
        title = (node.title or node.description or node.value or "").strip().lower()
        if "引用" in title or re.search(r"\bquote\b", title):
            preferred = node
            break
        if fallback is None and ("回复" in title or re.search(r"\breply\b", title)):
            fallback = node
    return preferred or fallback


def _norm(name: str) -> str:
    return " ".join(name.strip().lower().split())
