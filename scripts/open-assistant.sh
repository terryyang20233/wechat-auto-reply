#!/bin/zsh
set -euo pipefail

APP="$HOME/Applications/微信回复助手.app"
if [[ -d "$APP" ]]; then
  exec /usr/bin/open -a "$APP"
fi

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
URL="http://127.0.0.1:8765"
PY="$ROOT/.venv/bin/python"

if /usr/bin/curl -sf --max-time 0.6 "$URL/api/health" >/dev/null 2>&1; then
  /usr/bin/open "$URL"
  exit 0
fi

if [[ ! -x "$PY" ]]; then
  /usr/bin/osascript -e 'display dialog "还没有安装运行环境，也还没有生成「微信回复助手」App。请先在项目目录安装依赖。" buttons {"好"} default button 1 with title "微信回复助手" with icon stop'
  exit 1
fi

cd "$ROOT"
exec "$PY" -m wechat_assist
