# Software Company Operating System

Last updated: 2026-06-07

This folder defines a reusable software-company operating system for co-Suite and future projects. It turns product development into departments, agents, workflows, handoffs, registers, and review loops.

The goal is not to create static documentation. The goal is to create a repeatable company process where each agent owns a role, produces artifacts, reviews other work, and keeps evidence of what was done and what remains open.

## Departments

- `product-manager`: owns product intent, user value, PRDs, roadmap, acceptance criteria.
- `architecture`: owns system design, technical boundaries, scalability, data contracts, and architecture review loops.
- `design`: owns UX flows, design system, UI quality, responsive behavior, and product clarity.
- `devops-infra`: owns environments, deploys, secrets, queues, storage, monitoring, scaling, and incident readiness.
- `project-management`: owns status, owners, timelines, risks, blockers, and cross-agent coordination.
- `developers-manager`: owns engineering task breakdown, code ownership, implementation sequencing, and developer review readiness.
- `developers`: own code implementation, tests, local verification, and handoff notes.
- `qa`: owns test plans, regression checks, defect registers, re-check cycles, and release gates.

## Core Principle

Every meaningful feature or release goes through a loop:

```txt
Product intent
  -> brand and design intake when UI/client-facing screens are involved
  -> UX style intake when comfort, animation, or long-session work matters
  -> architecture review
  -> design review
  -> planning and task breakdown
  -> implementation
  -> QA verification
  -> architecture re-check
  -> release readiness
  -> post-release learning
```

The loop is not optional. The architect must return after implementation to compare planned architecture with actual work. QA must record every finding and re-check it later until it is closed, deferred, or accepted as risk.

## Files

- `operating-model.md`: how departments cooperate.
- `agent-template.md`: standard template for every role agent.
- `department-managers.md`: named managers for every department and owner-review attribution rules.
- `templates/project-task-board.md`: reusable project task board for new projects.
- `templates/agent-cycle-runbook.md`: lightweight runbook for one agent delivery cycle.
- `templates/manager-responsibilities.md`: portable manager ownership template.
- `templates/qa-architecture-gates.md`: reusable QA and architecture phase gates.
- `departments/*/agent.md`: role-specific agent instructions.
- `workflows/*`: lifecycle workflows.
- `workflows/brand-and-design-intake.md`: reusable brand/design intake before UI work on any project.
- `workflows/ux-style-intake.md`: reusable UX personality, animation, comfort, and long-session workflow.
- `quotes/*`: client proposal templates and dated client quotes.
- `handoffs/README.md`: handoff protocol between agents.
- `registers/*`: durable logs for risks, architecture drift, QA findings, estimates, and decisions.

## Reuse For Future Projects

This system should stay project-agnostic where possible. A future project can copy this folder and replace only:

- project name.
- product goals.
- architecture constraints.
- deployment platform.
- quality gates.
- department-specific source paths.

The operating model should remain stable.

For future visual products, Product Management must ask for brand assets when they are not provided. Design should create a visual direction before coding starts, including multilingual and RTL/LTR assumptions where relevant.

For future UX-heavy products, Product Management must ask how the experience should feel. If the owner/client is unsure, Product and Design should propose clear UX directions and document the chosen one before coding.

## Starting A New Project

1. Create `docs/software-company/projects/<project>/`.
2. Copy `templates/project-task-board.md` to `docs/software-company/projects/<project>/task-board.md`.
3. Add `README.md`, `next-actions.md`, `status-log.md`, and `handoff-log.md` as the project control room grows.
4. Use `templates/agent-cycle-runbook.md` for each delivery loop.
5. Use `templates/qa-architecture-gates.md` before phase movement or owner review.

To generate a markdown owner-review from a project board:

```sh
python3 scripts/software_company/generate_owner_review.py <project>
```

Use `--dry-run` to print the report without creating a file.
