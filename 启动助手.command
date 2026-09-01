#!/bin/zsh
for APP in "/Applications/微信回复助手.app" "$HOME/Applications/微信回复助手.app"; do
  if [[ -d "$APP" ]]; then
    exec /usr/bin/open -a "$APP"
  fi
done
cd -- "$(dirname "$0")"
exec ./scripts/open-assistant.sh
