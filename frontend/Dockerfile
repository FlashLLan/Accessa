# Accessa frontend: Vite build, served by Caddy (HTTPS, /api proxy).
# Built by docker-compose.prod.yml, which mounts deploy/caddy/Caddyfile at
# /etc/caddy/Caddyfile; see DEPLOYMENT.md.

# --- build ---------------------------------------------------------------------------
FROM node:22-alpine AS build
WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
# https://<domain>/api, passed by docker-compose.prod.yml as a build argument.
ARG VITE_API_URL
RUN test -n "$VITE_API_URL" || (echo "VITE_API_URL (https://<domain>/api) must be set" >&2; exit 1)
ENV VITE_API_URL=$VITE_API_URL
RUN npm run build \
 && node scripts/print-csp.js > /app/csp-header.txt

# --- serve ---------------------------------------------------------------------------
FROM caddy:2.10-alpine
COPY --from=build /app/dist /srv
# The same policy as the build's <meta> tag (csp.config.js), sent as a real header
# by the Caddyfile ({$ACCESSA_CSP}).
COPY --from=build /app/csp-header.txt /etc/caddy/csp-header.txt

# Certificates and ACME state live here (docker-compose.prod.yml mounts volumes);
# a new named volume takes this ownership, so Caddy can write as nobody.
ENV XDG_DATA_HOME=/data XDG_CONFIG_HOME=/config
RUN mkdir -p /data/caddy /config/caddy && chown -R nobody:nobody /data /config
USER nobody

CMD ["sh", "-c", "export ACCESSA_CSP=\"$(cat /etc/caddy/csp-header.txt)\" && test -n \"$ACCESSA_CSP\" && exec caddy run --config /etc/caddy/Caddyfile --adapter caddyfile"]
