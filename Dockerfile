# syntax=docker/dockerfile:1
#
# Looking Glass — multi-target image
#
#   docker build --target api    -t looking-glass-api .
#   docker build --target worker -t looking-glass-worker .
#   docker build --target web    -t looking-glass-web .
#
# Compose uses these targets. Prefer `docker compose up --build`.

# ---------------------------------------------------------------------------
# API / worker
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS api-base

WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 --shell /usr/sbin/nologin appuser

COPY src/api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/api/app ./app
RUN chown -R appuser:appuser /app
USER appuser
EXPOSE 8000

FROM api-base AS api
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/health || exit 1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM api-base AS worker
CMD ["python", "-m", "app.worker"]

# ---------------------------------------------------------------------------
# Web (Next.js standalone)
# ---------------------------------------------------------------------------
FROM node:22-alpine AS web-deps
WORKDIR /app
COPY src/web/package.json ./
RUN npm install

FROM node:22-alpine AS web-builder
WORKDIR /app
COPY --from=web-deps /app/node_modules ./node_modules
COPY src/web/ ./
ENV NEXT_TELEMETRY_DISABLED=1 \
    AUTH_SECRET=build-placeholder-secret-not-used
RUN npm run build

FROM node:22-alpine AS web
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1
RUN addgroup -S app && adduser -S -G app app
COPY --from=web-builder --chown=app:app /app/.next/standalone ./
COPY --from=web-builder --chown=app:app /app/.next/static ./.next/static
COPY --from=web-builder --chown=app:app /app/public ./public
USER app
EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD node -e "fetch('http://127.0.0.1:3000/api/config').then((r)=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"
CMD ["node", "server.js"]
