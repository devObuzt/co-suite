# OneShare — project instructions

## Telegram owner loop

The owner communicates through the Telegram company group (config in
`api/.env`, bridge at `scripts/software_company/telegram_bridge.py`).

- When the user asks to send a report ("ابعتلي تقرير", "send me a report",
  etc.), use the `/telegram-report` skill. Reports go to Telegram topics and
  the owner replies to them there.
- When the user asks to check notes ("شيك الملاحظات", "check telegram"), or at
  the start of a substantial work session, use the `/telegram-inbox` skill:
  run `fetch-notes` and check `docs/software-company/owner-feedback/inbox/`
  for pending owner requests — treat them as work items.
- Always load env first: `set -a; source api/.env; set +a`.
