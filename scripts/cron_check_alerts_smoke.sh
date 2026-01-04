#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${CRON_SECRET:-}" ]]; then
  echo "CRON_SECRET is not set"
  exit 1
fi

curl -s -X POST "https://etnamonitor.it/internal/cron/check-alerts?key=${CRON_SECRET}" | jq
