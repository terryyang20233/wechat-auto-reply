#!/bin/zsh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="$ROOT/.venv/bin/python"
APP="$HOME/Applications/微信回复助手.app"
SRC="$ROOT/scripts/launcher.c"

if [[ ! -x "$PY" ]]; then
  echo "缺少虚拟环境：$PY" >&2
  exit 1
fi
if [[ ! -f "$SRC" ]]; then
  echo "缺少 $SRC" >&2
  exit 1
fi

/bin/mkdir -p "$HOME/Applications"
/bin/rm -rf "$APP"
/bin/mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key>
  <string>微信回复助手</string>
  <key>CFBundleDisplayName</key>
  <string>微信回复助手</string>
  <key>CFBundleIdentifier</key>
  <string>local.wechat-assist.launcher</string>
  <key>CFBundleVersion</key>
  <string>0.1.1</string>
  <key>CFBundleShortVersionString</key>
  <string>0.1.1</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>CFBundleExecutable</key>
  <string>WeChatAssist</string>
  <key>LSMinimumSystemVersion</key>
  <string>12.0</string>
  <key>LSMultipleInstancesProhibited</key>
  <true/>
  <key>NSHighResolutionCapable</key>
  <true/>
</dict>
</plist>
PLIST

/usr/bin/cc -O2 \
  -DROOT_DIR="\"$ROOT\"" \
  -DPYTHON_BIN="\"$PY\"" \
  -o "$APP/Contents/MacOS/WeChatAssist" \
  "$SRC" \
  -framework ApplicationServices \
  -framework CoreFoundation

/bin/chmod 755 "$APP/Contents/MacOS/WeChatAssist"
/usr/bin/codesign --force --deep -s - "$APP" >/dev/null 2>&1 || true
/usr/bin/xattr -cr "$APP" >/dev/null 2>&1 || true

echo "$APP"
