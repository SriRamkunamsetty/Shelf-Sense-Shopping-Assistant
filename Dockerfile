# syntax=docker/dockerfile:1
# ---- 1) build the React app ----------------------------------------------------
FROM node:22-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---- 2) runtime: FastAPI serves the API and the built UI ------------------------
FROM python:3.13-slim AS app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1 \
    PORT=8080 STATIC_DIR=/app/static APP_ENV=production DEMO_MODE=false SEED_ON_START=false
WORKDIR /app
COPY backend/pyproject.toml ./
COPY backend/shelfsense ./shelfsense
RUN pip install ".[gcp]" && useradd --system --uid 10001 shelf && chown -R shelf /app
COPY --from=web /web/dist ./static
USER shelf
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s --start-period=20s \
  CMD python -c "import os,urllib.request as u; u.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/api/health', timeout=2)"
CMD ["sh", "-c", "exec uvicorn shelfsense.api.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
