# ── Stage 1: Build React frontend ──────────────────────────────
FROM node:20-alpine AS frontend-build

WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci
# Cache-bust: changing FRONTEND_VERSION invalidates the COPY + build layers
ARG FRONTEND_VERSION=1
COPY frontend/ ./
RUN npm run build

# ── Stage 2: Python backend + built frontend ──────────────────
FROM python:3.12-slim

# Prevent Python from buffering stdout/stderr (important for Docker logs)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install system deps (needed for some Python packages + health check)
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc libffi-dev curl && \
    rm -rf /var/lib/apt/lists/*

# Install Python dependencies (--prefer-binary avoids compiling numpy/pandas from source)
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir --prefer-binary -r requirements.txt

# Copy backend source
COPY backend/ ./

# Copy built frontend from stage 1
COPY --from=frontend-build /build/frontend/dist /app/frontend/dist

# Create data directory (will be overridden by volume mount)
RUN mkdir -p /app/data

# Default environment for Docker (can be overridden in docker-compose)
ENV API_HOST=0.0.0.0 \
    API_PORT=8000 \
    DB_PATH=/app/data/bot_data.db \
    CONFIG_FILE=/app/data/bot_config.json

EXPOSE 8000

# Single worker — the bot uses async tasks that share state in-process
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
