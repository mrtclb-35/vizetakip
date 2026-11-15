# Visa tracking Telegram bot

## Run on Replit

Keep the existing single-file Python 3.12 application. Dependencies are in
`requirements.txt`. Run `python -u main.py` using the **Visa tracking bot**
console workflow.

Before starting, add these settings in Replit Secrets:

- `TELEGRAM_TOKEN`: a newly rotated Telegram bot token from BotFather.
- `TELEGRAM_CHAT_ID`: the numeric Telegram chat ID allowed to receive alerts
  and issue commands. Open the bot and send `/start` so it can message you.

The imported source contained exposed credentials. Rotate the Telegram token
and proxy password at their providers; removing them from the current file
does not remove them from Git history or invalidate them.

Optional environment settings:

- `TELEGRAM_ALLOWED_USERS`: comma-separated numeric chat IDs. Defaults to
  `TELEGRAM_CHAT_ID`; overrides the full list of alert recipients and permitted
  command chats. Only include trusted private chats, since commands can set VFS tokens.
- `CHECK_INTERVAL`: full scan interval in seconds (default 1200). The separate
  vizetakip monitor checks every 300 seconds.
- `PROXY_HOST`: comma-separated proxy host:port entries; `PROXY_USER` and
  `PROXY_PASS` (Secret) supply proxy authentication. Alternatively set
  `WEBSHARE_URL` as a Secret for an existing proxy-list URL. With no proxy
  configured, requests are direct and some providers may block them.
- `VFS_EMAIL`, `VFS_PASSWORD` (Secret): optional existing VFS configuration.
  The bot's VFS API checks require a valid VFS token entered through the
  authorized Telegram `/token` command. Starting the process alone does not
  prove live appointment access works.
- `UPTIMEROBOT_API_KEY` (Secret): optional, used only for `/uptime`.
- `KEEP_ALIVE_URL`: optional external ping target; disabled by default.
- `DATA_DIR`: defaults to `.data/` beside `main.py`, storing site hashes and
  the VFS token. This private local directory is ignored by Git and publishing.
  It is workspace-local storage, not a durable production storage solution.

The bot is not a web app. Its existing health endpoint listens on
`0.0.0.0:8080` and returns `OK`; it is not a dashboard or proof of upstream
Telegram/VFS health. Starting the bot sends startup alerts and begins monitoring.
Do not run another copy with the same Telegram token while this one is polling.

## Local checks

Run `python -m unittest discover -s tests -v`. Tests mock external services;
real Telegram and VFS checks require the user's configured credentials.
