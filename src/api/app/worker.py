"""Background ingest + recommendation loop.

Same image as the API: `python -m app.worker`
"""

from __future__ import annotations

import asyncio
import logging
import os

from app.connectors.registry import ingest_all
from app.db import SessionLocal
from app.services.recommend import refresh_recommendations

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("looking-glass.worker")
INTERVAL = int(os.getenv("WORKER_INTERVAL_SECONDS", str(6 * 60 * 60)))


async def run_once() -> None:
    async with SessionLocal() as session:
        results = await ingest_all(session)
        created = await refresh_recommendations(session)
        log.info("ingest complete rows=%s recommendations=%s", results, created)


async def main() -> None:
    log.info("worker started interval=%ss", INTERVAL)
    while True:
        try:
            await run_once()
            await asyncio.sleep(INTERVAL)
        except Exception:
            log.exception("worker cycle failed")
            await asyncio.sleep(30)


if __name__ == "__main__":
    asyncio.run(main())
