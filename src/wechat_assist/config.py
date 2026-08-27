from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

CONFIG_DIR = Path.home() / ".wechat-assist"
SETTINGS_PATH = CONFIG_DIR / "settings.json"

ProviderName = Literal["openai", "anthropic", "gemini", "ollama", "custom"]
SendMode = Literal["fill_only", "fill_and_send"]
ReplyTone = Literal[
    "natural",
    "concise",
    "friendly",
    "professional",
    "warm",
    "humorous",
    "firm",
    "varied",
]


class AppSettings(BaseModel):
    provider: ProviderName = "openai"
    api_key: str = ""
    api_base: str = ""
    model: str = "gpt-4o-mini"
    n_suggestions: int = Field(default=3, ge=1, le=6)
    context_messages: int = Field(default=20, ge=4, le=80)
    anonymize_names: bool = True
    include_chat_name: bool = False
    reply_tone: ReplyTone = "natural"
    system_style: str = ""
    send_mode: SendMode = "fill_and_send"
    min_send_interval_seconds: float = Field(default=8.0, ge=2.0, le=120.0)
    max_sends_per_hour: int = Field(default=20, ge=1, le=80)
    human_delay_min: float = Field(default=0.7, ge=0.2, le=5.0)
    human_delay_max: float = Field(default=1.8, ge=0.3, le=8.0)

    def masked(self) -> dict[str, Any]:
        data = self.model_dump()
        key = data.get("api_key") or ""
        if len(key) > 8:
            data["api_key"] = key[:4] + "…" + key[-4:]
        elif key:
            data["api_key"] = "••••"
        return data


def load_settings() -> AppSettings:
    if not SETTINGS_PATH.exists():
        return AppSettings()
    try:
        raw = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        return AppSettings.model_validate(raw)
    except Exception:
        return AppSettings()


def save_settings(settings: AppSettings) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(
        settings.model_dump_json(indent=2),
        encoding="utf-8",
    )
    try:
        SETTINGS_PATH.chmod(0o600)
    except OSError:
        pass
