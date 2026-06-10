#!/usr/bin/env python3
"""Autonomous software-company runner.

This runner is intentionally conservative by default:

- It records an execution cycle.
- It chooses the next department/work slice from the project board.
- It writes a Codex prompt for the next worker cycle.
- It can send a Telegram update.
- It only invokes Codex CLI when explicitly enabled by flag or env.

Use this as the bridge between "documented agents" and a real always-on
operating loop.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import time

try:
    from telegram_bridge import send_message
except ModuleNotFoundError:
    from scripts.software_company.telegram_bridge import send_message


REPO_ROOT = Path(__file__).resolve().parents[2]
PROJECTS_DIR = REPO_ROOT / "docs" / "software-company" / "projects"
OWNER_REVIEW_DIR = REPO_ROOT / "docs" / "software-company" / "owner review"
CODEX_BIN = "/Applications/Codex.app/Contents/Resources/codex"

DEPARTMENT_TOPIC = {
    "Project Management": "project-management",
    "Product Manager": "product",
    "Architecture": "architecture",
    "Design": "design",
    "Developers Manager": "developers-manager",
    "Developers": "developers",
    "QA": "qa",
    "DevOps / Infra": "devops",
}


@dataclass(frozen=True)
class BoardTask:
    task_id: str
    milestone: str
    task: str
    owner: str
    status: str
    acceptance: str
    handoff: str


@dataclass(frozen=True)
class CycleDecision:
    project: str
    department: str
    task_id: str
    task: str
    reason: str
    codex_prompt: str
    owner_input_required: bool = False


def split_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def clean_cell(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("`", "")).strip()


def parse_active_tasks(board_text: str) -> list[BoardTask]:
    in_active = False
    tasks: list[BoardTask] = []
    for raw_line in board_text.splitlines():
        line = raw_line.strip()
        if line.startswith("## "):
            in_active = line == "## Active Tasks"
            continue
        if not in_active or not line.startswith("|"):
            continue
        cells = split_row(line)
        if len(cells) < 7 or cells[0] in {"ID", "---"} or set(cells[0]) == {"-"}:
            continue
        tasks.append(
            BoardTask(
                task_id=clean_cell(cells[0]),
                milestone=clean_cell(cells[1]),
                task=clean_cell(cells[2]),
                owner=clean_cell(cells[3]),
                status=clean_cell(cells[4]),
                acceptance=clean_cell(cells[5]),
                handoff=clean_cell(cells[6]),
            )
        )
    return tasks


def project_paths(project: str) -> tuple[Path, Path, Path]:
    project_dir = PROJECTS_DIR / project
    return project_dir, project_dir / "task-board.md", project_dir / "next-actions.md"


def load_tasks(project: str) -> list[BoardTask]:
    _, board_path, _ = project_paths(project)
    if not board_path.exists():
        raise FileNotFoundError(f"Task board not found: {board_path}")
    return parse_active_tasks(board_path.read_text(encoding="utf-8"))


def choose_next_decision(project: str, tasks: list[BoardTask]) -> CycleDecision:
    by_id = {task.task_id: task for task in tasks}

    # Priority is intentionally product-specific only at the project-task level.
    # The runner itself stays reusable: it reads the board and applies a small
    # decision policy instead of hard-coding source files.
    priority_ids = [
        "QA-03",
        "DEVMGR-03",
        "ARCH-02",
        "QA-02",
        "DEV-A-01",
        "DEV-B-01",
        "DEV-C-01",
        "DEV-E-01",
    ]
    for task_id in priority_ids:
        task = by_id.get(task_id)
        if task and task.status in {"needs_review", "in_progress", "not_started"}:
            return decision_for_task(project, task)

    for status in ["needs_review", "in_progress", "not_started"]:
        for task in tasks:
            if task.status == status:
                return decision_for_task(project, task)

    for task in tasks:
        if task.status == "ready_for_handoff":
            return decision_for_task(project, task)

    return CycleDecision(
        project=project,
        department="Project Management",
        task_id="NO-ACTIVE-TASK",
        task="No active task found",
        reason="No active task matched the autonomous runner policy.",
        codex_prompt=(
            f"Inspect {project} task board and status logs. Decide whether the project is complete, "
            "blocked, or needs a new task board entry. Write an owner review if needed."
        ),
        owner_input_required=True,
    )


def decision_for_task(project: str, task: BoardTask) -> CycleDecision:
    department = route_department(task)
    prompt = build_codex_prompt(project, task, department)
    return CycleDecision(
        project=project,
        department=department,
        task_id=task.task_id,
        task=task.task,
        reason=f"{task.task_id} is {task.status} and routes to {task.handoff}.",
        codex_prompt=prompt,
    )


def route_department(task: BoardTask) -> str:
    owner = task.owner.lower()
    if "qa" in owner or task.task_id.startswith("QA"):
        return "QA"
    if "architecture" in owner or task.task_id.startswith("ARCH"):
        return "Architecture"
    if "devops" in owner:
        return "DevOps / Infra"
    if "developers manager" in owner or task.task_id.startswith("DEVMGR"):
        return "Developers Manager"
    if "developers" in owner or task.task_id.startswith("DEV"):
        return "Developers"
    if "design" in owner:
        return "Design"
    if "product" in owner:
        return "Product Manager"
    return "Project Management"


def telegram_topic_for_department(department: str) -> str:
    return DEPARTMENT_TOPIC.get(department, "project-management")


def build_codex_prompt(project: str, task: BoardTask, department: str) -> str:
    return f"""You are the {department} department agent for the reusable software-company workflow.

Repository: {REPO_ROOT}
Project: {project}
Task ID: {task.task_id}
Task: {task.task}
Status: {task.status}
Acceptance criteria: {task.acceptance}
Next handoff: {task.handoff}

Operating rules:
- Continue autonomously. Do not ask the owner for routine execution approval.
- Ask the owner only for external access, secrets, business decisions, or accepted-risk decisions.
- Do not touch unrelated dirty files.
- Do not push unless AUTONOMOUS_GIT_PUSH is explicitly enabled by the human-runner environment.
- Keep changes narrow and consistent with existing project patterns.
- Run focused verification for touched surfaces.
- Update docs/software-company/projects/{project}/status-log.md.
- Create an owner-review markdown file under docs/software-company/owner review/ for meaningful checkpoints.

Current mission:
Read docs/software-company/projects/{project}/task-board.md and next-actions.md, then handle {task.task_id}.
If this is a review task, produce findings and exact next developer tasks.
If this is an implementation task, implement the smallest safe slice, verify it, and document the result.
"""


def process_is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def clear_stale_lock(lock_path: Path) -> None:
    if not lock_path.exists():
        return
    try:
        pid_text = lock_path.read_text(encoding="utf-8").strip()
        pid = int(pid_text)
    except (OSError, ValueError):
        return
    if not process_is_running(pid):
        release_lock(lock_path)


def acquire_lock(lock_path: Path) -> bool:
    clear_stale_lock(lock_path)
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(str(os.getpid()))
        return True
    except FileExistsError:
        return False


def release_lock(lock_path: Path) -> None:
    try:
        lock_path.unlink()
    except FileNotFoundError:
        pass


def write_cycle_files(project: str, decision: CycleDecision, codex_output: str | None = None) -> tuple[Path, Path]:
    project_dir, _, _ = project_paths(project)
    run_dir = project_dir / "autonomous-runs"
    run_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

    prompt_path = run_dir / f"{stamp}_{decision.task_id}_codex-prompt.md"
    prompt_path.write_text(decision.codex_prompt, encoding="utf-8")

    report_path = OWNER_REVIEW_DIR / f"{stamp}_{project}-autopilot-cycle-owner-review.md"
    report = [
        f"# {project} Autopilot Cycle Owner Review",
        "",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## Decision",
        "",
        f"- Department: {decision.department}",
        f"- Task: `{decision.task_id}` {decision.task}",
        f"- Reason: {decision.reason}",
        f"- Owner input required: {decision.owner_input_required}",
        "",
        "## Prompt File",
        "",
        f"`{prompt_path}`",
        "",
    ]
    if codex_output:
        report.extend(["## Codex Output", "", codex_output[:4000], ""])
    else:
        report.extend(
            [
                "## Execution",
                "",
                "Codex execution was not enabled for this cycle. The prompt is ready for the worker runner.",
                "",
            ]
        )
    report_path.write_text("\n".join(report), encoding="utf-8")
    return prompt_path, report_path


def run_codex(prompt: str, output_path: Path, timeout_minutes: int) -> str:
    if not Path(CODEX_BIN).exists():
        raise FileNotFoundError(f"Codex CLI not found: {CODEX_BIN}")

    command = [
        CODEX_BIN,
        "--ask-for-approval",
        "never",
        "exec",
        "--cd",
        str(REPO_ROOT),
        "--sandbox",
        "workspace-write",
        "--output-last-message",
        str(output_path),
        "-",
    ]
    try:
        result = subprocess.run(
            command,
            input=prompt,
            text=True,
            cwd=REPO_ROOT,
            capture_output=True,
            timeout=timeout_minutes * 60,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        partial_output = ""
        try:
            if output_path.exists():
                partial_output = output_path.read_text(encoding="utf-8")[-3000:]
        except OSError:
            partial_output = ""
        return (
            "Codex worker timed out.\n\n"
            f"Command: {shlex.join(command)}\n\n"
            f"Timeout minutes: {timeout_minutes}\n\n"
            f"Partial output:\n{partial_output or str(exc)}"
        )
    if result.returncode != 0:
        return (
            "Codex worker failed.\n\n"
            f"Command: {shlex.join(command)}\n\n"
            f"STDOUT:\n{result.stdout[-2000:]}\n\n"
            f"STDERR:\n{result.stderr[-2000:]}"
        )
    if output_path.exists():
        return output_path.read_text(encoding="utf-8")
    return result.stdout[-4000:]


def telegram_messages_for_cycle(
    project: str,
    decision: CycleDecision,
    prompt_path: Path,
    report_path: Path,
) -> list[tuple[str, str]]:
    owner_message = "\n".join(
        [
            "Autopilot cycle complete",
            f"Project: {project}",
            f"Department: {decision.department}",
            f"Task: {decision.task_id} - {decision.task}",
            f"Prompt: {prompt_path}",
            f"Report: {report_path}",
        ]
    )
    department_message = "\n".join(
        [
            f"{decision.department} cycle update",
            f"Project: {project}",
            f"Task: {decision.task_id}",
            decision.task,
            "",
            f"Why this task: {decision.reason}",
            f"Owner input required: {decision.owner_input_required}",
            f"Report: {report_path}",
        ]
    )
    department_topic = telegram_topic_for_department(decision.department)
    messages = [("owner-review", owner_message)]
    if department_topic != "owner-review":
        messages.append((department_topic, department_message))
    return messages


def safe_send_message(text: str, topic: str) -> None:
    try:
        send_message(text, topic=topic)
    except Exception as exc:  # Telegram should not kill the work loop.
        print(f"Telegram send failed for topic {topic}: {exc}", file=sys.stderr)


def send_incident(project: str, exc: BaseException) -> None:
    safe_send_message(
        "\n".join(
            [
                "Autopilot incident",
                f"Project: {project}",
                f"Error: {type(exc).__name__}: {exc}",
            ]
        ),
        topic="incidents",
    )


def run_once(project: str, execute_codex: bool, send_telegram: bool, timeout_minutes: int) -> Path:
    project_dir, _, _ = project_paths(project)
    lock_path = project_dir / ".autonomous-runner.lock"
    if not acquire_lock(lock_path):
        raise RuntimeError(f"Autonomous runner is already active for {project}: {lock_path}")

    try:
        tasks = load_tasks(project)
        decision = choose_next_decision(project, tasks)
        codex_output = None
        if execute_codex or os.environ.get("AUTONOMOUS_CODEX_EXEC") == "1":
            run_dir = project_dir / "autonomous-runs"
            run_dir.mkdir(parents=True, exist_ok=True)
            worker_output = run_dir / f"{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}_{decision.task_id}_codex-output.md"
            codex_output = run_codex(decision.codex_prompt, worker_output, timeout_minutes)
        prompt_path, report_path = write_cycle_files(project, decision, codex_output=codex_output)

        if send_telegram:
            for topic, message in telegram_messages_for_cycle(project, decision, prompt_path, report_path):
                safe_send_message(message, topic)
        return report_path
    finally:
        release_lock(lock_path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", nargs="?", default="cosuite")
    parser.add_argument("--loop", action="store_true", help="Run continuously until interrupted")
    parser.add_argument("--interval-minutes", type=int, default=60)
    parser.add_argument("--max-cycles", type=int, default=1)
    parser.add_argument("--execute-codex", action="store_true", help="Invoke Codex CLI for the chosen task")
    parser.add_argument("--telegram", action="store_true", help="Send cycle summary to Telegram")
    parser.add_argument("--timeout-minutes", type=int, default=45)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cycles = 0
    while True:
        try:
            report = run_once(
                project=args.project,
                execute_codex=args.execute_codex,
                send_telegram=args.telegram,
                timeout_minutes=args.timeout_minutes,
            )
            print(report)
        except Exception as exc:
            print(f"Autopilot cycle failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            if args.telegram:
                send_incident(args.project, exc)
        cycles += 1
        if not args.loop or cycles >= args.max_cycles:
            break
        time.sleep(max(1, args.interval_minutes) * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
