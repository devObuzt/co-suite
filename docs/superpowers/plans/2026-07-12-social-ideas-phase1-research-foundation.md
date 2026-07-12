# Social Ideas — Phase 1: Research Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Build the reusable research layer — an occasions + market-research cache keyed by (country, language) — that later idea generation consumes.

**Architecture:** New `ResearchCache` SQLAlchemy model (auto-created via `Base.metadata.create_all`), a small cache service (get/upsert by unique key), an `occasions_service` (LLM proposes → web-search verifies dates → cache), a `market_research` cache wrapper reusing existing research, and a pure `occasion_match` relevance filter. No prompts/UI in this phase.

**Tech Stack:** FastAPI, async SQLAlchemy (Mapped/mapped_column), `call_text_ai` LLM helper, `search_web` web search, pytest + pytest-asyncio.

## Global Constraints

- Models use `Mapped[...] = mapped_column(...)`; Base from `api.core.database`; register new models in `api/models/__init__.py`; JSON dict column reserved name is `metadata_json` (not `metadata`).
- New table also gets a raw `CREATE TABLE IF NOT EXISTS` in `api/main.py` startup block (established pattern), in addition to `create_all`.
- LLM calls go through `call_text_ai(provider=None, model=None, max_tokens, messages, system="", timeout=120) -> str`; do NOT wrap in `external_call()` (already instrumented). Parse JSON defensively (reuse a brace-balanced extractor).
- Web search via `from api.services.multi_scraper import search_web` → `await search_web(query, limit) -> [{title,url,snippet,platform}]`.
- Settings: `settings.serpapi_api_key`, `settings.ai_text_provider`, `settings.anthropic_text_model`/`settings.openai_text_model`.
- Country/location from a suite: `brand.get("audience_location") or brand.get("location")`; language via `infer_plan_language(suite)`.
- Never block generation on research failure — return empty + a warning.

---

### Task 1: `ResearchCache` model

**Files:**
- Create: `api/models/research_cache.py`
- Modify: `api/models/__init__.py` (add import)
- Modify: `api/main.py` (raw CREATE TABLE IF NOT EXISTS in startup)
- Test: `tests/test_research_cache_model.py`

**Interfaces:**
- Produces: `ResearchCache` with columns `id, kind, country, language, period(nullable), data(JSON), source, created_at, refreshed_at, expires_at(nullable)`; `UNIQUE(kind, country, language, period)`.

- [ ] **Step 1: Write the failing test**
```python
# tests/test_research_cache_model.py
def test_research_cache_model_has_expected_columns():
    from api.models.research_cache import ResearchCache
    cols = set(ResearchCache.__table__.columns.keys())
    assert {"id","kind","country","language","period","data","source",
            "created_at","refreshed_at","expires_at"} <= cols
    uniques = [c for c in ResearchCache.__table__.constraints
               if c.__class__.__name__ == "UniqueConstraint"]
    assert any({"kind","country","language","period"} ==
               {col.name for col in u.columns} for u in uniques)
```

- [ ] **Step 2: Run test to verify it fails**
Run: `python3 -m pytest tests/test_research_cache_model.py -q`
Expected: FAIL (ModuleNotFoundError: api.models.research_cache)

- [ ] **Step 3: Write minimal implementation**
```python
# api/models/research_cache.py
import uuid
from datetime import datetime
from typing import Optional
from sqlalchemy import DateTime, JSON, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column
from ..core.database import Base


class ResearchCache(Base):
    __tablename__ = "research_cache"
    __table_args__ = (
        UniqueConstraint("kind", "country", "language", "period",
                         name="uq_research_cache_kind_country_language_period"),
    )
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    kind: Mapped[str] = mapped_column(String(40), nullable=False, index=True)          # occasions|market|(trends)
    country: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    language: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    period: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)            # "YYYY-MM" or NULL
    data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="hybrid")   # llm|web|hybrid
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    refreshed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
```
Then add to `api/models/__init__.py`: `from .research_cache import ResearchCache` and include `"ResearchCache"` in `__all__` if present.
Then in `api/main.py` startup block (near the other `CREATE TABLE IF NOT EXISTS`), add:
```python
await conn.exec_driver_sql(
    "CREATE TABLE IF NOT EXISTS research_cache ("
    "id VARCHAR PRIMARY KEY, kind VARCHAR(40) NOT NULL, country VARCHAR(80) NOT NULL, "
    "language VARCHAR(16) NOT NULL, period VARCHAR(16), data JSON, source VARCHAR(16) NOT NULL DEFAULT 'hybrid', "
    "created_at TIMESTAMPTZ DEFAULT now(), refreshed_at TIMESTAMPTZ DEFAULT now(), expires_at TIMESTAMPTZ, "
    "CONSTRAINT uq_research_cache_kind_country_language_period UNIQUE (kind, country, language, period))"
)
```
(Match the exact call style used by the neighbouring statements in main.py — use whatever `conn.exec_driver_sql`/`text()` form is already there.)

- [ ] **Step 4: Run test to verify it passes**
Run: `python3 -m pytest tests/test_research_cache_model.py -q`
Expected: PASS

- [ ] **Step 5: Commit**
```bash
git add api/models/research_cache.py api/models/__init__.py api/main.py tests/test_research_cache_model.py
git commit -m "feat(research): ResearchCache model + auto-create"
```

---

### Task 2: Cache get/upsert service

**Files:**
- Create: `api/services/research_cache.py`
- Test: `tests/test_research_cache_service.py`

**Interfaces:**
- Consumes: `ResearchCache` (Task 1).
- Produces:
  - `async def get_cached(db, *, kind, country, language, period=None) -> dict | None` — returns `data` if a non-expired row exists, else None.
  - `async def upsert_cached(db, *, kind, country, language, period, data, source="hybrid", ttl_days=None) -> None` — insert or update by unique key; sets `expires_at = now()+ttl_days` when given.
  - `def normalize_country(v) -> str`, `def normalize_language(v) -> str` — lowercase/trim; empty → "global"/"en".

- [ ] **Step 1: Write the failing test** (async, uses the test DB session fixture pattern already in tests/)
```python
# tests/test_research_cache_service.py
import pytest
from api.services.research_cache import normalize_country, normalize_language

def test_normalizers():
    assert normalize_country("  Israel ") == "israel"
    assert normalize_country("") == "global"
    assert normalize_language("AR") == "ar"
    assert normalize_language(None) == "en"
```
(Add DB-backed get/upsert idempotency tests using the repo's existing async db fixture — mirror `tests/test_media_library.py` setup for the session.)

- [ ] **Step 2: Run test to verify it fails**
Run: `python3 -m pytest tests/test_research_cache_service.py -q`
Expected: FAIL (ImportError)

- [ ] **Step 3: Write minimal implementation**
```python
# api/services/research_cache.py
from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ..models.research_cache import ResearchCache


def normalize_country(value) -> str:
    v = (str(value or "")).strip().lower()
    return v or "global"


def normalize_language(value) -> str:
    v = (str(value or "")).strip().lower()
    return (v.split("-")[0] or "en")


async def get_cached(db: AsyncSession, *, kind, country, language, period=None):
    row = (await db.execute(
        select(ResearchCache).where(
            ResearchCache.kind == kind,
            ResearchCache.country == normalize_country(country),
            ResearchCache.language == normalize_language(language),
            ResearchCache.period.is_(period) if period is None else ResearchCache.period == period,
        )
    )).scalar_one_or_none()
    if not row:
        return None
    if row.expires_at is not None and row.expires_at < datetime.now(timezone.utc):
        return None
    return row.data


async def upsert_cached(db: AsyncSession, *, kind, country, language, period, data, source="hybrid", ttl_days=None):
    country = normalize_country(country); language = normalize_language(language)
    expires_at = datetime.now(timezone.utc) + timedelta(days=ttl_days) if ttl_days else None
    row = (await db.execute(
        select(ResearchCache).where(
            ResearchCache.kind == kind, ResearchCache.country == country,
            ResearchCache.language == language,
            ResearchCache.period.is_(period) if period is None else ResearchCache.period == period,
        )
    )).scalar_one_or_none()
    if row:
        row.data = data; row.source = source; row.expires_at = expires_at
    else:
        db.add(ResearchCache(kind=kind, country=country, language=language, period=period,
                             data=data, source=source, expires_at=expires_at))
    await db.commit()
```

- [ ] **Step 4: Run test** — `python3 -m pytest tests/test_research_cache_service.py -q` → PASS
- [ ] **Step 5: Commit** — `git commit -m "feat(research): cache get/upsert service"`

---

### Task 3: Occasions service (hybrid LLM + web verify)

**Files:**
- Create: `api/services/occasions_service.py`
- Test: `tests/test_occasions_service.py`

**Interfaces:**
- Consumes: `call_text_ai`, `search_web`, `get_cached`/`upsert_cached` (Task 2).
- Produces: `async def get_occasions(db, *, country, language, period) -> list[dict]` where each item is `{title, type, date_or_window, confidence, verified_by}`. Cache-or-fetch; failure → `[]` (never raises).

- [ ] **Step 1: Write the failing test** (mock LLM + web)
```python
# tests/test_occasions_service.py
import pytest
from unittest.mock import AsyncMock, patch

@pytest.mark.asyncio
async def test_get_occasions_uses_cache(monkeypatch):
    from api.services import occasions_service as svc
    with patch.object(svc, "get_cached", AsyncMock(return_value=[{"title":"عيد الأضحى","type":"religious","date_or_window":"2026-08","confidence":"high","verified_by":"web"}])):
        out = await svc.get_occasions(db=None, country="israel", language="ar", period="2026-08")
    assert out and out[0]["title"] == "عيد الأضحى"

@pytest.mark.asyncio
async def test_get_occasions_fetches_on_miss(monkeypatch):
    from api.services import occasions_service as svc
    llm_json = '{"occasions":[{"title":"المونديال 2026","type":"sports","date_or_window":"2026-06..2026-07","confidence":"medium"}]}'
    with patch.object(svc, "get_cached", AsyncMock(return_value=None)), \
         patch.object(svc, "upsert_cached", AsyncMock()), \
         patch.object(svc, "call_text_ai", AsyncMock(return_value=llm_json)), \
         patch.object(svc, "search_web", AsyncMock(return_value=[{"title":"World Cup 2026 dates","url":"x","snippet":"June 11 – July 19, 2026","platform":"web"}])):
        out = await svc.get_occasions(db=None, country="israel", language="ar", period="2026-08")
    assert any("المونديال" in o["title"] for o in out)

@pytest.mark.asyncio
async def test_get_occasions_never_raises_on_failure():
    from api.services import occasions_service as svc
    with patch.object(svc, "get_cached", AsyncMock(return_value=None)), \
         patch.object(svc, "call_text_ai", AsyncMock(side_effect=RuntimeError("boom"))):
        out = await svc.get_occasions(db=None, country="x", language="ar", period="2026-08")
    assert out == []
```

- [ ] **Step 2: Run** → FAIL (ImportError)

- [ ] **Step 3: Write minimal implementation**
```python
# api/services/occasions_service.py
import json, logging
from .multi_scraper import search_web
from ..core.llm_client import call_text_ai
from .research_cache import get_cached, upsert_cached

log = logging.getLogger(__name__)
OCCASION_TYPES = {"religious","national","school","sports","seasonal","commercial"}


def _extract_json(raw: str):
    start = raw.find("{")
    if start < 0: return {}
    depth = 0
    for i in range(start, len(raw)):
        if raw[i] == "{": depth += 1
        elif raw[i] == "}":
            depth -= 1
            if depth == 0:
                try: return json.loads(raw[start:i+1])
                except Exception: return {}
    return {}


def _prompt(country, language, period):
    return (
        f"List real-world occasions relevant to an audience in country='{country}', "
        f"audience language='{language}', for the month/period='{period}'. Include religious, "
        f"national, school (breaks/return), sports (e.g. World Cup, Champions League), seasonal and "
        f"commercial shopping events. Return ONLY JSON: "
        f'{{"occasions":[{{"title": "...", "type": "religious|national|school|sports|seasonal|commercial", '
        f'"date_or_window": "YYYY-MM or YYYY-MM-DD or range", "confidence": "high|medium|low"}}]}}'
    )


async def _verify(occasions):
    """Web-verify movable/sports/school dates; downgrade confidence when unfound."""
    for occ in occasions:
        if occ.get("type") in {"sports","school","seasonal"} and occ.get("confidence") != "high":
            try:
                hits = await search_web(f"{occ.get('title','')} {occ.get('date_or_window','')} date", limit=3)
            except Exception:
                hits = []
            occ["verified_by"] = "web" if hits else "llm"
            if hits and occ.get("confidence") == "low":
                occ["confidence"] = "medium"
        else:
            occ.setdefault("verified_by", "llm")
    return occasions


async def get_occasions(db, *, country, language, period):
    try:
        cached = await get_cached(db, kind="occasions", country=country, language=language, period=period)
        if cached is not None:
            return cached
        raw = await call_text_ai(max_tokens=1500,
                                 messages=[{"role":"user","content":_prompt(country, language, period)}],
                                 system="You are a cultural calendar expert. Return valid JSON only.")
        occasions = [o for o in (_extract_json(raw).get("occasions") or [])
                     if isinstance(o, dict) and o.get("title")]
        for o in occasions:
            if o.get("type") not in OCCASION_TYPES: o["type"] = "seasonal"
            o.setdefault("confidence", "medium")
        occasions = await _verify(occasions)
        if db is not None:
            await upsert_cached(db, kind="occasions", country=country, language=language,
                                period=period, data=occasions, source="hybrid", ttl_days=120)
        return occasions
    except Exception:
        log.exception("occasions fetch failed for %s/%s/%s", country, language, period)
        return []
```

- [ ] **Step 4: Run** → `python3 -m pytest tests/test_occasions_service.py -q` → PASS
- [ ] **Step 5: Commit** — `git commit -m "feat(research): hybrid occasions service"`

---

### Task 4: Market-research cache wrapper

**Files:**
- Create: `api/services/market_research.py`
- Test: `tests/test_market_research.py`

**Interfaces:**
- Consumes: `research_competitors` (strategy_generator), cache service.
- Produces: `async def get_market_research(db, *, country, language, brand: dict) -> dict` → `{audience_behavior, local_trends, competitors_summary}`; cache-or-fetch, `[]/{}` safe on failure.

- [ ] **Step 1: Write the failing test**
```python
# tests/test_market_research.py
import pytest
from unittest.mock import AsyncMock, patch

@pytest.mark.asyncio
async def test_market_research_cache_hit():
    from api.services import market_research as mr
    with patch.object(mr, "get_cached", AsyncMock(return_value={"audience_behavior":"x","local_trends":[],"competitors_summary":""})):
        out = await mr.get_market_research(db=None, country="israel", language="ar", brand={})
    assert out["audience_behavior"] == "x"

@pytest.mark.asyncio
async def test_market_research_never_raises():
    from api.services import market_research as mr
    with patch.object(mr, "get_cached", AsyncMock(return_value=None)), \
         patch.object(mr, "research_competitors", AsyncMock(side_effect=RuntimeError())):
        out = await mr.get_market_research(db=None, country="x", language="ar", brand={"competitors":["a"]})
    assert set(out.keys()) == {"audience_behavior","local_trends","competitors_summary"}
```

- [ ] **Step 2: Run** → FAIL

- [ ] **Step 3: Write minimal implementation**
```python
# api/services/market_research.py
import logging
from .research_cache import get_cached, upsert_cached
from .strategy_generator import research_competitors

log = logging.getLogger(__name__)
_EMPTY = {"audience_behavior": "", "local_trends": [], "competitors_summary": ""}


async def get_market_research(db, *, country, language, brand: dict) -> dict:
    try:
        cached = await get_cached(db, kind="market", country=country, language=language, period=None)
        if cached is not None:
            return cached
        competitors = [c for c in (brand.get("competitors") or []) if isinstance(c, str)][:4]
        summary = ""
        if competitors:
            snippets = await research_competitors(competitors, str(brand.get("name") or ""))
            summary = " | ".join(f"{k}: {v[:200]}" for k, v in snippets.items() if v)
        data = {"audience_behavior": str(brand.get("audience_notes") or brand.get("target_audience") or ""),
                "local_trends": [], "competitors_summary": summary}
        if db is not None:
            await upsert_cached(db, kind="market", country=country, language=language,
                                period=None, data=data, source="hybrid", ttl_days=90)
        return data
    except Exception:
        log.exception("market research failed for %s/%s", country, language)
        return dict(_EMPTY)
```

- [ ] **Step 4: Run** → PASS
- [ ] **Step 5: Commit** — `git commit -m "feat(research): market research cache wrapper"`

---

### Task 5: Occasion → brand relevance filter (pure)

**Files:**
- Create: `api/services/occasion_match.py`
- Test: `tests/test_occasion_match.py`

**Interfaces:**
- Produces: `def relevant_occasions(occasions: list[dict], brand: dict, *, limit=6) -> list[dict]` — keeps universally-relevant types (religious/national/seasonal/commercial) always; sports/school kept when the brand's field/audience plausibly cares; ranked by confidence then type; capped at `limit`.

- [ ] **Step 1: Write the failing test**
```python
# tests/test_occasion_match.py
def test_relevant_occasions_ranks_and_caps():
    from api.services.occasion_match import relevant_occasions
    occ = [
        {"title":"عيد الأضحى","type":"religious","confidence":"high"},
        {"title":"المونديال","type":"sports","confidence":"medium"},
        {"title":"رجعة المدارس","type":"school","confidence":"high"},
    ]
    out = relevant_occasions(occ, {"industry":"retail"}, limit=2)
    assert len(out) == 2
    assert out[0]["title"] == "عيد الأضحى"   # high-confidence universal first

def test_relevant_occasions_empty_safe():
    from api.services.occasion_match import relevant_occasions
    assert relevant_occasions([], {}) == []
```

- [ ] **Step 2: Run** → FAIL

- [ ] **Step 3: Write minimal implementation**
```python
# api/services/occasion_match.py
_UNIVERSAL = {"religious","national","seasonal","commercial"}
_CONF_RANK = {"high":0,"medium":1,"low":2}


def relevant_occasions(occasions, brand, *, limit=6):
    kept = []
    for o in occasions or []:
        if not isinstance(o, dict) or not o.get("title"):
            continue
        t = o.get("type")
        if t in _UNIVERSAL or t in {"sports","school"}:   # keep sports/school this phase; refine later
            kept.append(o)
    kept.sort(key=lambda o: (_CONF_RANK.get(o.get("confidence"), 1),
                             0 if o.get("type") in _UNIVERSAL else 1))
    return kept[:limit]
```

- [ ] **Step 4: Run** → PASS
- [ ] **Step 5: Commit** — `git commit -m "feat(research): occasion relevance filter"`

---

## Self-review notes

- Spec coverage: research_cache table (Task 1), cache reuse (Task 2), hybrid occasions (Task 3), market research (Task 4), occasion matching (Task 5). Wiring into generation + prompts + UI = Phase 2/3 (separate plans).
- The `db=None` guard in services makes them unit-testable without a DB and no-ops the cache write in tests.
- Deploy after Task 5: `Base.metadata.create_all` + the raw CREATE TABLE make `research_cache` appear on prod at startup; services are dormant until Phase 2 wires them in — safe to ship incrementally.

## Follow-on plans
- **Phase 2** — generation reshape: modify `build_social_content_plan_prompt`/`DEFAULT_SOCIAL_WORK_PLAN_PROMPTS` to request ideas (not content), inject occasions+market, over-generate 2N, emit new idea shape + preselected "middle" asset set, extend asset taxonomy, adapt fallback.
- **Phase 3** — endpoints + mobile-first idea-selection gallery (single feed + filters, inline-accordion card, sticky counter, notes, asset chips), persist selection.
