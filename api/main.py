from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from .core.config import settings
from .core.database import engine, Base
from .routers import auth, suites, onboarding
from .routers import content
from .routers import connections
from .routers import billing
from .routers import analytics

app = FastAPI(title=settings.app_name, docs_url="/docs" if settings.debug else None)

_origins = [o.strip() for o in settings.frontend_url.split(",") if o.strip()]
_origins += ["http://localhost:3000", "http://localhost:3001", "http://localhost:3002"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_origin_regex=r"https://.*\.up\.railway\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


_static_dir = Path(__file__).parent / "static"
_static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")


@app.on_event("startup")
async def startup():
    import logging
    log = logging.getLogger(__name__)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        try:
            async with engine.begin() as conn:
                await conn.execute(text(
                    "ALTER TABLE suites ADD COLUMN IF NOT EXISTS strategy JSON"
                ))
        except Exception as e:
            log.warning("strategy column migration skipped: %s", e)
    except Exception as e:
        log.error("Database startup failed (check DATABASE_URL env var): %s", e)


app.include_router(auth.router, prefix="/api/v1")
app.include_router(suites.router, prefix="/api/v1")
app.include_router(onboarding.router, prefix="/api/v1")
app.include_router(content.router, prefix="/api/v1")
app.include_router(connections.router, prefix="/api/v1")
app.include_router(billing.router, prefix="/api/v1")
app.include_router(analytics.router, prefix="/api/v1")


@app.get("/health")
async def health():
    return {"status": "ok", "app": settings.app_name}


@app.get("/debug-ai")
async def debug_ai():
    """Temporary: diagnose Claude API connectivity."""
    import requests as _req
    import anthropic as _anthropic

    # Test 1: raw HTTPS connectivity to Anthropic
    raw_ok = False
    raw_err = ""
    try:
        r = _req.get("https://api.anthropic.com", timeout=5)
        raw_ok = True
    except Exception as e:
        raw_err = str(e)

    # Test 2: requests-based Claude call
    sdk_result = ""
    sdk_err = ""
    try:
        from .core.ai_client import call_claude
        sdk_result = await call_claude(
            model="claude-haiku-4-5-20251001",
            max_tokens=10,
            messages=[{"role": "user", "content": "Say OK"}],
        )
    except Exception as e:
        sdk_err = f"{type(e).__name__}: {e}"

    return {
        "raw_https_ok": raw_ok,
        "raw_error": raw_err,
        "key_prefix": settings.anthropic_api_key[:12] if settings.anthropic_api_key else "NOT SET",
        "sdk_result": sdk_result,
        "sdk_error": sdk_err,
    }
