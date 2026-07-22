import asyncio
import os
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
from .routers import admin
from .routers import app_text
from .routers import video_montage
from .routers import media
from .routers import funnel
from .routers import admin_catalog
from .services.durable_generation_queue import run_forever
from .services.creative_assets import count_builtin_creative_assets, seed_builtin_creative_assets
from .services.service_catalog_seed import seed_service_items

app = FastAPI(title=settings.app_name, docs_url="/docs" if settings.debug else None)
configure_logging()
_embedded_generation_worker_task: asyncio.Task | None = None

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


# httpx logs full request URLs at INFO level, which leaks access tokens and
# client secrets into deploy logs — keep it at WARNING.
import logging as _logging
_logging.getLogger("httpx").setLevel(_logging.WARNING)


@app.on_event("startup")
async def startup():
    import logging
    log = logging.getLogger(__name__)
    global _embedded_generation_worker_task
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
                    "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_super_admin BOOLEAN DEFAULT FALSE NOT NULL",
                    "CREATE TABLE IF NOT EXISTS audit_logs (id VARCHAR PRIMARY KEY, actor_user_id VARCHAR REFERENCES users(id), actor_email VARCHAR, action VARCHAR NOT NULL, resource_type VARCHAR NOT NULL, resource_id VARCHAR, suite_id VARCHAR REFERENCES suites(id), target_user_id VARCHAR REFERENCES users(id), metadata_json JSON, ip_address VARCHAR, user_agent TEXT, created_at TIMESTAMP WITH TIME ZONE DEFAULT now())",
                    "CREATE INDEX IF NOT EXISTS ix_audit_logs_created_at ON audit_logs (created_at)",
                    "CREATE INDEX IF NOT EXISTS ix_audit_logs_action ON audit_logs (action)",
                    "CREATE INDEX IF NOT EXISTS ix_audit_logs_actor_user_id ON audit_logs (actor_user_id)",
                    "CREATE INDEX IF NOT EXISTS ix_audit_logs_suite_id ON audit_logs (suite_id)",
                    "CREATE INDEX IF NOT EXISTS ix_audit_logs_target_user_id ON audit_logs (target_user_id)",
                    "CREATE TABLE IF NOT EXISTS provider_usage_events (id VARCHAR PRIMARY KEY, provider VARCHAR NOT NULL, model VARCHAR, endpoint VARCHAR, operation VARCHAR NOT NULL, status VARCHAR DEFAULT 'success' NOT NULL, input_tokens INTEGER DEFAULT 0 NOT NULL, output_tokens INTEGER DEFAULT 0 NOT NULL, total_tokens INTEGER DEFAULT 0 NOT NULL, actual_cost_usd DOUBLE PRECISION DEFAULT 0 NOT NULL, suite_id VARCHAR REFERENCES suites(id), user_id VARCHAR REFERENCES users(id), generation_job_id VARCHAR REFERENCES generation_jobs(id), latency_ms INTEGER, request_id VARCHAR, metadata_json JSON, created_at TIMESTAMP WITH TIME ZONE DEFAULT now())",
                    "CREATE INDEX IF NOT EXISTS ix_provider_usage_events_created_at ON provider_usage_events (created_at)",
                    "CREATE INDEX IF NOT EXISTS ix_provider_usage_events_provider ON provider_usage_events (provider)",
                    "CREATE INDEX IF NOT EXISTS ix_provider_usage_events_model ON provider_usage_events (model)",
                    "CREATE INDEX IF NOT EXISTS ix_provider_usage_events_operation ON provider_usage_events (operation)",
                    "CREATE INDEX IF NOT EXISTS ix_provider_usage_events_status ON provider_usage_events (status)",
                    "CREATE INDEX IF NOT EXISTS ix_provider_usage_events_suite_id ON provider_usage_events (suite_id)",
                    "CREATE TABLE IF NOT EXISTS app_text_overrides (id VARCHAR PRIMARY KEY, language VARCHAR(12) NOT NULL, text_key VARCHAR(240) NOT NULL, value TEXT NOT NULL, updated_by_user_id VARCHAR REFERENCES users(id), updated_by_email VARCHAR, created_at TIMESTAMP WITH TIME ZONE DEFAULT now(), updated_at TIMESTAMP WITH TIME ZONE DEFAULT now(), CONSTRAINT uq_app_text_overrides_language_key UNIQUE (language, text_key))",
                    "CREATE INDEX IF NOT EXISTS ix_app_text_overrides_language ON app_text_overrides (language)",
                    "CREATE INDEX IF NOT EXISTS ix_app_text_overrides_text_key ON app_text_overrides (text_key)",
                    "CREATE INDEX IF NOT EXISTS ix_app_text_overrides_updated_at ON app_text_overrides (updated_at)",
                    "CREATE TABLE IF NOT EXISTS creative_assets (id VARCHAR PRIMARY KEY, kind VARCHAR NOT NULL, title VARCHAR NOT NULL, storage_url TEXT NOT NULL, source_url TEXT, content_type VARCHAR, duration_seconds DOUBLE PRECISION, tags JSON, use_cases JSON, classification JSON, active BOOLEAN DEFAULT TRUE NOT NULL, usage_count INTEGER DEFAULT 0 NOT NULL, last_used_at TIMESTAMP WITH TIME ZONE, metadata_json JSON, created_by_user_id VARCHAR REFERENCES users(id), created_at TIMESTAMP WITH TIME ZONE DEFAULT now(), updated_at TIMESTAMP WITH TIME ZONE DEFAULT now())",
                    "CREATE INDEX IF NOT EXISTS ix_creative_assets_kind ON creative_assets (kind)",
                    "CREATE INDEX IF NOT EXISTS ix_creative_assets_active ON creative_assets (active)",
                    "CREATE INDEX IF NOT EXISTS ix_creative_assets_created_at ON creative_assets (created_at)",
                    "CREATE INDEX IF NOT EXISTS ix_creative_assets_created_by_user_id ON creative_assets (created_by_user_id)",
                    "ALTER TABLE users ADD COLUMN IF NOT EXISTS approval_status VARCHAR DEFAULT 'frozen' NOT NULL",
                    "ALTER TABLE users ADD COLUMN IF NOT EXISTS phone VARCHAR",
                    "UPDATE users SET approval_status = 'approved' WHERE lower(email) IN ('w.sholy@gmail.com', 'admin@connec.co.il') OR is_super_admin = TRUE",
                    "CREATE TABLE IF NOT EXISTS service_items (id VARCHAR PRIMARY KEY, name JSON NOT NULL, description JSON NOT NULL, category JSON NOT NULL, billing_cycle VARCHAR DEFAULT 'one_time' NOT NULL, price_min DOUBLE PRECISION DEFAULT 0 NOT NULL, price_max DOUBLE PRECISION, unit JSON, is_active BOOLEAN DEFAULT TRUE NOT NULL, sort_order INTEGER DEFAULT 0 NOT NULL, created_at TIMESTAMP WITH TIME ZONE DEFAULT now(), updated_at TIMESTAMP WITH TIME ZONE DEFAULT now())",
                    "CREATE TABLE IF NOT EXISTS leads (id VARCHAR PRIMARY KEY, user_id VARCHAR REFERENCES users(id) NOT NULL, suite_id VARCHAR REFERENCES suites(id) ON DELETE SET NULL, full_name VARCHAR NOT NULL, email VARCHAR NOT NULL, phone VARCHAR NOT NULL, status VARCHAR DEFAULT 'new' NOT NULL, source VARCHAR DEFAULT 'startbyconnec' NOT NULL, admin_notes TEXT, recommendations JSON, progress JSON, created_at TIMESTAMP WITH TIME ZONE DEFAULT now(), updated_at TIMESTAMP WITH TIME ZONE DEFAULT now())",
                    "CREATE INDEX IF NOT EXISTS ix_leads_user_id ON leads (user_id)",
                    "CREATE TABLE IF NOT EXISTS service_requests (id VARCHAR PRIMARY KEY, lead_id VARCHAR REFERENCES leads(id) NOT NULL, items JSON NOT NULL, totals JSON NOT NULL, customer_notes TEXT, status VARCHAR DEFAULT 'new' NOT NULL, created_at TIMESTAMP WITH TIME ZONE DEFAULT now())",
                    "CREATE INDEX IF NOT EXISTS ix_service_requests_lead_id ON service_requests (lead_id)",
                    "CREATE TABLE IF NOT EXISTS research_cache (id VARCHAR PRIMARY KEY, kind VARCHAR(40) NOT NULL, country VARCHAR(80) NOT NULL, language VARCHAR(16) NOT NULL, period VARCHAR(16), data JSON, source VARCHAR(16) DEFAULT 'hybrid' NOT NULL, created_at TIMESTAMP WITH TIME ZONE DEFAULT now(), refreshed_at TIMESTAMP WITH TIME ZONE DEFAULT now(), expires_at TIMESTAMP WITH TIME ZONE, CONSTRAINT uq_research_cache_kind_country_language_period UNIQUE (kind, country, language, period))",
                    "CREATE INDEX IF NOT EXISTS ix_research_cache_kind ON research_cache (kind)",
                    "CREATE INDEX IF NOT EXISTS ix_research_cache_country ON research_cache (country)",
                    "CREATE INDEX IF NOT EXISTS ix_research_cache_language ON research_cache (language)",
                    # Phone-only funnel auth: lead is captured before any user exists
                    "ALTER TABLE leads ALTER COLUMN user_id DROP NOT NULL",
                    "ALTER TABLE leads ALTER COLUMN full_name DROP NOT NULL",
                    "ALTER TABLE leads ALTER COLUMN email DROP NOT NULL",
                    "CREATE INDEX IF NOT EXISTS ix_leads_phone ON leads (phone)",
                    "CREATE TABLE IF NOT EXISTS phone_otps (id VARCHAR PRIMARY KEY, phone VARCHAR NOT NULL, code VARCHAR NOT NULL, attempts INTEGER DEFAULT 0 NOT NULL, expires_at TIMESTAMP WITH TIME ZONE NOT NULL, verified_at TIMESTAMP WITH TIME ZONE, created_at TIMESTAMP WITH TIME ZONE DEFAULT now())",
                    "CREATE INDEX IF NOT EXISTS ix_phone_otps_phone ON phone_otps (phone)",
                ):
                    await conn.execute(text(statement))
        except Exception as e:
            log.warning("billing ledger migration skipped: %s", e)

        if settings.admin_email.strip():
            try:
                async with engine.begin() as conn:
                    await conn.execute(
                        text("UPDATE users SET is_super_admin = TRUE WHERE lower(email) = lower(:email)"),
                        {"email": settings.admin_email.strip()},
                    )
            except Exception as e:
                log.warning("admin promotion migration skipped: %s", e)

        try:
            async with AsyncSessionLocal() as session:
                seeded_assets = await seed_builtin_creative_assets(session)
                builtins_count = await count_builtin_creative_assets(session)
                log.info("Built-in creative assets synced. inserted=%d total=%d", seeded_assets, builtins_count)
        except Exception as e:
            log.warning("built-in creative asset seed skipped: %s", e)

        try:
            async with AsyncSessionLocal() as session:
                await seed_service_items(session)
        except Exception as e:
            log.warning("service catalog seed skipped: %s", e)

        async with engine.begin() as conn:
            for value in (
                "marketing_plan",
                "product_bulk_import",
                "product_bulk_generate_first",
                "product_bulk_generate_all",
                "product_bulk_regenerate_asset",
                "video_montage",
            ):
                await conn.execute(text(
                    f"ALTER TYPE generationjobtype ADD VALUE IF NOT EXISTS '{value}'"
                ))
    except Exception as e:
        log.error("Database startup failed (check DATABASE_URL env var): %s", e)
        raise

    embedded_worker_enabled = os.getenv("EMBEDDED_GENERATION_WORKER", "true").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }
    if embedded_worker_enabled and (
        _embedded_generation_worker_task is None or _embedded_generation_worker_task.done()
    ):
        _embedded_generation_worker_task = asyncio.create_task(run_forever())
        log.info("Embedded generation queue worker started in API process.")


@app.on_event("shutdown")
async def shutdown():
    global _embedded_generation_worker_task
    if _embedded_generation_worker_task and not _embedded_generation_worker_task.done():
        _embedded_generation_worker_task.cancel()


app.include_router(auth.router, prefix="/api/v1")
app.include_router(suites.router, prefix="/api/v1")
app.include_router(onboarding.router, prefix="/api/v1")
app.include_router(content.router, prefix="/api/v1")
app.include_router(connections.router, prefix="/api/v1")
app.include_router(billing.router, prefix="/api/v1")
app.include_router(analytics.router, prefix="/api/v1")
app.include_router(product_bulk.router, prefix="/api/v1")
app.include_router(marketing_plans.router, prefix="/api/v1")
app.include_router(admin.router, prefix="/api/v1")
app.include_router(app_text.router, prefix="/api/v1")
app.include_router(video_montage.router, prefix="/api/v1")
app.include_router(media.router, prefix="/api/v1")
app.include_router(funnel.router, prefix="/api/v1")
app.include_router(admin_catalog.router, prefix="/api/v1")


@app.get("/health")
async def health():
    return await api_health_payload()


@app.get("/health/ready")
async def readiness():
    async with AsyncSessionLocal() as db:
        return await api_health_payload(db)
