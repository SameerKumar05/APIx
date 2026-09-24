# ==============================================================================
# APIx Frontend Standalone Dockerfile
# Serves React 19 Vite SPA through optimized Nginx Alpine
# ==============================================================================

FROM oven/bun:1.2-alpine AS builder

WORKDIR /app

COPY package.json bun.lock* ./
RUN bun install --frozen-lockfile

COPY . .
RUN bun run build

FROM nginx:alpine

COPY --from=builder /app/dist /usr/share/nginx/html

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
