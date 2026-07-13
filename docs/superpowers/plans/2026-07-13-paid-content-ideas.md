# Paid Content Ideas Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace detailed paid-ad generation with concise, selectable funnel-stage ideas matching the social-ideas experience.

**Architecture:** Keep the existing paid-content endpoints, stage grouping, and selection persistence. Narrow the provider JSON contract in `marketing_plan_generator.py`, add compatibility aliases in normalization, then simplify the paid idea card in the work-plan page.

**Tech Stack:** FastAPI/Python, pytest, Next.js/React/TypeScript, Tailwind CSS.

## Global Constraints

- Preserve all five paid funnel stages.
- Generate two choices per stage by combining one OpenAI and one Claude result.
- Show title, concise description, recommended format, channel, and provider only.
- Preserve existing saved plans and selection persistence.

---

### Task 1: Concise Provider Contract

**Files:**
- Modify: `tests/test_marketing_plan_generator.py`
- Modify: `api/services/marketing_plan_generator.py`

- [ ] Add failing tests that require `description` and `recommended_format` and reject detailed prompt fields.
- [ ] Run the focused tests and confirm they fail on the current detailed contract.
- [ ] Update the prompt, fallback candidates, normalization, and version.
- [ ] Run the focused generator tests and confirm they pass.

### Task 2: Compact Paid Idea Cards

**Files:**
- Modify: `web/src/lib/api.ts`
- Modify: `web/src/app/(dashboard)/suite/[id]/work-plans/page.tsx`

- [ ] Extend the TypeScript type with concise fields and compatibility fields.
- [ ] Replace detailed paid-ad sections with the compact title/description/format presentation.
- [ ] Preserve the one-per-stage selection limit and save behavior.
- [ ] Run lint and production build.

### Task 3: End-User QA

**Files:**
- No production files.

- [ ] Exercise the paid-plan API or browser generation workflow.
- [ ] Select and save one idea per stage, reload, and verify persistence.
- [ ] Verify no neighboring social-plan data is erased.
- [ ] Check 390px mobile layout and browser/server errors.
