#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${CRON_SECRET:-}" ]]; then
  echo "CRON_SECRET is not set"
  exit 1
fi

response="$(curl -s -X POST "https://etnamonitor.it/internal/cron/check-alerts?key=${CRON_SECRET}")"
echo "${response}" | jq

echo "${response}" | jq -e '
  if (.diagnostic.premium_samples | type) != "array" then
    error("missing premium_samples")
  else
    .diagnostic.premium_samples
    | all(.threshold_source == "user" or .threshold_source == "fallback_default")
    and all(
      if .threshold_source == "fallback_default"
      then .threshold_fallback_used == true
      else true
      end
    )
  end
' > /dev/null
