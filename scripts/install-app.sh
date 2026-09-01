#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP="$ROOT/微信回复助手.app"
RES="$APP/Contents/Resources"
MACOS="$APP/Contents/MacOS"
ICONSET="$RES/AppIcon.iconset"
APPS_APP="/Applications/微信回复助手.app"
PY="${ROOT}/.venv/bin/python"
SRC="$ROOT/scripts/launcher.m"

if [[ ! -x "$PY" ]]; then
  echo "缺少虚拟环境：$PY" >&2
  echo "请先：python3 -m venv .venv && .venv/bin/pip install -e \".[macos]\"" >&2
  exit 1
fi
if [[ ! -f "$SRC" ]]; then
  echo "缺少 $SRC" >&2
  exit 1
fi

INC="$("$PY" -c "import sysconfig; print(sysconfig.get_config_var('INCLUDEPY'))")"
PY_PREFIX="$("$PY" -c "import sys; print(sys.base_prefix)")"
FRAMEWORKS="$(cd "$PY_PREFIX/../.." && pwd)"
if [[ "$(basename "$FRAMEWORKS")" != "Frameworks" ]]; then
  FRAMEWORKS="/Library/Frameworks"
fi

chmod +x "$ROOT/scripts/make-icon.py"

rm -rf "$APP"
mkdir -p "$MACOS" "$RES"
printf '%s' "$ROOT" > "$RES/project-root"

/usr/bin/cc -O2 -fobjc-arc \
  -I"$INC" \
  -o "$MACOS/WeChatAssist" \
  "$SRC" \
  -F"$FRAMEWORKS" \
  -framework Python \
  -framework Cocoa \
  -framework ApplicationServices \
  -Wl,-rpath,"$FRAMEWORKS"
/bin/chmod 755 "$MACOS/WeChatAssist"
mkdir -p "$APP/Contents/Helpers"
/bin/cp "$MACOS/WeChatAssist" "$APP/Contents/Helpers/wechat-assist-server"
/bin/chmod 755 "$APP/Contents/Helpers/wechat-assist-server"

python3 "$ROOT/scripts/make-icon.py" "$RES/icon.png"
rm -rf "$ICONSET"
mkdir -p "$ICONSET"
sips -z 16 16 "$RES/icon.png" --out "$ICONSET/icon_16x16.png" >/dev/null
sips -z 32 32 "$RES/icon.png" --out "$ICONSET/icon_16x16@2x.png" >/dev/null
sips -z 32 32 "$RES/icon.png" --out "$ICONSET/icon_32x32.png" >/dev/null
sips -z 64 64 "$RES/icon.png" --out "$ICONSET/icon_32x32@2x.png" >/dev/null
sips -z 128 128 "$RES/icon.png" --out "$ICONSET/icon_128x128.png" >/dev/null
sips -z 256 256 "$RES/icon.png" --out "$ICONSET/icon_128x128@2x.png" >/dev/null
sips -z 256 256 "$RES/icon.png" --out "$ICONSET/icon_256x256.png" >/dev/null
sips -z 512 512 "$RES/icon.png" --out "$ICONSET/icon_256x256@2x.png" >/dev/null
sips -z 512 512 "$RES/icon.png" --out "$ICONSET/icon_512x512.png" >/dev/null
sips -z 1024 1024 "$RES/icon.png" --out "$ICONSET/icon_512x512@2x.png" >/dev/null
iconutil -c icns "$ICONSET" -o "$RES/AppIcon.icns"
rm -rf "$ICONSET" "$RES/icon.png"

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
  <key>CFBundleIconFile</key>
  <string>AppIcon</string>
  <key>NSPrincipalClass</key>
  <string>NSApplication</string>
  <key>NSSupportsAutomaticTermination</key>
  <false/>
  <key>NSSupportsSuddenTermination</key>
  <false/>
  <key>LSMinimumSystemVersion</key>
  <string>12.0</string>
  <key>LSMultipleInstancesProhibited</key>
  <true/>
  <key>NSHighResolutionCapable</key>
  <true/>
</dict>
</plist>
PLIST
printf 'APPL????' > "$APP/Contents/PkgInfo"

touch "$APP"
xattr -cr "$APP" 2>/dev/null || true
codesign --force --deep --sign - "$APP" 2>/dev/null || true

if [[ -f "$HOME/.wechat-assist/server.pid" ]]; then
  kill "$(cat "$HOME/.wechat-assist/server.pid")" 2>/dev/null || true
fi
/usr/bin/killall WeChatAssist 2>/dev/null || true
/usr/bin/killall wechat-assist-server 2>/dev/null || true
/usr/bin/pkill -f 'python.*-m wechat_assist' 2>/dev/null || true
sleep 0.4

install_copy() {
  local dest="$1"
  mkdir -p "$(dirname "$dest")"
  rm -rf "$dest"
  ditto "$APP" "$dest"
  xattr -cr "$dest" 2>/dev/null || true
  codesign --force --deep --sign - "$dest" 2>/dev/null || true
}

install_copy "$APPS_APP"

echo "已创建：$APP"
echo "已放到：$APPS_APP"
echo "双击「微信回复助手」启动。若辅助功能里已有旧的「微信回复助手」，先关掉再打开一次（可删掉后用「+」重新添加本程序）。"
