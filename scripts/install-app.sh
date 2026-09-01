#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP="$ROOT/微信回复助手.app"
RES="$APP/Contents/Resources"
ICONSET="$RES/AppIcon.iconset"
APPS_DIR="/Applications"
APPS_APP="${APPS_DIR}/微信回复助手.app"

chmod +x "$ROOT/scripts/launch.sh" "$ROOT/scripts/make-icon.py"

TMP_APP="$(mktemp -d)/微信回复助手.app"
osacompile -s -o "$TMP_APP" "$ROOT/scripts/WeChatAssist.applescript"
rm -rf "$APP"
ditto "$TMP_APP" "$APP"
rm -rf "$(dirname "$TMP_APP")"

mkdir -p "$RES"
printf '%s' "$ROOT" > "$RES/project-root"
cp "$ROOT/scripts/launch.sh" "$RES/launch.sh"
chmod +x "$RES/launch.sh"

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

PLIST="$APP/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Set :CFBundleName 微信回复助手" "$PLIST" 2>/dev/null || true
/usr/libexec/PlistBuddy -c "Set :CFBundleDisplayName 微信回复助手" "$PLIST" 2>/dev/null \
  || /usr/libexec/PlistBuddy -c "Add :CFBundleDisplayName string 微信回复助手" "$PLIST"
/usr/libexec/PlistBuddy -c "Set :CFBundleIconFile AppIcon" "$PLIST" 2>/dev/null \
  || /usr/libexec/PlistBuddy -c "Add :CFBundleIconFile string AppIcon" "$PLIST"
/usr/libexec/PlistBuddy -c "Set :CFBundleIdentifier local.wechat-assist.launcher" "$PLIST" 2>/dev/null \
  || /usr/libexec/PlistBuddy -c "Add :CFBundleIdentifier string local.wechat-assist.launcher" "$PLIST"
/usr/libexec/PlistBuddy -c "Add :LSMultipleInstancesProhibited bool true" "$PLIST" 2>/dev/null || true

touch "$APP"
xattr -cr "$APP" 2>/dev/null || true
codesign --force --deep --sign - "$APP" 2>/dev/null || true

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
echo "双击「微信回复助手」即可启动；从程序坞退出会关掉后台服务。"
