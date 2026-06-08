# Telegram Company Bridge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a reusable Telegram bridge so software-company departments can discover topic IDs and send owner reports or department messages without storing secrets in git.

**Architecture:** A standalone Python CLI under `scripts/software_company` reads all Telegram credentials from environment variables, uses Telegram Bot API over HTTPS, and keeps OneShare-specific behavior out of the bridge. Tests cover topic extraction and env-topic mapping without touching the network.

**Tech Stack:** Python standard library, pytest, Telegram Bot API.

---

### Task 1: Telegram Bridge CLI

**Files:**
- Create: `scripts/software_company/telegram_bridge.py`
- Test: `tests/test_telegram_bridge.py`
- Modify: `docs/software-company/README.md`

- [x] **Step 1: Add a standalone CLI**

Create `scripts/software_company/telegram_bridge.py` with commands:

```sh
python3 scripts/software_company/telegram_bridge.py updates
python3 scripts/software_company/telegram_bridge.py send "message" --topic owner-review
python3 scripts/software_company/telegram_bridge.py send-owner-review --project cosuite
```

- [x] **Step 2: Keep secrets in environment variables**

The CLI reads `TELEGRAM_BOT_TOKEN`, `TELEGRAM_COMPANY_CHAT_ID`, and `TELEGRAM_TOPIC_*` values from runtime env only.

- [x] **Step 3: Add tests for topic extraction**

`tests/test_telegram_bridge.py` verifies unique `chat_id` and `message_thread_id` extraction from sample Telegram updates.

- [x] **Step 4: Document setup and usage**

`docs/software-company/README.md` now lists the required variables and the bridge commands.
