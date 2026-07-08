---
name: telegram-report
description: Send a task/status report to the owner's Telegram company group so the owner can reply with notes. Use when the user says "ابعتلي تقرير", "ابعث تقرير عالتلجرام", "send me a report", "telegram report", or asks to report task status to Telegram — from any conversation in this project.
---

# Telegram Report

Send a report about the current work to the Telegram company group. The owner
replies to it in Telegram, and `/telegram-inbox` pulls those replies back into
the repo for any session to act on.

## Steps

1. Compose the report in Markdown (Arabic unless asked otherwise). Keep it
   under ~3500 chars. Structure:
   - **العنوان**: what task/session this is about + timestamp
   - **شو انعمل**: concrete changes (files, commits, deploys)
   - **الوضع الحالي**: working / blocked / needs decision
   - **أسئلة للمالك**: anything needing a decision (numbered, so replies can
     reference them)
   - End with: `للرد: اعمل Reply على هاي الرسالة بتلجرام وملاحظاتك بتوصل لأي جلسة بالمشروع.`

2. Write it to a temp file (scratchpad), then send:

   ```sh
   set -a; source api/.env; set +a
   python3 scripts/software_company/telegram_bridge.py send --topic owner-review --file <report.md>
   ```

   Pick a more specific topic when it fits: `qa`, `devops`, `incidents`,
   `developers`, `product`, `architecture`, `design`, `project-management`,
   `developers-manager` (see `TOPIC_ENV_KEYS` in
   `scripts/software_company/telegram_bridge.py`).

3. Before sending, also run `fetch-notes` once so pending owner notes aren't
   left unread:

   ```sh
   python3 scripts/software_company/telegram_bridge.py fetch-notes
   ```

   If new notes appear in `docs/software-company/owner-feedback/inbox/`,
   surface them to the user and factor them into the report.

4. Confirm to the user that the report was sent and that replying to it in
   Telegram will reach any project session via `/telegram-inbox`.
