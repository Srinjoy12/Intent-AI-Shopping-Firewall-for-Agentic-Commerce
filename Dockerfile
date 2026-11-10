# ==============================================================================
# Intent — AI Shopping Firewall
# Multi-stage production Dockerfile: Node.js frontend + Python FastAPI backend
# ==============================================================================

# --- Stage 1: Build Frontend SPA ---
FROM node:20-alpine AS frontend-builder
WORKDIR /build

# Install dependencies
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

# Copy source and build production bundle
COPY frontend/ ./
RUN npm run build

# --- Stage 2: Python Backend Runtime ---
FROM python:3.12-slim AS runner

WORKDIR /app

# Install curl for healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Persistent disk mount directory (Render / cloud volume)
RUN mkdir -p /var/data

# Install Python dependencies
COPY backend/requirements.txt ./backend/
RUN pip install --no-cache-dir -r ./backend/requirements.txt

# Copy backend application source
COPY backend/ ./backend/

# Copy compiled frontend from Stage 1 into /app/frontend/dist
COPY --from=frontend-builder /build/dist ./frontend/dist

# Default environment configuration
ENV PYTHONPATH=/app/backend \
    DATABASE_PATH=/var/data/intent.db \
    APP_ENV=production \
    APP_MODE=demo \
    WEB_CONCURRENCY=1 \
    PORT=8000 \
    PYTHONUNBUFFERED=1

EXPOSE 8000

# Health check using the /api/health endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/api/health || exit 1

WORKDIR /app/backend

# Single-worker operation is required for SQLite in-memory budget reservation locks
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]

