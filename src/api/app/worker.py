"""Background ingest, recommendations, and Entra directory sync."""

from __future__ import annotations

import asyncio
import logging
import os

from app.config import settings
from app.connectors.registry import ingest_all
from app.db import SessionLocal
from app.entra.sync import sync_all_tenants
from app.services.recommend import refresh_recommendations

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("looking-glass.worker")
INTERVAL = int(os.getenv("WORKER_INTERVAL_SECONDS", str(6 * 60 * 60)))


async def run_ingest() -> None:
    async with SessionLocal() as session:
        results = await ingest_all(session)
        created = await refresh_recommendations(session)
        log.info("ingest complete rows=%s recommendations=%s", results, created)


async def run_entra_sync() -> None:
    async with SessionLocal() as session:
        runs = await sync_all_tenants(session)
        for run in runs:
            log.info(
                "entra sync %s tenant=%s users=%s groups=%s members=%s apps=%s assignments=%s error=%s",
                run.status,
                run.tenant_id,
                run.users_upserted,
                run.groups_upserted,
                run.memberships_upserted,
                run.apps_upserted,
                run.assignments_upserted,
                run.error,
            )


async def _loop(name: str, interval: int, job) -> None:
    log.info("%s loop interval=%ss", name, interval)
    while True:
        try:
            await job()
        except Exception:
            log.exception("%s cycle failed", name)
            await asyncio.sleep(30)
            continue
        await asyncio.sleep(max(interval, 60))


async def main() -> None:
    log.info("worker started")
    tasks = [
        asyncio.create_task(_loop("ingest", INTERVAL, run_ingest)),
        asyncio.create_task(_loop("entra", settings.entra_sync_interval_seconds, run_entra_sync)),
    ]
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())
