#!/bin/zsh
APP="$HOME/Applications/微信回复助手.app"
if [[ -d "$APP" ]]; then
  exec /usr/bin/open -a "$APP"
fi
cd -- "$(dirname "$0")"
exec ./scripts/open-assistant.sh
