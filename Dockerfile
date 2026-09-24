# ==============================================================================
# APIx Multi-Stage Production & Development Dockerfile
# SIH 2026 Problem Statement 26056: Real-time Airfare Price Index for India
#
# Available Targets:
#   - backend (default): Python 3.12 FastAPI ASGI server
#   - frontend-builder: Vite build stage using Bun
#   - frontend: Lightweight Nginx alpine serving static frontend with SPA routing
# ==============================================================================

# ------------------------------------------------------------------------------
# Stage 1: Backend ASGI Web Service
# ------------------------------------------------------------------------------
FROM python:3.12-slim AS backend

WORKDIR /app

# Prevent Python from writing .pyc files and enable unbuffered output
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PORT=8000

# Install system dependencies (curl for healthchecks, gcc & libpq for psycopg2/asyncpg)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python production dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy backend, ingestion, scripts, and configuration metadata
COPY backend/ ./backend/
COPY ingestion/ ./ingestion/
COPY pyproject.toml .

# Create non-root system user for security compliance
RUN groupadd -r apix && useradd -r -g apix -d /app -s /sbin/nologin apix && \
    chown -R apix:apix /app

USER apix

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]

# ------------------------------------------------------------------------------
# Stage 2: Frontend Vite Asset Builder
# ------------------------------------------------------------------------------
FROM oven/bun:1.2-alpine AS frontend-builder

WORKDIR /app/frontend

# Copy dependency specifications and install lockfile
COPY frontend/package.json frontend/bun.lock* ./
RUN bun install --frozen-lockfile

# Copy source assets and build static distribution
COPY frontend/ ./
RUN bun run build

# ------------------------------------------------------------------------------
# Stage 3: Frontend Static Distribution Web Server (Nginx)
# ------------------------------------------------------------------------------
FROM nginx:alpine AS frontend

# Copy compiled static assets from builder stage
COPY --from=frontend-builder /app/frontend/dist /usr/share/nginx/html

# Configure Nginx for SPA history routing and backend reverse proxying
RUN printf '%s\n' \
    'server {' \
    '    listen 80;' \
    '    server_name localhost;' \
    '    location / {' \
    '        root /usr/share/nginx/html;' \
    '        index index.html index.htm;' \
    '        try_files $uri $uri/ /index.html;' \
    '    }' \
    '    location /api/ {' \
    '        proxy_pass http://backend:8000/api/;' \
    '        proxy_http_version 1.1;' \
    '        proxy_set_header Upgrade $http_upgrade;' \
    '        proxy_set_header Connection "upgrade";' \
    '        proxy_set_header Host $host;' \
    '        proxy_set_header X-Real-IP $remote_addr;' \
    '        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;' \
    '        proxy_set_header X-Forwarded-Proto $scheme;' \
    '    }' \
    '    error_page 500 502 503 504 /50x.html;' \
    '    location = /50x.html {' \
    '        root /usr/share/nginx/html;' \
    '    }' \
    '}' > /etc/nginx/conf.d/default.conf

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD wget -qO- http://localhost:80/ || exit 1

CMD ["nginx", "-g", "daemon off;"]
