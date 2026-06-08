#!/usr/bin/env python3
"""Generate a lightweight owner-review markdown report from a project task board."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import re
import sys

from telegram_bridge import send_message


REPO_ROOT = Path(__file__).resolve().parents[2]
PROJECTS_DIR = REPO_ROOT / "docs" / "software-company" / "projects"
OWNER_REVIEW_DIR = REPO_ROOT / "docs" / "software-company" / "owner review"


@dataclass(frozen=True)
class Task:
    task_id: str
    milestone: str
    task: str
    owner: str
    status: str
    acceptance: str
    handoff: str


def split_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def clean_cell(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("`", "")).strip()


def parse_active_tasks(board_text: str) -> list[Task]:
    in_active = False
    tasks: list[Task] = []

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
            Task(
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


def bullet_tasks(tasks: list[Task], empty: str) -> list[str]:
    if not tasks:
        return [f"- {empty}"]
    return [f"- `{task.task_id}` {task.task} ({task.owner}) -> {task.handoff}" for task in tasks]


def build_report(project: str, board_path: Path, tasks: list[Task], generated_at: datetime) -> str:
    status_counts = Counter(task.status for task in tasks)
    by_owner: dict[str, list[Task]] = defaultdict(list)
    for task in tasks:
        by_owner[task.owner].append(task)

    blocked = [task for task in tasks if task.status == "blocked"]
    needs_review = [task for task in tasks if task.status == "needs_review"]
    active = [task for task in tasks if task.status in {"in_progress", "ready_for_handoff"}]
    not_started = [task for task in tasks if task.status == "not_started"]

    status_lines = [f"- `{status}`: {count}" for status, count in sorted(status_counts.items())]
    owner_lines = [
        f"- {owner}: {len(owner_tasks)} task(s); "
        f"{', '.join(sorted(set(task.status for task in owner_tasks)))}"
        for owner, owner_tasks in sorted(by_owner.items())
    ]

    owner_summary = owner_lines or ["- No active tasks found."]

    lines = [
        f"# {project} Owner Review Cycle Report",
        "",
        f"Generated: {generated_at.strftime('%Y-%m-%d %H:%M:%S')}",
        f"Source board: `{board_path.relative_to(REPO_ROOT)}`",
        "",
        "## Summary",
        "",
        f"- Total active tasks: {len(tasks)}",
        *status_lines,
        "",
        "## Department Load",
        "",
        *owner_summary,
        "",
        "## Needs Review",
        "",
        *bullet_tasks(needs_review, "No tasks currently need review."),
        "",
        "## Active Handoffs",
        "",
        *bullet_tasks(active, "No active handoffs currently open."),
        "",
        "## Blockers",
        "",
        *bullet_tasks(blocked, "No blocked active tasks found."),
        "",
        "## Next Queue",
        "",
        *bullet_tasks(not_started[:8], "No not-started tasks in the active board."),
        "",
        "## Manager Decision Prompt",
        "",
        "- Project Management: continue, fix, block, or request owner review?",
        "- QA: are any open findings phase-blocking?",
        "- Architecture: is any drift blocking the next phase?",
        "- Developers Manager: is the next slice small enough to verify quickly?",
        "",
    ]
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", help="Project folder name under docs/software-company/projects")
    parser.add_argument("--board", type=Path, help="Override task board path")
    parser.add_argument("--output-dir", type=Path, default=OWNER_REVIEW_DIR)
    parser.add_argument("--dry-run", action="store_true", help="Print report instead of writing a file")
    parser.add_argument("--telegram", action="store_true", help="Send the generated report to Telegram Owner Review")
    parser.add_argument("--telegram-dry-run", action="store_true", help="Print Telegram payload without sending")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    board_path = args.board or PROJECTS_DIR / args.project / "task-board.md"
    if not board_path.exists():
        print(f"Task board not found: {board_path}", file=sys.stderr)
        return 1

    generated_at = datetime.now()
    tasks = parse_active_tasks(board_path.read_text(encoding="utf-8"))
    report = build_report(args.project, board_path, tasks, generated_at)

    if args.dry_run:
        print(report)
        return 0

    args.output_dir.mkdir(parents=True, exist_ok=True)
    stamp = generated_at.strftime("%Y-%m-%d_%H-%M-%S")
    output_path = args.output_dir / f"{stamp}_{args.project}-cycle-owner-review.md"
    output_path.write_text(report, encoding="utf-8")
    print(output_path)

    if args.telegram or args.telegram_dry_run:
        message = f"Owner Review generated\n\n{report}\n\nLocal file: {output_path}"
        send_message(message, topic="owner-review", dry_run=args.telegram_dry_run)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
