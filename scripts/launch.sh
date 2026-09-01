#!/bin/bash
# 微信回复助手启动器（唱机同款：StayOpen 小程序 + 后台服务）。
# WECHAT_ASSIST_DETACH=1：拉起服务、打开浏览器后退出（给 .app / AppleScript 用）。
LOG="${HOME}/.wechat-assist/server.log"
PID_FILE="${HOME}/.wechat-assist/server.pid"
mkdir -p "$(dirname "$LOG")"
if [[ ! -t 1 ]]; then
  exec >>"$LOG" 2>&1
fi

echo
echo "==== $(date '+%Y-%m-%d %H:%M:%S') pid=$$ detach=${WECHAT_ASSIST_DETACH:-0} ===="
echo "PATH=${PATH-}"

alert() {
  /usr/bin/osascript -e "display dialog \"$1\" buttons {\"好\"} default button 1 with title \"微信回复助手\" with icon stop" >/dev/null 2>&1 || true
}

notify() {
  /usr/bin/osascript -e "display notification \"$1\" with title \"微信回复助手\"" >/dev/null 2>&1 || true
}

resolve_root() {
  if [[ -n "${WECHAT_ASSIST_ROOT:-}" && -f "${WECHAT_ASSIST_ROOT}/pyproject.toml" ]]; then
    printf '%s' "$WECHAT_ASSIST_ROOT"
    return
  fi
  local here bundled
  here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  if [[ -f "$here/../Resources/project-root" ]]; then
    bundled="$(tr -d '\n' < "$here/../Resources/project-root")"
    if [[ -f "$bundled/pyproject.toml" ]]; then
      printf '%s' "$bundled"
      return
    fi
  fi
  if [[ -f "$here/project-root" ]]; then
    bundled="$(tr -d '\n' < "$here/project-root")"
    if [[ -f "$bundled/pyproject.toml" ]]; then
      printf '%s' "$bundled"
      return
    fi
  fi
  if [[ "$(basename "$here")" == "MacOS" && -f "$here/../../../pyproject.toml" ]]; then
    (cd "$here/../../.." && pwd)
    return
  fi
  if [[ -f "$here/../pyproject.toml" ]]; then
    (cd "$here/.." && pwd)
    return
  fi
  return 1
}

ROOT="$(resolve_root || true)"
echo "ROOT=$ROOT"
if [[ -z "${ROOT:-}" || ! -f "$ROOT/pyproject.toml" ]]; then
  alert "找不到项目目录。请在项目里重新运行 scripts/install-app.sh。"
  exit 1
fi

export HOME="${HOME:-/Users/$(id -un)}"
export LANG="${LANG:-zh_CN.UTF-8}"
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH}"

URL="http://127.0.0.1:8765"
CURL="/usr/bin/curl"

health_ok() {
  "$CURL" -fsS --connect-timeout 1 --max-time 2 "${URL}/api/health" >/dev/null 2>&1
}

cd "$ROOT" || {
  alert "无法进入项目目录：$ROOT"
  exit 1
}

if health_ok; then
  echo "already running"
  /usr/bin/open "$URL"
  exit 0
fi

PY="$ROOT/.venv/bin/python"
if [[ ! -x "$PY" ]]; then
  notify "正在创建运行环境，请稍候…"
  PYTHON3="$(command -v python3 || true)"
  if [[ -z "$PYTHON3" ]]; then
    PYTHON3="$(/bin/zsh -lic 'whence -p python3' 2>/dev/null | tail -1 || true)"
  fi
  if [[ -z "$PYTHON3" || ! -x "$PYTHON3" ]]; then
    alert "找不到 Python 3。请先安装 Python 3.11+，再打开助手。"
    exit 1
  fi
  if ! "$PYTHON3" -m venv "$ROOT/.venv"; then
    alert "创建虚拟环境失败。日志：${LOG}"
    exit 1
  fi
  PY="$ROOT/.venv/bin/python"
fi

if ! "$PY" -c "import wechat_assist, fastapi, uvicorn" >/dev/null 2>&1; then
  notify "正在安装依赖，请稍候…"
  if ! "$PY" -m pip install -e "${ROOT}[macos]"; then
    alert "依赖安装失败。日志：${LOG}"
    exit 1
  fi
fi

notify "正在启动微信回复助手…"
nohup "$PY" -m wechat_assist >/dev/null 2>>"$LOG" &
SERVER_PID=$!
echo "$SERVER_PID" >"$PID_FILE"
echo "server pid=$SERVER_PID"

ok=0
i=0
while [[ $i -lt 50 ]]; do
  if health_ok; then
    ok=1
    break
  fi
  if ! kill -0 "$SERVER_PID" 2>/dev/null; then
    break
  fi
  i=$((i + 1))
  sleep 0.2
done

if [[ "$ok" != 1 ]]; then
  alert "助手没有启动成功。可打开日志：${LOG}"
  exit 1
fi

/usr/bin/open "$URL"

if [[ "${WECHAT_ASSIST_DETACH:-0}" == "1" ]]; then
  echo "detached"
  exit 0
fi

cleanup() {
  if [[ -n "${SERVER_PID:-}" ]] && kill -0 "$SERVER_PID" 2>/dev/null; then
    kill "$SERVER_PID" 2>/dev/null || true
    wait "$SERVER_PID" 2>/dev/null || true
  fi
  rm -f "$PID_FILE"
}
trap cleanup EXIT INT TERM
wait "$SERVER_PID"
