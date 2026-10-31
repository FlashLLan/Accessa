# Deploying Accessa on a single server (Docker Compose)

One Ubuntu 24.04 server runs everything with `docker-compose.prod.yml`:

```
Internet ──443/80──▶ caddy ──/api/*──▶ backend ──▶ postgres
                     (HTTPS,          (uvicorn,     (no route
                      frontend)        private)      outside)
```

| Service | Image | Published ports | Networks |
|---|---|---|---|
| `caddy` | built from `frontend/` (Vite build + Caddy), config `deploy/caddy/Caddyfile` | **80, 443** (only service) | `app` (fixed IP 172.30.0.10) |
| `backend` | built from the repo root `Dockerfile` | none | `app`, `db` |
| `postgres` | `postgres:16`, volume `pgdata` | none | `db` (internal: no route outside) |

- **HTTPS:** Caddy gets and renews the certificate for `ACCESSA_DOMAIN`. It serves the frontend with SPA fallback, and proxies `/api/*` to the backend with the prefix stripped.
- **Security headers:** the frontend gets the same CSP as `vite.config.js` (including `frame-ancestors 'none'`) plus `nosniff`, `Referrer-Policy: no-referrer` and `X-Frame-Options: DENY`. Every response gets HSTS.
- **Client IP:** Caddy replaces any client-supplied `X-Forwarded-For` with the real address. uvicorn (`--proxy-headers --forwarded-allow-ips=172.30.0.10`) accepts it only from Caddy, so the rate limiter and the audit log see the real client IP.
- **Secrets:** they live only in `.env.production` on the server. The backend never gets `MIGRATION_DATABASE_URL`; migrations are a one-off command (step 4), and the app refuses to start in production if that variable is set.

All commands below run on the server as the deploy user, from the repository
directory, with this alias:

```bash
alias dc='docker compose --env-file .env.production -f docker-compose.prod.yml'
```

---

## 1. Server hardening (Ubuntu 24.04)

Log in as root once (with the provider's console or SSH key), then:

```bash
apt update && apt full-upgrade -y
timedatectl set-timezone UTC

# A sudo user for everything else (pick a strong password; it is used for sudo only).
adduser deploy
usermod -aG sudo deploy

# Copy root's authorized SSH key(s) to the new user.
install -d -m 700 -o deploy -g deploy /home/deploy/.ssh
install -m 600 -o deploy -g deploy /root/.ssh/authorized_keys /home/deploy/.ssh/authorized_keys
```

(If you have no key on the server yet: on your own machine, `ssh-keygen -t ed25519` and
`ssh-copy-id deploy@<server-ip>`.)

**Keep the root session open** and check, in a second terminal, that
`ssh deploy@<server-ip>` works and `sudo -v` succeeds. Only then lock SSH down:

```bash
# 00-* is read first; sshd uses the first value it finds, so this wins over
# Ubuntu's 50-cloud-init.conf (which may enable passwords).
sudo tee /etc/ssh/sshd_config.d/00-hardening.conf > /dev/null <<'EOF'
PermitRootLogin no
PasswordAuthentication no
KbdInteractiveAuthentication no
PubkeyAuthentication yes
EOF
sudo sshd -t && sudo systemctl restart ssh
sudo sshd -T | grep -E '^(permitrootlogin|passwordauthentication|kbdinteractiveauthentication) '
# expected: permitrootlogin no / passwordauthentication no / kbdinteractiveauthentication no
```

Firewall: only SSH, HTTP and HTTPS.

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow OpenSSH          # 22/tcp
sudo ufw allow 80/tcp           # ACME challenge + redirect to HTTPS
sudo ufw allow 443/tcp
sudo ufw allow 443/udp          # HTTP/3
sudo ufw enable
sudo ufw status verbose
```

> **Docker-published ports bypass ufw.** Docker writes its own iptables rules,
> so a port published with `ports:` in a Compose file is reachable from the
> internet even if ufw denies it. That is why **only Caddy publishes ports**
> (80, 443) and PostgreSQL and the backend publish none. Do not add `ports:`
> to them (not even for debugging; use `dc exec` instead).

Automatic security updates:

```bash
sudo apt install -y unattended-upgrades
sudo dpkg-reconfigure -plow unattended-upgrades     # answer "Yes"
cat /etc/apt/apt.conf.d/20auto-upgrades           # both values "1"
# Optional: reboot automatically at night when an update requires it.
echo 'Unattended-Upgrade::Automatic-Reboot "true";
Unattended-Upgrade::Automatic-Reboot-Time "04:30";' | sudo tee /etc/apt/apt.conf.d/52accessa-reboot
```

## 2. Docker

Install Docker Engine and the Compose plugin from Docker's repository
(https://docs.docker.com/engine/install/ubuntu/):

```bash
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin git
sudo usermod -aG docker deploy      # log out and in again; the docker group is root-equivalent
```

## 3. First deployment

1. **Domain.** No DNS of your own needed:
   - **sslip.io:** `accessa.<ip-with-dashes>.sslip.io`, e.g. `accessa.203-0-113-5.sslip.io` for 203.0.113.5. It resolves automatically.
   - **DuckDNS:** a free name such as `accessa.duckdns.org`, pointed at the server's IP.

   Ports 80 and 443 must reach the server for the certificate.
2. **Code:**

   ```bash
   git clone --branch thesis https://github.com/FlashLLan/Accessa.git ~/accessa
   cd ~/accessa
   ```

3. **Secrets:** follow the comments in `.env.production.example`:

   ```bash
   cp .env.production.example .env.production && chmod 600 .env.production
   # generate the secrets (the sed command in the file), then edit:
   nano .env.production     # ACCESSA_DOMAIN, OPENAI_API_KEY (and OPENAI_MODEL, GITHUB_TOKEN)
   ```

   Keep an offline copy of `MFA_ENCRYPTION_KEY` and the three database passwords.
4. **Start.** On the first start PostgreSQL runs `docker/postgres/init/01-roles.sh`, which creates `accessa_owner` (owns the database and schema, **no** CREATEDB) and `accessa_app`:

   ```bash
   dc up -d --build
   dc ps                    # postgres and backend "healthy", caddy "running"
   dc logs caddy | grep -i certificate   # "certificate obtained successfully"
   ```

## 4. Migrations (one-off, as the schema owner)

The owner's credentials are given to a single throwaway container, never to the
running backend:

```bash
OWNER_PW="$(grep '^ACCESSA_OWNER_PASSWORD=' .env.production | cut -d= -f2-)"
dc run --rm -e MIGRATION_DATABASE_URL="postgresql+psycopg://accessa_owner:${OWNER_PW}@postgres:5432/accessa" \
   backend alembic upgrade head
unset OWNER_PW
```

The first time, also create the five roles (junior, mid, senior, lead, admin). This runs as the application role:

```bash
dc exec backend python -m backend.core.seed_roles
```

Migration `5d4a194aa17b` makes `audit_logs` append-only for `accessa_app`
(UPDATE/DELETE/TRUNCATE revoked). Never run `backend.core.seed_admin` or
`scripts/seed_demo.py` in production (`seed_demo.py` refuses non-localhost URLs).

## 5. Check

```bash
D=https://$(grep '^ACCESSA_DOMAIN=' .env.production | cut -d= -f2-)
curl -s $D/api/health                                   # {"status":"ok"}
curl -sI $D/ | grep -iE 'content-security|strict-transport|x-frame|referrer|nosniff'
curl -sI $D/api/health | grep -iE 'content-security|strict-transport'   # default-src 'none'
curl -s -o /dev/null -w '%{http_code}\n' $D/w/anything                 # 200 (SPA fallback)
```

From another machine, PostgreSQL and the backend must be unreachable:
`nc -zv <server-ip> 5432` and `nc -zv <server-ip> 8000` both fail.

**Client IP check.** Run a failed login with fake headers, then look at the newest *Failed Login* entry in the Audit Log (as admin):

```bash
curl -s -X POST $D/api/auth/login -H 'Content-Type: application/json' \
     -H 'X-Forwarded-For: 198.51.100.99' -H 'X-Real-IP: 203.0.113.99' \
     -d '{"workspace_slug":"<slug>","email":"nobody@example.com","password":"x"}'
```

The address shown must be your real public IP, not one of the fake ones.

## 6. First workspace: sign-up

`seed_demo.py` is localhost-only. In production every workspace starts with
the sign-up page:

1. Open `https://<domain>/signup`.
2. Enter the workspace name, its address (slug, e.g. `acme`), your name, e-mail and a password (at least 8 characters). You become the workspace's first admin.
3. **Continue: set up two-factor authentication.** Scan the QR code with an authenticator app (or type the key), then enter the 6-digit code. MFA is mandatory.
4. Share `https://<domain>/w/<slug>` and create your team's accounts under **User Management**. Each person changes the initial password at first login, then sets up MFA.
5. Create a **second admin** early: an admin cannot reset their own MFA, and admin requests need a second admin to approve them.

Sign-up is open to anyone who can reach the page. It can only create a new
workspace, never join an existing one. Restrict it if that is not wanted.

## 7. Updating to a new version

```bash
cd ~/accessa
deploy/backup/backup.sh                     # fresh backup first
git fetch origin && git checkout <branch-or-tag> && git pull --ff-only
dc build                                    # new backend and frontend images
OWNER_PW="$(grep '^ACCESSA_OWNER_PASSWORD=' .env.production | cut -d= -f2-)"
dc run --rm -e MIGRATION_DATABASE_URL="postgresql+psycopg://accessa_owner:${OWNER_PW}@postgres:5432/accessa" \
   backend alembic upgrade head             # migrations with the new image
unset OWNER_PW
dc up -d                                    # replace the running containers
dc ps && curl -s https://<domain>/api/health
docker image prune -f
```

To roll back, check out the previous version, `dc build && dc up -d`. If the
new version ran migrations that the old code cannot handle, restore the backup
taken before the update (section 8).

## 8. Backups

**Daily dump.** `deploy/backup/backup.sh` writes a custom-format `pg_dump` (data,
schema and GRANT/REVOKE rights) to `/var/backups/accessa`, checks that it is
readable, and deletes dumps older than 14 days.

```bash
sudo install -d -m 700 -o deploy -g deploy /var/backups/accessa
deploy/backup/backup.sh                     # first run by hand
crontab -e                                  # as deploy, add:
# 15 3 * * * cd /home/deploy/accessa && deploy/backup/backup.sh >> /var/backups/accessa/backup.log 2>&1
```

A backup on the same server does not survive the loss of the server. Copy the
dumps elsewhere regularly, e.g. from your own machine:
`rsync -a deploy@<server-ip>:/var/backups/accessa/ ./accessa-backups/`.
The dumps contain all data (including encrypted MFA secrets and audit logs):
store them like the secrets.

**Restore test** (after setting up backups, then monthly).
`deploy/backup/restore-test.sh` restores the latest dump into a **throwaway**
container (no network, never the live database). It prints the migration
revision and row counts, and checks that `audit_logs` is still append-only for
`accessa_app`:

```bash
deploy/backup/restore-test.sh            # or: deploy/backup/restore-test.sh /path/to/file.dump
# ... RESTORE TEST OK
```

**Real restore** (disaster recovery, replaces all current data):

```bash
dc stop caddy backend
dc exec -T postgres psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
   -c 'DROP DATABASE accessa WITH (FORCE)' -c 'CREATE DATABASE accessa OWNER accessa_owner' \
   -c 'REVOKE ALL ON DATABASE accessa FROM PUBLIC' -c 'GRANT CONNECT ON DATABASE accessa TO accessa_app'
dc exec -T postgres pg_restore -U postgres -d accessa --exit-on-error --single-transaction \
   < /var/backups/accessa/accessa-<timestamp>.dump
dc start backend caddy
```

Database-level rights are not part of a `pg_dump`, so the recreate step sets
them again (as the init script does). Tables, sequences, schema ownership and
the `audit_logs` restrictions come back with the dump.

On a **new server**, start from a fresh `pgdata` volume with the **same role
passwords** in `.env.production`. The init script then creates the roles, and
the restore above brings back the data and rights.

## Variables reference (`.env.production`)

| Variable | Notes |
|---|---|
| `ACCESSA_DOMAIN` | public hostname; also used for `VITE_API_URL=https://<domain>/api` and `CORS_ORIGINS=https://<domain>` |
| `POSTGRES_PASSWORD` | container superuser; init and maintenance only |
| `ACCESSA_OWNER_PASSWORD` | schema owner; only the one-off migration command |
| `ACCESSA_APP_PASSWORD` | application role |
| `DATABASE_URL` | `postgresql+psycopg://accessa_app:${ACCESSA_APP_PASSWORD}@postgres:5432/accessa` |
| `JWT_SECRET_KEY` | ≥ 32 bytes |
| `MFA_ENCRYPTION_KEY` | Fernet key; keep a backup |
| `OPENAI_API_KEY`, `OPENAI_MODEL` | AI review |
| `GITHUB_TOKEN` | optional, read-only |
| `MIGRATION_DATABASE_URL` | **never** in this file or on the backend; inline in the migration command |

`APP_ENV=production` is set by `docker-compose.prod.yml`.

## Railway (previous setup)

The Railway files (`railway.json`, `frontend/railway.json`,
`scripts/railway_db_roles.sql`, and the defaults in `Dockerfile` /
`frontend/Dockerfile`) are still in the repository. They do not affect this
deployment, because `docker-compose.prod.yml` overrides the start command and
`CLIENT_IP_HEADER`. The Railway instructions are in the git history
(commit `431c272`); that setup is no longer maintained.
