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

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


_static_dir = Path(__file__).parent / "static"
_static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")


@app.on_event("startup")
async def startup():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    # Run DDL migrations separately so a failure doesn't crash startup
    try:
        async with engine.begin() as conn:
            await conn.execute(text(
                "ALTER TABLE suites ADD COLUMN IF NOT EXISTS strategy JSON"
            ))
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("strategy column migration skipped: %s", e)


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
