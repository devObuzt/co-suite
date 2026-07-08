import asyncio
import json
import logging
import sys

from ..core.database import AsyncSessionLocal
from ..core.observability import configure_logging, worker_health_payload
from ..services.capacity_watchdog import run_capacity_watchdog
from ..services.creative_assets import seed_builtin_creative_assets
from ..services.durable_generation_queue import run_forever

log = logging.getLogger(__name__)


async def _run_worker() -> None:
    # Idempotent: keeps builtin creative asset rows pointing at the
    # repo-shipped library files even if the API has not redeployed yet.
    try:
        async with AsyncSessionLocal() as db:
            seeded = await seed_builtin_creative_assets(db)
            log.info("Built-in creative assets synced on worker startup. inserted=%d", seeded)
    except Exception:
        log.exception("Built-in creative asset seed skipped on worker startup.")
    await asyncio.gather(run_forever(), run_capacity_watchdog())


def main() -> None:
    configure_logging()
    if "--healthcheck" in sys.argv:
        async def _healthcheck() -> None:
            async with AsyncSessionLocal() as db:
                payload = await worker_health_payload(db)
                print(json.dumps(payload))

        asyncio.run(_healthcheck())
        return

    log.info("Starting generation queue worker.")
    asyncio.run(_run_worker())


if __name__ == "__main__":
    main()
