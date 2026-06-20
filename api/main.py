from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from .core.observability import api_health_payload, configure_logging
from .core.config import settings
from .core.database import AsyncSessionLocal, engine, Base
from .routers import auth, suites, onboarding
from .routers import content
from .routers import connections
from .routers import billing
from .routers import analytics
from .routers import product_bulk
from .routers import marketing_plans

app = FastAPI(title=settings.app_name, docs_url="/docs" if settings.debug else None)
configure_logging()

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

        try:
            async with engine.begin() as conn:
                for statement in (
                    "ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS generation_token_balance INTEGER DEFAULT 0 NOT NULL",
                    "ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS marketing_budget_balance_usd DOUBLE PRECISION DEFAULT 0 NOT NULL",
                    "ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS monthly_generation_token_grant INTEGER DEFAULT 0 NOT NULL",
                    "ALTER TABLE usage_events ADD COLUMN IF NOT EXISTS ledger_account VARCHAR DEFAULT 'generation_tokens' NOT NULL",
                    "ALTER TABLE usage_events ADD COLUMN IF NOT EXISTS billing_event_type VARCHAR DEFAULT 'legacy_usage_charge' NOT NULL",
                    "ALTER TABLE usage_events ADD COLUMN IF NOT EXISTS amount_tokens INTEGER DEFAULT 0 NOT NULL",
                    "ALTER TABLE usage_events ADD COLUMN IF NOT EXISTS balance_after_tokens INTEGER",
                    "ALTER TABLE usage_events ADD COLUMN IF NOT EXISTS amount_usd DOUBLE PRECISION DEFAULT 0 NOT NULL",
                    "ALTER TABLE usage_events ADD COLUMN IF NOT EXISTS balance_after_usd DOUBLE PRECISION",
                    "ALTER TABLE usage_events ADD COLUMN IF NOT EXISTS external_ref VARCHAR",
                    "ALTER TABLE usage_events ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR",
                    "CREATE INDEX IF NOT EXISTS ix_usage_events_idempotency_key ON usage_events (idempotency_key)",
                ):
                    await conn.execute(text(statement))
        except Exception as e:
            log.warning("billing ledger migration skipped: %s", e)

        async with engine.begin() as conn:
            for value in (
                "product_bulk_import",
                "product_bulk_generate_first",
                "product_bulk_generate_all",
                "product_bulk_regenerate_asset",
            ):
                await conn.execute(text(
                    f"ALTER TYPE generationjobtype ADD VALUE IF NOT EXISTS '{value}'"
                ))
    except Exception as e:
        log.error("Database startup failed (check DATABASE_URL env var): %s", e)
        raise


app.include_router(auth.router, prefix="/api/v1")
app.include_router(suites.router, prefix="/api/v1")
app.include_router(onboarding.router, prefix="/api/v1")
app.include_router(content.router, prefix="/api/v1")
app.include_router(connections.router, prefix="/api/v1")
app.include_router(billing.router, prefix="/api/v1")
app.include_router(analytics.router, prefix="/api/v1")
app.include_router(product_bulk.router, prefix="/api/v1")
app.include_router(marketing_plans.router, prefix="/api/v1")


@app.get("/health")
async def health():
    return await api_health_payload()


@app.get("/health/ready")
async def readiness():
    async with AsyncSessionLocal() as db:
        return await api_health_payload(db)
