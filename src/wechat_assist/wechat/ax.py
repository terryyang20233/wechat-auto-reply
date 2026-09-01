from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

WECHAT_BUNDLE_IDS = ("com.tencent.xinWeChat",)
WECHAT_APP_NAMES = ("WeChat", "微信")

AX_ROLE = "AXRole"
AX_TITLE = "AXTitle"
AX_IDENTIFIER = "AXIdentifier"
AX_DESCRIPTION = "AXDescription"
AX_VALUE = "AXValue"
AX_CHILDREN = "AXChildren"
AX_ROLE_DESCRIPTION = "AXRoleDescription"
AX_POSITION = "AXPosition"
AX_SIZE = "AXSize"
AX_FOCUSED_WINDOW = "AXFocusedWindow"
AX_WINDOWS = "AXWindows"
AX_SELECTED = "AXSelected"
AX_PLACEHOLDER = "AXPlaceholderValue"
AX_PRESS = "AXPress"
AX_SHOW_MENU = "AXShowMenu"
AX_ROWS = "AXRows"
AX_VISIBLE_ROWS = "AXVisibleRows"
AX_SELECTED_ROWS = "AXSelectedRows"

MESSAGE_LIST_TITLES = {"messages", "消息"}
INPUT_IDENTIFIERS = {"chat_input_field", "chatInputField", "message_input"}
SEARCH_TITLES = {"search", "搜索"}
CHROME_TEXTS = {
    "wechat",
    "微信",
    "search",
    "搜索",
    "chats",
    "contacts",
    "messages",
    "消息",
    "send",
    "发送",
    "sticker",
    "stickers",
    "emoji",
    "file",
    "photo",
    "voice",
    "video",
    "hide stickied chats",
    "stickied chats",
    "new chat",
    "details",
    "moments",
    "favorites",
    "search chat history",
    "voice call",
    "video call",
    "attachment",
    "screenshot",
    "handoff",
    "profile photo",
}


class AccessibilityUnavailable(RuntimeError):
    pass


def _load_objc() -> dict[str, Any]:
    try:
        from ApplicationServices import (  # type: ignore
            AXIsProcessTrusted,
            AXIsProcessTrustedWithOptions,
            AXUIElementCopyAttributeNames,
            AXUIElementCopyAttributeValue,
            AXUIElementCreateApplication,
            AXUIElementPerformAction,
            AXUIElementSetAttributeValue,
            AXValueGetValue,
            kAXTrustedCheckOptionPrompt,
            kAXValueCGPointType,
            kAXValueCGSizeType,
        )
        from Cocoa import (  # type: ignore
            NSRunningApplication,
            NSWorkspace,
            NSApplicationActivateIgnoringOtherApps,
        )
        from Quartz import (  # type: ignore
            CGEventCreateKeyboardEvent,
            CGEventPost,
            CGEventSetFlags,
            CGEventSourceCreate,
            kCGEventSourceStateHIDSystemState,
            kCGHIDEventTap,
            CGEventCreateMouseEvent,
            kCGEventLeftMouseDown,
            kCGEventLeftMouseUp,
            kCGMouseButtonLeft,
            kCGEventRightMouseDown,
            kCGEventRightMouseUp,
            kCGMouseButtonRight,
        )
        import Quartz  # type: ignore
    except ImportError as exc:
        raise AccessibilityUnavailable(
            "当前环境缺少 macOS Accessibility 绑定。请安装：pip install -r requirements.txt"
        ) from exc
    return {
        "AXIsProcessTrusted": AXIsProcessTrusted,
        "AXIsProcessTrustedWithOptions": AXIsProcessTrustedWithOptions,
        "AXUIElementCopyAttributeNames": AXUIElementCopyAttributeNames,
        "AXUIElementCopyAttributeValue": AXUIElementCopyAttributeValue,
        "AXUIElementCreateApplication": AXUIElementCreateApplication,
        "AXUIElementPerformAction": AXUIElementPerformAction,
        "AXUIElementSetAttributeValue": AXUIElementSetAttributeValue,
        "AXValueGetValue": AXValueGetValue,
        "kAXTrustedCheckOptionPrompt": kAXTrustedCheckOptionPrompt,
        "kAXValueCGPointType": kAXValueCGPointType,
        "kAXValueCGSizeType": kAXValueCGSizeType,
        "NSRunningApplication": NSRunningApplication,
        "NSWorkspace": NSWorkspace,
        "NSApplicationActivateIgnoringOtherApps": NSApplicationActivateIgnoringOtherApps,
        "CGEventCreateKeyboardEvent": CGEventCreateKeyboardEvent,
        "CGEventPost": CGEventPost,
        "CGEventSetFlags": CGEventSetFlags,
        "CGEventSourceCreate": CGEventSourceCreate,
        "kCGEventSourceStateHIDSystemState": kCGEventSourceStateHIDSystemState,
        "kCGHIDEventTap": kCGHIDEventTap,
        "CGEventCreateMouseEvent": CGEventCreateMouseEvent,
        "kCGEventLeftMouseDown": kCGEventLeftMouseDown,
        "kCGEventLeftMouseUp": kCGEventLeftMouseUp,
        "kCGMouseButtonLeft": kCGMouseButtonLeft,
        "kCGEventRightMouseDown": kCGEventRightMouseDown,
        "kCGEventRightMouseUp": kCGEventRightMouseUp,
        "kCGMouseButtonRight": kCGMouseButtonRight,
        "Quartz": Quartz,
    }


_OBJC: dict[str, Any] | None = None


def objc() -> dict[str, Any]:
    global _OBJC
    if _OBJC is None:
        _OBJC = _load_objc()
    return _OBJC


def is_trusted(prompt: bool = False) -> bool:
    api = objc()
    if prompt:
        try:
            options = {api["kAXTrustedCheckOptionPrompt"]: True}
            return bool(api["AXIsProcessTrustedWithOptions"](options))
        except Exception:
            pass
    try:
        return bool(api["AXIsProcessTrusted"]())
    except Exception:
        return False


def process_identity() -> dict[str, Any]:
    """Which binary macOS actually checks for Accessibility — usually Python.app, not Cursor."""
    executable = os.path.realpath(sys.executable)
    python_app = None
    path = Path(executable)
    for parent in [path.parent, *path.parents]:
        candidate = parent / "Resources" / "Python.app"
        if candidate.exists():
            python_app = str(candidate)
            break
        if parent.name.endswith(".app") and (parent / "Contents").exists():
            python_app = str(parent)
            break
    launcher = None
    for candidate in (
        Path("/Applications") / "微信回复助手.app",
        Path.home() / "Applications" / "微信回复助手.app",
        Path.home() / "Desktop" / "微信回复助手.app",
    ):
        if candidate.exists():
            launcher = candidate
            break
    launcher_app = str(launcher) if launcher else None
    inside_app = "微信回复助手.app" in executable
    if inside_app:
        target = launcher_app or executable
    else:
        target = python_app or executable
    return {
        "pid": os.getpid(),
        "executable": executable,
        "python_app": python_app,
        "launcher_app": launcher_app,
        "ax_target": target,
    }


def permission_hint() -> str:
    ident = process_identity()
    exe = ident.get("executable") or ""
    if "微信回复助手.app" in exe:
        target = ident.get("launcher_app") or ident["ax_target"]
        return (
            "请把「微信回复助手」勾进辅助功能。"
            "打开「系统设置 → 隐私与安全性 → 辅助功能」，找到「微信回复助手」并打开。"
            f"若列表里没有，点「+」添加：\n{target}\n"
            "打开开关后必须完全退出助手再打开一次。只勾选 Cursor 无效。"
        )
    target = ident.get("python_app") or exe
    return (
        "授权「微信回复助手」图标还不够：当前实际读微信的是 Python 进程。"
        "请打开「系统设置 → 隐私与安全性 → 辅助功能」，点左下角「+」，添加下面这个程序"
        f"（列表里可能叫 Python）：\n{target}\n"
        "添加并打开开关后，必须重启本助手才会生效。"
        "若你是从 App 打开却看到这条说明，请重新运行 scripts/install-app.sh。"
    )


def open_accessibility_settings() -> None:
    import subprocess

    subprocess.Popen(
        [
            "open",
            "x-apple.systempreferences:com.apple.settings.PrivacySecurity.extension?Privacy_Accessibility",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def ax_get(element: Any, attribute: str) -> Any:
    api = objc()
    err, value = api["AXUIElementCopyAttributeValue"](element, attribute, None)
    if err != 0:
        return None
    return value


def ax_names(element: Any) -> list[str]:
    api = objc()
    err, names = api["AXUIElementCopyAttributeNames"](element, None)
    if err != 0:
        return []
    return [str(n) for n in (names or [])]


def ax_set(element: Any, attribute: str, value: Any) -> bool:
    api = objc()
    err = api["AXUIElementSetAttributeValue"](element, attribute, value)
    return err == 0


def ax_press(element: Any) -> bool:
    return ax_action(element, AX_PRESS)


def ax_action(element: Any, action: str) -> bool:
    api = objc()
    err = api["AXUIElementPerformAction"](element, action)
    return err == 0


def ax_show_menu(element: Any) -> bool:
    return ax_action(element, AX_SHOW_MENU)


def ax_str(value: Any) -> str:
    if value is None:
        return ""
    try:
        return str(value).strip()
    except Exception:
        return ""


def ax_role(element: Any) -> str:
    return ax_str(ax_get(element, AX_ROLE))


def table_rows(table_el: Any, *, visible: bool = False) -> list[Any]:
    """Prefer native table row attributes so we don't walk every AX child."""
    attrs = (AX_VISIBLE_ROWS, AX_ROWS, AX_CHILDREN) if visible else (AX_ROWS, AX_VISIBLE_ROWS, AX_CHILDREN)
    for attr in attrs:
        rows = ax_get(table_el, attr)
        if rows:
            return list(rows)
    return []


def selected_table_rows(table_el: Any) -> list[Any]:
    rows = ax_get(table_el, AX_SELECTED_ROWS)
    if rows:
        return list(rows)
    found: list[Any] = []
    visible = ax_get(table_el, AX_VISIBLE_ROWS)
    candidates = list(visible) if visible else table_rows(table_el)[:80]
    for row in candidates:
        if bool(ax_get(row, AX_SELECTED)):
            found.append(row)
            break
        cells = list(ax_get(row, AX_CHILDREN) or [])[:3]
        if any(bool(ax_get(cell, AX_SELECTED)) for cell in cells):
            found.append(row)
            break
    return found


def ax_point(element: Any) -> tuple[float, float] | None:
    raw = ax_get(element, AX_POSITION)
    return _unpack_point(raw)


def ax_size(element: Any) -> tuple[float, float] | None:
    raw = ax_get(element, AX_SIZE)
    return _unpack_size(raw)


def _unpack_point(raw: Any) -> tuple[float, float] | None:
    if raw is None:
        return None
    api = objc()
    try:
        ok, point = api["AXValueGetValue"](raw, api["kAXValueCGPointType"], None)
        if ok and point is not None:
            return float(point.x), float(point.y)
    except Exception:
        pass
    match = re.search(r"x:\s*(-?\d+(?:\.\d+)?)\s+y:\s*(-?\d+(?:\.\d+)?)", str(raw))
    if match:
        return float(match.group(1)), float(match.group(2))
    return None


def _unpack_size(raw: Any) -> tuple[float, float] | None:
    if raw is None:
        return None
    api = objc()
    try:
        ok, size = api["AXValueGetValue"](raw, api["kAXValueCGSizeType"], None)
        if ok and size is not None:
            return float(size.width), float(size.height)
    except Exception:
        pass
    match = re.search(r"w:\s*(-?\d+(?:\.\d+)?)\s+h:\s*(-?\d+(?:\.\d+)?)", str(raw))
    if match:
        return float(match.group(1)), float(match.group(2))
    return None


def _extract_floats(text: str) -> list[float]:
    import re

    return [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", text)]


@dataclass
class AXNode:
    element: Any
    role: str
    title: str
    identifier: str
    description: str
    value: str
    x: float | None = None
    y: float | None = None
    w: float | None = None
    h: float | None = None

    def label(self) -> str:
        return self.title or self.description or self.identifier or self.value


SKIP_DESCEND_ROLES = {
    "AXWebArea",
    "AXImage",
    "AXBusyIndicator",
    "AXProgressIndicator",
    "AXScrollBar",
    "AXLayoutArea",
}


def describe(element: Any, *, geometry: bool = False, value: bool = False) -> AXNode:
    pos = ax_point(element) if geometry else None
    size = ax_size(element) if geometry else None
    return AXNode(
        element=element,
        role=ax_str(ax_get(element, AX_ROLE)),
        title=ax_str(ax_get(element, AX_TITLE)),
        identifier=ax_str(ax_get(element, AX_IDENTIFIER)),
        description=ax_str(ax_get(element, AX_DESCRIPTION)),
        value=ax_str(ax_get(element, AX_VALUE)) if value else "",
        x=pos[0] if pos else None,
        y=pos[1] if pos else None,
        w=size[0] if size else None,
        h=size[1] if size else None,
    )


def find_wechat_app() -> tuple[Any, int, str]:
    api = objc()
    workspace = api["NSWorkspace"].sharedWorkspace()
    running = workspace.runningApplications()
    for app in running:
        bid = ax_str(app.bundleIdentifier())
        name = ax_str(app.localizedName())
        if bid in WECHAT_BUNDLE_IDS or name in WECHAT_APP_NAMES:
            pid = int(app.processIdentifier())
            ax_app = api["AXUIElementCreateApplication"](pid)
            return ax_app, pid, name or bid
    raise AccessibilityUnavailable("未找到正在运行的微信。请先打开 Mac 版微信。")


def activate_wechat() -> None:
    api = objc()
    _, pid, _ = find_wechat_app()
    running = api["NSRunningApplication"].runningApplicationWithProcessIdentifier_(pid)
    if running is not None:
        running.activateWithOptions_(api["NSApplicationActivateIgnoringOtherApps"])


def main_window(ax_app: Any) -> Any:
    focused = ax_get(ax_app, AX_FOCUSED_WINDOW)
    if focused is not None:
        return focused
    windows = list(ax_get(ax_app, AX_WINDOWS) or [])
    if not windows:
        raise AccessibilityUnavailable(
            "读不到微信窗口。请把微信放到前台，并确认已授予辅助功能权限。"
        )
    # Prefer the largest window — usually the main chat window.
    def area(win: Any) -> float:
        size = ax_size(win) or (0.0, 0.0)
        return size[0] * size[1]

    windows.sort(key=area, reverse=True)
    return windows[0]


def walk(
    element: Any,
    max_depth: int = 8,
    max_nodes: int = 400,
) -> list[AXNode]:
    out: list[AXNode] = []
    stack: list[tuple[Any, int]] = [(element, 0)]
    seen = 0
    while stack:
        current, depth = stack.pop()
        seen += 1
        if seen > max_nodes:
            break
        node = describe(current, value=True)
        out.append(node)
        if depth >= max_depth or node.role in SKIP_DESCEND_ROLES:
            continue
        children = list(ax_get(current, AX_CHILDREN) or [])
        for child in reversed(children[:40]):
            stack.append((child, depth + 1))
    return out


def dfs(
    element: Any,
    predicate: Callable[[AXNode], bool],
    max_depth: int = 8,
    max_nodes: int = 300,
    geometry: bool = False,
    value: bool = False,
) -> AXNode | None:
    stack: list[tuple[Any, int]] = [(element, 0)]
    seen = 0
    while stack:
        current, depth = stack.pop()
        seen += 1
        if seen > max_nodes:
            break
        node = describe(current, geometry=geometry, value=value)
        if predicate(node):
            return node
        if depth >= max_depth or node.role in SKIP_DESCEND_ROLES:
            continue
        children = list(ax_get(current, AX_CHILDREN) or [])
        for child in reversed(children[:40]):
            stack.append((child, depth + 1))
    return None


def collect(
    element: Any,
    predicate: Callable[[AXNode], bool],
    max_depth: int = 8,
    max_nodes: int = 300,
    geometry: bool = False,
    value: bool = False,
) -> list[AXNode]:
    found: list[AXNode] = []
    stack: list[tuple[Any, int]] = [(element, 0)]
    seen = 0
    while stack:
        current, depth = stack.pop()
        seen += 1
        if seen > max_nodes:
            break
        node = describe(current, geometry=geometry, value=value)
        if predicate(node):
            found.append(node)
        if depth >= max_depth or node.role in SKIP_DESCEND_ROLES:
            continue
        children = list(ax_get(current, AX_CHILDREN) or [])
        for child in reversed(children[:40]):
            stack.append((child, depth + 1))
    return found


SKIP_MENU_SEARCH_ROLES = SKIP_DESCEND_ROLES | {
    "AXTable",
    "AXTextArea",
    "AXTextField",
    "AXOutline",
    "AXBrowser",
}


def collect_menu_items(ax_app: Any, max_nodes: int = 400) -> list[AXNode]:
    """Find AXMenuItem nodes without walking the chat transcript table."""
    found: list[AXNode] = []
    stack: list[tuple[Any, int]] = [(ax_app, 0)]
    seen = 0
    while stack:
        current, depth = stack.pop()
        seen += 1
        if seen > max_nodes:
            break
        node = describe(current, geometry=True)
        if node.role == "AXMenuItem":
            found.append(node)
            continue
        if depth >= 10 or node.role in SKIP_MENU_SEARCH_ROLES:
            continue
        children = list(ax_get(current, AX_CHILDREN) or [])
        for child in reversed(children[:40]):
            stack.append((child, depth + 1))
    return found


def click_center(node: AXNode) -> bool:
    if node.x is None or node.y is None or node.w is None or node.h is None:
        return ax_press(node.element)
    x = node.x + node.w / 2
    y = node.y + node.h / 2
    return click_xy(x, y)


def click_xy(x: float, y: float) -> bool:
    return _mouse_click(x, y, left=True)


def right_click_center(node: AXNode) -> bool:
    if node.x is None or node.y is None or node.w is None or node.h is None:
        return False
    x = node.x + max(node.w, 8) / 2
    y = node.y + max(node.h, 8) / 2
    return right_click_xy(x, y)


def right_click_xy(x: float, y: float) -> bool:
    return _mouse_click(x, y, left=False)


def _mouse_click(x: float, y: float, left: bool = True) -> bool:
    api = objc()
    try:
        if left:
            down_type, up_type, button = (
                api["kCGEventLeftMouseDown"],
                api["kCGEventLeftMouseUp"],
                api["kCGMouseButtonLeft"],
            )
        else:
            down_type, up_type, button = (
                api["kCGEventRightMouseDown"],
                api["kCGEventRightMouseUp"],
                api["kCGMouseButtonRight"],
            )
        down = api["CGEventCreateMouseEvent"](None, down_type, (x, y), button)
        up = api["CGEventCreateMouseEvent"](None, up_type, (x, y), button)
        api["CGEventPost"](api["kCGHIDEventTap"], down)
        api["CGEventPost"](api["kCGHIDEventTap"], up)
        return True
    except Exception:
        return False


KEYCODE_RETURN = 36
KEYCODE_ESCAPE = 53
KEYCODE_A = 0
KEYCODE_V = 9
KEYCODE_COMMAND = 55
FLAG_COMMAND = 1 << 20  # kCGEventFlagMaskCommand = 0x100000


def press_key(keycode: int, flags: int = 0) -> None:
    api = objc()
    source = api["CGEventSourceCreate"](api["kCGEventSourceStateHIDSystemState"])
    down = api["CGEventCreateKeyboardEvent"](source, keycode, True)
    up = api["CGEventCreateKeyboardEvent"](source, keycode, False)
    api["CGEventSetFlags"](down, flags)
    api["CGEventSetFlags"](up, flags)
    api["CGEventPost"](api["kCGHIDEventTap"], down)
    api["CGEventPost"](api["kCGHIDEventTap"], up)


def press_return() -> None:
    # flags=0 avoids inheriting Command/Shift from a previous shortcut.
    press_key(KEYCODE_RETURN, 0)


def paste_via_clipboard(text: str) -> None:
    from AppKit import NSPasteboard, NSPasteboardTypeString  # type: ignore
    import time

    board = NSPasteboard.generalPasteboard()
    previous_types = list(board.types() or [])
    previous = board.stringForType_(NSPasteboardTypeString)

    board.clearContents()
    board.setString_forType_(text, NSPasteboardTypeString)
    time.sleep(0.05)
    press_key(KEYCODE_A, FLAG_COMMAND)
    time.sleep(0.04)
    press_key(KEYCODE_V, FLAG_COMMAND)
    time.sleep(0.08)

    board.clearContents()
    if previous:
        board.setString_forType_(previous, NSPasteboardTypeString)
    elif previous_types:
        # Best-effort restore; do not keep the composed reply on the clipboard.
        pass


def dump_tree(max_depth: int = 6) -> list[dict[str, Any]]:
    if not is_trusted():
        return [{"error": "辅助功能权限未授予"}]
    ax_app, pid, name = find_wechat_app()
    window = main_window(ax_app)
    rows: list[dict[str, Any]] = []
    for node in walk(window, max_depth=max_depth, max_nodes=400):
        rows.append(
            {
                "role": node.role,
                "title": node.title,
                "id": node.identifier,
                "desc": node.description,
                "value": node.value[:80],
                "x": node.x,
                "y": node.y,
                "w": node.w,
                "h": node.h,
            }
        )
    return [{"app": name, "pid": pid, "count": len(rows)}, *rows[:200]]


def is_chrome_text(text: str) -> bool:
    lowered = text.strip().lower()
    if not lowered:
        return True
    if lowered in CHROME_TEXTS:
        return True
    if len(lowered) > 2000:
        return True
    return False
