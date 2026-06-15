from __future__ import annotations

from pathlib import Path
import subprocess

from scripts.software_company import autonomous_runner
from scripts.software_company.autonomous_runner import (
    CycleDecision,
    acquire_lock,
    choose_next_decision,
    parse_active_tasks,
    release_lock,
    telegram_messages_for_cycle,
    telegram_topic_for_department,
)


def test_autonomous_runner_prioritizes_qa_recheck() -> None:
    board = """
## Active Tasks

| ID | Milestone | Task | Owner | Status | Acceptance Criteria | Next Handoff |
| --- | --- | --- | --- | --- | --- | --- |
| QA-03 | M1 | Media preview and content action re-check | QA | needs_review | Findings recorded or marked clear. | Architecture |
| DEVMGR-03 | M1 | Product Bulk stability slice | Developers Manager | in_progress | Slice defined. | Developers |
"""
    decision = choose_next_decision("cosuite", parse_active_tasks(board))

    assert decision.task_id == "QA-03"
    assert decision.department == "QA"
    assert "continue autonomously" in decision.codex_prompt.lower()


def test_autonomous_runner_falls_back_to_in_progress_task() -> None:
    board = """
## Active Tasks

| ID | Milestone | Task | Owner | Status | Acceptance Criteria | Next Handoff |
| --- | --- | --- | --- | --- | --- | --- |
| DEVMGR-03 | M1 | Product Bulk stability slice | Developers Manager | in_progress | Slice defined. | Developers |
"""
    decision = choose_next_decision("cosuite", parse_active_tasks(board))

    assert decision.task_id == "DEVMGR-03"
    assert decision.department == "Developers Manager"


def test_department_topics_route_to_matching_telegram_topics() -> None:
    assert telegram_topic_for_department("QA") == "qa"
    assert telegram_topic_for_department("Architecture") == "architecture"
    assert telegram_topic_for_department("Developers Manager") == "developers-manager"
    assert telegram_topic_for_department("Unknown") == "project-management"


def test_autonomous_runner_skips_ready_handoff_when_actionable_work_exists() -> None:
    board = """
## Active Tasks

| ID | Milestone | Task | Owner | Status | Acceptance Criteria | Next Handoff |
| --- | --- | --- | --- | --- | --- | --- |
| QA-03 | M1 | Media preview and content action re-check | QA | ready_for_handoff | Findings recorded or marked clear. | Architecture |
| DEVMGR-03 | M1 | Product Bulk stability slice | Developers Manager | in_progress | Slice defined. | Developers |
| ARCH-02 | M1 | Post-stabilization architecture re-check | Architecture | not_started | Review latest flow. | Project Management |
"""
    decision = choose_next_decision("cosuite", parse_active_tasks(board))

    assert decision.task_id == "DEVMGR-03"
    assert decision.department == "Developers Manager"


def test_autonomous_runner_prioritizes_active_product_bulk_ui_over_pm_gate() -> None:
    board = """
## Active Tasks

| ID | Milestone | Task | Owner | Status | Acceptance Criteria | Next Handoff |
| --- | --- | --- | --- | --- | --- | --- |
| PM-02 | M1 | Autonomous phase control | Project Management | in_progress | Hold RC until gates close. | Developers, QA, Architecture |
| DEV-I-05 | M1 | Product Bulk UI lifecycle gates | Developers | in_progress | UI copy and controls mirror backend lifecycle rules. | Design, QA |
| DEV-I-06 | M1 | Product Bulk mapped smoke | QA / Developers | in_progress | Smoke rows are passed, failed, or blocked. | Project Management, Architecture |
"""
    decision = choose_next_decision("cosuite", parse_active_tasks(board))

    assert decision.task_id == "DEV-I-05"
    assert decision.department == "Developers"


def test_autonomous_runner_moves_to_product_bulk_smoke_after_ui_gate() -> None:
    board = """
## Active Tasks

| ID | Milestone | Task | Owner | Status | Acceptance Criteria | Next Handoff |
| --- | --- | --- | --- | --- | --- | --- |
| PM-02 | M1 | Autonomous phase control | Project Management | in_progress | Hold RC until gates close. | Developers, QA, Architecture |
| DEV-I-05 | M1 | Product Bulk UI lifecycle gates | Developers | done | UI copy and controls mirror backend lifecycle rules. | Design, QA |
| DEV-I-06 | M1 | Product Bulk mapped smoke | QA / Developers | in_progress | Smoke rows are passed, failed, or blocked. | Project Management, Architecture |
"""
    decision = choose_next_decision("cosuite", parse_active_tasks(board))

    assert decision.task_id == "DEV-I-06"
    assert decision.department == "QA"


def test_autonomous_runner_prioritizes_product_bulk_arabic_header_task_over_pm_gate() -> None:
    board = """
## Active Tasks

| ID | Milestone | Task | Owner | Status | Acceptance Criteria | Next Handoff |
| --- | --- | --- | --- | --- | --- | --- |
| PM-02 | M1 | Autonomous phase control | Project Management | in_progress | Hold RC until gates close. | Developers, QA, Architecture |
| DEV-I-07 | M1 | Product Bulk Arabic header support or guidance | Developers | in_progress | Arabic headers map or are documented. | QA, Architecture |
| ARCH-02B | M1 | Product Bulk gate reconciliation after mapped smoke | Architecture | in_progress | Reconcile Product Bulk drift. | Project Management |
"""
    decision = choose_next_decision("cosuite", parse_active_tasks(board))

    assert decision.task_id == "DEV-I-07"
    assert decision.department == "Developers"


def test_codex_approval_flag_is_top_level(monkeypatch, tmp_path) -> None:
    command_seen: list[str] = []

    def fake_run(command, **kwargs):  # type: ignore[no-untyped-def]
        command_seen.extend(command)
        output_path = Path(command[command.index("--output-last-message") + 1])
        output_path.write_text("ok", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(autonomous_runner.Path, "exists", lambda self: True)
    monkeypatch.setattr(autonomous_runner.subprocess, "run", fake_run)

    output = autonomous_runner.run_codex("do work", tmp_path / "codex-output.md", timeout_minutes=1)

    assert output == "ok"
    assert command_seen.index("--ask-for-approval") < command_seen.index("exec")


def test_codex_timeout_returns_report_text(monkeypatch, tmp_path) -> None:
    def fake_run(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise subprocess.TimeoutExpired(cmd=["codex"], timeout=60)

    monkeypatch.setattr(autonomous_runner.Path, "exists", lambda self: True)
    monkeypatch.setattr(autonomous_runner.subprocess, "run", fake_run)

    output = autonomous_runner.run_codex("do work", tmp_path / "codex-output.md", timeout_minutes=1)

    assert "Codex worker timed out" in output
    assert "Timeout minutes: 1" in output


def test_telegram_messages_include_owner_and_department_topics(tmp_path) -> None:
    decision = CycleDecision(
        project="cosuite",
        department="QA",
        task_id="QA-03",
        task="Smoke test media states",
        reason="QA-03 needs review.",
        codex_prompt="do qa",
    )

    messages = telegram_messages_for_cycle(
        "cosuite",
        decision,
        tmp_path / "prompt.md",
        tmp_path / "report.md",
        codex_output=(
            "## Owner Arabic Summary\n"
            "- ما تم في هذه الدورة: تم فحص smoke.\n"
            "- ماذا يجب أن تعمل الدورة القادمة: إعادة الاختبار."
        ),
        next_decision=CycleDecision(
            project="cosuite",
            department="Developers",
            task_id="DEV-I-07",
            task="Arabic headers",
            reason="DEV-I-07 is active.",
            codex_prompt="do dev",
        ),
    )

    assert [topic for topic, _message in messages] == ["owner-review", "qa"]
    assert "تقرير دورة الأوتوبايلوت" in messages[0][1]
    assert "ما تم في هذه الدورة: تم فحص smoke." in messages[0][1]
    assert "الدورة القادمة المتوقعة: Developers - DEV-I-07: Arabic headers" in messages[0][1]
    assert "QA cycle update" in messages[1][1]


def test_acquire_lock_clears_dead_pid(monkeypatch, tmp_path) -> None:
    lock_path = tmp_path / ".autonomous-runner.lock"
    lock_path.write_text("999999", encoding="utf-8")
    monkeypatch.setattr(autonomous_runner, "process_is_running", lambda pid: False)

    assert acquire_lock(lock_path) is True
    release_lock(lock_path)
