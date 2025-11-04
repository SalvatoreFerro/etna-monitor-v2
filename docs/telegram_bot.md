# Telegram bot deployment checklist

This project uses a dedicated Render worker that runs the Telegram bot in polling mode.
Follow the steps below whenever you deploy or troubleshoot the bot.

## Verify the webhook is disabled

1. Retrieve the current webhook configuration:
   ```
   https://api.telegram.org/bot<token>/getWebhookInfo
   ```
2. If the response contains a non-empty `url`, disable it explicitly:
   ```
   https://api.telegram.org/bot<token>/deleteWebhook
   ```
3. Confirm that the webhook is cleared by repeating step 1.

## Validate the bot token

Use the following endpoint to confirm that the bot token is valid and Telegram is reachable:
```
https://api.telegram.org/bot<token>/getMe
```
The response must include `"ok": true`.

## Render worker expectations

* Worker start command: `python worker_telegram_bot.py`
* Logs must contain the line `Starting Telegram polling…` shortly after startup.
* The worker requires the `TELEGRAM_BOT_TOKEN` environment variable (configured in Render).

## Manual smoke test

* Open Telegram and send `/start` to the bot – it should respond within two seconds.
* Send `/help` to confirm that the command list is returned.
* Review the worker logs on Render to ensure there are no startup errors.

## Optional helper script

The repository provides `scripts/telegram_delete_webhook.sh` to quickly disable the webhook
from a local shell session. Export `TELEGRAM_BOT_TOKEN` before running it.
