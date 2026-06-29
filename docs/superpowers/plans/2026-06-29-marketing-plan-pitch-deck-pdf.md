# Marketing Plan Pitch Deck PDF Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the generated marketing plan PDF report with a persuasive 16:9 pitch deck that shows the full marketing picture.

**Architecture:** Keep the existing `/marketing-plan/pdf` API route and `build_marketing_plan_pdf(suite)` interface. Refactor `api/services/marketing_plan_pdf.py` into slide-oriented helpers inside the same module first, so the behavior is easy to review without changing API consumers.

**Tech Stack:** FastAPI route, SQLAlchemy suite model, ReportLab PDF generation, Noto Arabic/Hebrew fonts, Poppler `pdftoppm` for visual QA, pytest.

## Global Constraints

- Output is PDF landscape 16:9.
- Target length is 16-20 pages when enough data exists.
- Use saved suite data only; do not trigger new generation during PDF download.
- Arabic, Hebrew, and English content must render without broken glyphs.
- Long text must be clamped or split across slides, never clipped.
- Maintain existing route and frontend download behavior.
- QA must render representative PDF pages to PNG and inspect cover, services, competitors, personas, and execution/closing.

---

### Task 1: Slide Foundation And Theme

**Files:**
- Modify: `api/services/marketing_plan_pdf.py`
- Test: `tests/test_marketing_plan_pdf.py`

**Interfaces:**
- Consumes: `build_marketing_plan_pdf(suite: Suite) -> tuple[bytes, str]`
- Produces: internal slide constants and helpers used by later slide tasks.

- [ ] **Step 1: Add or update tests for deck shape**

Add assertions to `test_build_marketing_plan_pdf_returns_valid_pdf_bytes` that the generated PDF has a landscape 16:9-ish media box and more than 8 pages for rich data. Use `pypdf.PdfReader`.

- [ ] **Step 2: Run the focused test to verify current behavior is insufficient**

Run: `python -m pytest tests/test_marketing_plan_pdf.py::test_build_marketing_plan_pdf_returns_valid_pdf_bytes -q`
Expected before implementation: fail on page size or page count.

- [ ] **Step 3: Implement deck constants and page callback**

In `api/services/marketing_plan_pdf.py`, introduce:

```python
SLIDE_SIZE = (900, 507)
SLIDE_MARGIN = 42
DARK_BG = colors.HexColor("#0b071f")
PANEL_BG = colors.HexColor("#1f1a35")
CARD_BG = colors.HexColor("#2b2250")
TEXT_LIGHT = colors.HexColor("#f8fafc")
TEXT_MUTED = colors.HexColor("#cbd5e1")
ACCENT_HEX = "#ff79a8"
```

Change `SimpleDocTemplate(... pagesize=SLIDE_SIZE, margins=...)` and add an `onPage` callback that paints the dark background, page number, and OneShare footer.

- [ ] **Step 4: Run focused test**

Run: `python -m pytest tests/test_marketing_plan_pdf.py::test_build_marketing_plan_pdf_returns_valid_pdf_bytes -q`
Expected: pass page size expectations.

### Task 2: Pitch Deck Slide Helpers

**Files:**
- Modify: `api/services/marketing_plan_pdf.py`
- Test: `tests/test_marketing_plan_pdf.py`

**Interfaces:**
- Consumes: theme constants from Task 1.
- Produces: `_deck_title`, `_section_label`, `_pitch_card`, `_pitch_grid`, `_split_pages`, `_compact_url`, and `_section_break` helpers.

- [ ] **Step 1: Add mixed RTL/LTR regression test**

Extend `test_marketing_plan_pdf_ignores_bidi_isolate_controls` to assert PDF generation stays valid and larger than a small smoke threshold after the new deck layout.

- [ ] **Step 2: Implement helper functions**

Add helpers for:

```python
def _clamp_text(value: Any, limit: int = 160) -> str: ...
def _compact_url(value: Any, limit: int = 38) -> str: ...
def _pitch_card(title: str, lines: list[Any], ..., accent: str = ACCENT_HEX, width: float = 240) -> Table: ...
def _pitch_grid(story: list[Any], cards: list[Table], columns: int, col_width: float) -> None: ...
def _section_break(story: list[Any], title: str, subtitle: str, ...) -> None: ...
```

Use `KeepTogether` only when it will not create oversize layout errors; split content by page instead of letting cards overflow.

- [ ] **Step 3: Run all PDF unit tests**

Run: `python -m pytest tests/test_marketing_plan_pdf.py -q`
Expected: pass.

### Task 3: Content Slides

**Files:**
- Modify: `api/services/marketing_plan_pdf.py`
- Test: `tests/test_marketing_plan_pdf.py`

**Interfaces:**
- Consumes: helper functions from Task 2.
- Produces: new implementation of `build_marketing_plan_pdf` with slide sequence.

- [ ] **Step 1: Build slide sequence**

Rework `build_marketing_plan_pdf` story construction into this order:

1. cover slide
2. business snapshot
3. services/products pages
4. market reading
5. keyword intent pages
6. competitors by source
7. demand/supply dashboard
8. personas pages
9. strategic direction
10. 30/60/90 execution
11. closing page

- [ ] **Step 2: Add data extraction helpers**

Add helpers that derive content from existing saved data only:

```python
def _business_snapshot(suite: Suite, labels: dict[str, str]) -> list[tuple[str, str]]: ...
def _keyword_groups(intelligence: dict[str, Any], labels: dict[str, str]) -> dict[str, list[str]]: ...
def _competitors_by_source(intelligence: dict[str, Any]) -> dict[str, list[dict[str, Any]]]: ...
def _strategic_direction(suite: Suite, intelligence: dict[str, Any], labels: dict[str, str]) -> list[tuple[str, list[str]]]: ...
def _execution_steps(action_plan: dict[str, Any], labels: dict[str, str]) -> list[tuple[str, list[str]]]: ...
```

- [ ] **Step 3: Run PDF unit tests**

Run: `python -m pytest tests/test_marketing_plan_pdf.py -q`
Expected: pass.

### Task 4: Route Regression And Visual QA

**Files:**
- Modify: `tests/test_marketing_plan_routes.py` only if route expectations need updating.
- Generated QA artifacts: `tmp/pdf-qa/marketing-plan-deck-*.png`

**Interfaces:**
- Consumes: unchanged API route.
- Produces: verification that download behavior is intact and visual PDF is polished.

- [ ] **Step 1: Run route tests**

Run: `python -m pytest tests/test_marketing_plan_routes.py::test_download_marketing_plan_pdf_returns_attachment tests/test_marketing_plan_pdf.py -q`
Expected: pass.

- [ ] **Step 2: Generate a sample PDF locally**

Use a short Python script importing `build_marketing_plan_pdf` and a rich Arabic `Suite` fixture to write `tmp/pdf-qa/sample-marketing-plan.pdf`.

- [ ] **Step 3: Render representative pages**

Run: `pdftoppm -png -f 1 -l 8 -r 120 tmp/pdf-qa/sample-marketing-plan.pdf tmp/pdf-qa/marketing-plan-deck`
Expected: PNG files appear for inspection.

- [ ] **Step 4: Inspect rendered images**

Open representative PNGs and verify no broken glyphs, clipped text, overlapping cards, or report-like dense pages.

- [ ] **Step 5: Build frontend and smoke download flow**

Run: `cd web && npm run build`.
Use Playwright mobile viewport to confirm the PDF download button still receives a PDF and does not produce `Load failed`.

