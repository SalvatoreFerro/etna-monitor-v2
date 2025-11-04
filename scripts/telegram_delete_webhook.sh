#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${TELEGRAM_BOT_TOKEN:-}" ]]; then
  echo "TELEGRAM_BOT_TOKEN environment variable is required" >&2
  exit 1
fi

curl -fsSL "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/deleteWebhook"
