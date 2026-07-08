---
name: telegram-inbox
description: Fetch the owner's Telegram replies/notes into the repo and act on them. Use when the user says "شيك الملاحظات", "شو رديت عالتلجرام", "check telegram", "telegram inbox", or at the start of work sessions to pick up pending owner requests.
---

# Telegram Inbox

Pull the owner's Telegram notes (replies to reports, or plain messages in the
company group) into `docs/software-company/owner-feedback/inbox/` and act on
them.

## Steps

1. Fetch:

   ```sh
   set -a; source api/.env; set +a
   python3 scripts/software_company/telegram_bridge.py fetch-notes
   ```

   The command prints each new note in full, including the excerpt of the
   report it replied to (`## In reply to`), so you know which task it targets.

2. Also check for older unprocessed notes:

   ```sh
   ls docs/software-company/owner-feedback/inbox/
   ```

3. For each note, in chronological order:
   - If it's an instruction/request: do the work (or add it to the current
     plan and tell the user).
   - If it's feedback on a report: apply it to the relevant task.
   - If it's ambiguous: ask the user before acting.

4. After a note is fully handled, change its `Status: new` line to
   `Status: done — <one-line summary>` and move the file to
   `docs/software-company/owner-feedback/processed/` (`git mv` if tracked).

5. Summarize to the user: how many notes, what each asked, what was done.
