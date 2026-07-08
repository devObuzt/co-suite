# Owner Feedback

Notes, comments, and requests the owner sends in the Telegram company group —
usually as replies to task reports the bridge sent.

## Flow

1. A Claude session sends a report to Telegram:

   ```sh
   set -a; source api/.env; set +a
   python3 scripts/software_company/telegram_bridge.py send --topic owner-review --file report.md
   ```

2. The owner replies to the report message in Telegram (any topic works;
   plain messages in the group are captured too, slash commands are ignored).

3. Any Claude session in this repo pulls the notes:

   ```sh
   set -a; source api/.env; set +a
   python3 scripts/software_company/telegram_bridge.py fetch-notes
   ```

   Each new note lands in `inbox/` as a markdown file that includes the
   original report excerpt it replied to.

4. When a note has been acted on, move its file to `processed/`.

`state.json` (gitignored) stores the Telegram `getUpdates` offset so notes are
fetched exactly once per machine; duplicate protection also comes from the
`update-<id>` suffix in filenames.

Related skills: `/telegram-report` (send a report), `/telegram-inbox`
(fetch + act on notes).
