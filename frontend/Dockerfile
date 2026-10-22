# Accessa frontend for Railway: Vite build, served by Caddy. See DEPLOYMENT.md.

# --- build ---------------------------------------------------------------------------
FROM node:22-alpine AS build
WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
# Railway passes service variables to the build as build arguments.
ARG VITE_API_URL
RUN test -n "$VITE_API_URL" || (echo "VITE_API_URL (the backend's public URL) must be set" >&2; exit 1)
ENV VITE_API_URL=$VITE_API_URL
RUN npm run build \
 && node scripts/print-csp.js > /app/csp-header.txt

# --- serve ---------------------------------------------------------------------------
FROM caddy:2.10-alpine
COPY Caddyfile /etc/caddy/Caddyfile
COPY --from=build /app/dist /srv
# The same policy as the build's <meta> tag (csp.config.js), sent as a real header.
COPY --from=build /app/csp-header.txt /etc/caddy/csp-header.txt

# Caddy only serves files here: no admin API, no TLS (Railway's edge terminates it).
ENV XDG_CONFIG_HOME=/tmp/caddy/config XDG_DATA_HOME=/tmp/caddy/data
USER nobody

CMD ["sh", "-c", "export ACCESSA_CSP=\"$(cat /etc/caddy/csp-header.txt)\" && test -n \"$ACCESSA_CSP\" && exec caddy run --config /etc/caddy/Caddyfile --adapter caddyfile"]
