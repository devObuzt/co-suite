import asyncio
import json
import logging
import sys

from ..core.database import AsyncSessionLocal
from ..core.observability import configure_logging, worker_health_payload
from ..services.durable_generation_queue import run_forever


def main() -> None:
    configure_logging()
    if "--healthcheck" in sys.argv:
        async def _healthcheck() -> None:
            async with AsyncSessionLocal() as db:
                payload = await worker_health_payload(db)
                print(json.dumps(payload))

        asyncio.run(_healthcheck())
        return

    logging.getLogger(__name__).info("Starting generation queue worker.")
    asyncio.run(run_forever())


if __name__ == "__main__":
    main()
