from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select, text

from app.config import settings
from app.db import Base, engine, SessionLocal
from app.models import Connection, CostLineItem
from app.routers import admin, connections, costs, dashboards, me, recommendations
from app.seed import ensure_iam, seed_if_empty
from app.services.hierarchy import enrich_line


@asynccontextmanager
async def lifespan(_: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("ALTER TABLE connections ADD COLUMN IF NOT EXISTS secrets JSONB DEFAULT '{}'::jsonb"))
        await conn.execute(text("ALTER TABLE cost_line_items ADD COLUMN IF NOT EXISTS resource_group VARCHAR(256) DEFAULT ''"))
        await conn.execute(text("ALTER TABLE cost_line_items ADD COLUMN IF NOT EXISTS org_id VARCHAR(256) DEFAULT ''"))
        await conn.execute(text("ALTER TABLE cost_line_items ADD COLUMN IF NOT EXISTS org_name VARCHAR(256) DEFAULT ''"))
        await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS status VARCHAR(16) DEFAULT 'active'"))
        await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS notes TEXT DEFAULT ''"))
        await conn.execute(text("ALTER TABLE access_groups ADD COLUMN IF NOT EXISTS is_system BOOLEAN DEFAULT false"))
    if settings.seed_on_startup:
        async with SessionLocal() as session:
            await seed_if_empty(session)
    async with SessionLocal() as session:
        await ensure_iam(session)
    async with SessionLocal() as session:
        connections = {row.id: row for row in (await session.execute(select(Connection))).scalars()}
        rows = (await session.execute(select(CostLineItem))).scalars().all()
        for row in rows:
            enrich_line(row, connections.get(row.connection_id))
        await session.commit()
    yield


app = FastAPI(title="Looking Glass", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.web_origin, "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(me.router)
app.include_router(costs.router)
app.include_router(dashboards.router)
app.include_router(recommendations.router)
app.include_router(connections.router)
app.include_router(admin.router)


@app.get("/health")
async def health():
    return {"ok": True, "service": "looking-glass-api"}
