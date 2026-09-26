from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select, text

from app.config import settings
from app.db import Base, engine, SessionLocal
from app.models import Connection, CostLineItem
from app.routers import admin, connections, costs, dashboards, entra, entra_ops, me, recommendations
from app.entra.sync import ensure_env_tenant
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
        await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS user_principal_name VARCHAR(320) DEFAULT ''"))
        await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS job_title VARCHAR(256) DEFAULT ''"))
        await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS department VARCHAR(256) DEFAULT ''"))
        await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS source VARCHAR(16) DEFAULT 'local'"))
        await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_synced_at TIMESTAMPTZ"))
        await conn.execute(text("ALTER TABLE directory_sync_runs ADD COLUMN IF NOT EXISTS apps_upserted INTEGER DEFAULT 0"))
        await conn.execute(text("ALTER TABLE directory_sync_runs ADD COLUMN IF NOT EXISTS assignments_upserted INTEGER DEFAULT 0"))
        await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS entra_tenant_id UUID"))
        await conn.execute(text("ALTER TABLE entra_groups ADD COLUMN IF NOT EXISTS tenant_id UUID"))
        await conn.execute(text("ALTER TABLE entra_applications ADD COLUMN IF NOT EXISTS tenant_id UUID"))
        await conn.execute(text("ALTER TABLE directory_sync_runs ADD COLUMN IF NOT EXISTS tenant_id UUID"))
        await conn.execute(text("ALTER TABLE entra_groups DROP CONSTRAINT IF EXISTS entra_groups_entra_id_key"))
        await conn.execute(text("ALTER TABLE entra_applications DROP CONSTRAINT IF EXISTS entra_applications_service_principal_id_key"))
        await conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_entra_groups_tenant_entra ON entra_groups (tenant_id, entra_id)"))
        await conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_entra_apps_tenant_sp ON entra_applications (tenant_id, service_principal_id)"))
        await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS usage_location VARCHAR(8) DEFAULT ''"))
        await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS assigned_licenses JSONB DEFAULT '[]'::jsonb"))
    if settings.seed_on_startup:
        async with SessionLocal() as session:
            await seed_if_empty(session)
    async with SessionLocal() as session:
        await ensure_iam(session)
    async with SessionLocal() as session:
        await ensure_env_tenant(session)
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
app.include_router(entra.router)
app.include_router(entra_ops.router)


@app.get("/health")
async def health():
    return {"ok": True, "service": "looking-glass-api"}
