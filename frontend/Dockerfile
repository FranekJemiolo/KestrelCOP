# -----------------------------------------------------------------------------
# KestrelCOP Tactical React PWA Dashboard Dockerfile
# Multi-stage production build served via lightweight Nginx Alpine
# -----------------------------------------------------------------------------

FROM node:24-alpine AS builder

WORKDIR /app

COPY package*.json ./
RUN npm ci

COPY . .
RUN npm run build

# -----------------------------------------------------------------------------
# Runtime Web Server
# -----------------------------------------------------------------------------
FROM nginx:1.27-alpine

COPY --from=builder /app/dist /usr/share/nginx/html

# Custom tactical nginx configuration for SPA routing and offline caching
RUN echo 'server { \
    listen 80; \
    server_name localhost; \
    location / { \
        root /usr/share/nginx/html; \
        index index.html; \
        try_files $uri $uri/ /index.html; \
    } \
    location /ws { \
        proxy_pass http://kestrel-collector:8080/ws; \
        proxy_http_version 1.1; \
        proxy_set_header Upgrade $http_upgrade; \
        proxy_set_header Connection "Upgrade"; \
    } \
    location /api/ { \
        proxy_pass http://kestrel-collector:8080/api/; \
    } \
}' > /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
