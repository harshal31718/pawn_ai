# PAWN — Deployment Runbook

Deploys PAWN as a **second, fully isolated app** on the existing Oracle
Always-Free ARM VM that already runs **Enma** in production. Two environments,
**staging first**:

| Env | Branch | Domain | Dir | Project | Backend | PostgREST |
|---|---|---|---|---|---|---|
| **staging** | `dev` | `dev.pawnai.duckdns.org` | `/opt/pawn-dev` | `pawn-dev` | `127.0.0.1:8002` | `127.0.0.1:3002` |
| **prod** | `main` | `pawnai.duckdns.org` | `/opt/pawn` | `pawn` | `127.0.0.1:8001` | `127.0.0.1:3001` |

Flow: **deploy staging → validate the whole runbook → `scripts/promote-to-main.sh`
(`dev`→`main`) → deploy prod → validate.** You prove everything on the
non-critical env before prod exists.

---

## 0. Hard rules (never break — Enma is live on this box)

1. **Never bind 80/443** in any PAWN container. The host's system Nginx owns
   them; PAWN is reached via new `server_name` blocks that reverse-proxy to
   PAWN's loopback ports.
2. **Never edit `/etc/nginx/sites-available/enma`** or Enma's compose/volumes.
   PAWN gets its own Nginx files, its own `/opt/pawn[-dev]` dirs, its own
   compose project.
3. **Never publish a container port without `127.0.0.1:`**. PAWN's ports:
   staging 8002/3002, prod 8001/3001. Enma owns 5000. All loopback-only.
4. **Never reuse Enma's secrets, OAuth client, DB, or `.env`.** PAWN generates
   everything fresh.
5. **Never `docker compose down -v`** in `/opt/pawn`, `/opt/pawn-dev`, or
   `/opt/enma`. `-v` destroys the database volume.
6. **Staging and prod get SEPARATE secrets** — especially `encryption_secret`,
   `jwt_secret`, `postgres_password`. A shared `encryption_secret` would let one
   environment decrypt the other's BYOK keys and Drive tokens.
7. **`sudo nginx -t` before every reload**, and after any PAWN-side Nginx or
   certbot change **re-verify Enma** is still served (§9).
8. Resource-cap PAWN's containers (already set in `docker-compose.prod.yml`) so
   a runaway PAWN can't starve Enma's trading engine.

---

## 1. Prerequisites (one-time)

- **SSH** to the existing `enma-production` VM. No new Oracle account, no new
  instance, no OCI Security List change (80/443 already open; PAWN stays
  loopback-only behind Nginx).
- **Dedicated Gmail** for PAWN (distinct from Enma's) — owns the DuckDNS domain
  and the Google Cloud project.
- **DuckDNS**: register `pawnai` → point it at the VM's reserved public IP.
  DuckDNS wildcard-resolves `dev.pawnai.duckdns.org` to the same IP
  automatically — verify both:
  ```bash
  dig +short pawnai.duckdns.org
  dig +short dev.pawnai.duckdns.org     # should return the SAME IP
  ```
- **Google Cloud OAuth client** (Web application) in PAWN's own project, with
  the **Drive API enabled** and the OAuth consent screen configured (Testing +
  your test users is fine). Add **both** redirect URIs to the one client:
  - `https://pawnai.duckdns.org/auth/callback`
  - `https://dev.pawnai.duckdns.org/auth/callback`

  (A separate client per environment also works; one client with both URIs is
  simpler. The redirect URI must match `OAUTH_REDIRECT_URI` exactly.)
- **Read-only deploy key** for PAWN's private repo, added to the VM (separate
  from Enma's). e.g. `~/.ssh/pawn_deploy` + a matching GitHub deploy key.

---

## 2. Pre-flight — confirm Enma is healthy and the box has headroom

```bash
curl -fsS https://enmaquant.duckdns.org/api/v1/health           # Enma up?
docker compose -f /opt/enma/docker-compose.prod.yml ps           # all Up?
free -h && nproc && df -h /                                       # RAM/CPU/disk headroom
```
Do not proceed if Enma is unhealthy.

---

## 3. Deploy STAGING (`dev` → `dev.pawnai.duckdns.org`)

### 3.1 Clone
```bash
sudo mkdir -p /opt/pawn-dev && sudo chown "$USER" /opt/pawn-dev
GIT_SSH_COMMAND='ssh -i ~/.ssh/pawn_deploy' \
  git clone -b dev git@github.com:<you>/PAWN.git /opt/pawn-dev
cd /opt/pawn-dev
```

### 3.2 Deploy env file
```bash
cp .env.staging.example .env.staging
# defaults already correct: COMPOSE_PROJECT_NAME=pawn-dev, ports 8002/3002,
# dev.pawnai.duckdns.org URLs. Edit only if you changed the domain.
```

### 3.3 Secrets (freshly generated — staging's OWN set)
Each secret is a file in `./secrets/<name>` (gitignored). Generate:
```bash
cd /opt/pawn-dev/secrets
openssl rand -hex 32 > encryption_secret          # 32-byte hex (AES-256-GCM)
openssl rand -hex 32 > jwt_secret
openssl rand -hex 24 > postgres_password
openssl rand -hex 24 > postgrest_anon_password
PGPW=$(cat postgres_password); ANONPW=$(cat postgrest_anon_password)
printf 'postgresql://pawn:%s@postgres:5432/pawn'      "$PGPW"   > postgres_dsn
printf 'postgres://pawn_anon:%s@postgres:5432/pawn'   "$ANONPW" > postgrest_db_uri
# Google OAuth (from your OAuth client):
printf '%s' '<GOOGLE_CLIENT_ID>'     > google_client_id
printf '%s' '<GOOGLE_CLIENT_SECRET>' > google_client_secret
# Provider keys (shared app fallback; users add their own via BYOK). Paste real
# keys, or copy from your dev machine. Empty file = that provider only via BYOK.
for p in gemini cerebras groq huggingface github openrouter; do
  printf '%s' '<KEY or empty>' > "${p}_api_key"; done
cd /opt/pawn-dev
```
> No trailing newline matters: `config.py` strips whitespace. Never commit these.

### 3.4 Build the frontend static bundle (Nginx serves it)
```bash
cd /opt/pawn-dev/frontend
npm ci
VITE_API_URL=https://dev.pawnai.duckdns.org npm run build   # -> frontend/dist
cd /opt/pawn-dev
```

### 3.5 Bring up the backend stack
```bash
docker compose --env-file .env.staging -f docker-compose.prod.yml up -d --build
docker compose --env-file .env.staging -f docker-compose.prod.yml ps
curl -fsS http://127.0.0.1:8002/health        # {"status":"ok"}
```
First boot runs `postgres/schema.sql` + `init_pawn_anon.sh` on the empty
`pawn-dev_postgres_data` volume (pgvector, `pawn_anon` role, tables).

### 3.6 Nginx server block
Create `/etc/nginx/sites-available/pawn-dev`:
```nginx
server {
    listen 80;
    server_name dev.pawnai.duckdns.org;
    root /opt/pawn-dev/frontend/dist;

    # Backend API (root-level routes; no /api prefix). SSE-friendly.
    location ~ ^/(health|auth|chat|generate|conversations|registry|keys|upload|crypto) {
        proxy_pass http://127.0.0.1:8002;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Connection "";
        proxy_buffering off;               # SSE streaming
        proxy_read_timeout 3600s;
    }

    # PostgREST rendezvous for the warm Kaggle kernel (trailing slash strips prefix).
    location /pgrst/ {
        proxy_pass http://127.0.0.1:3002/;
        proxy_set_header Host $host;
    }

    # SPA fallback.
    location / { try_files $uri /index.html; }
}
```
```bash
sudo ln -s /etc/nginx/sites-available/pawn-dev /etc/nginx/sites-enabled/pawn-dev
sudo nginx -t && sudo systemctl reload nginx
```

### 3.7 TLS (additive — does not touch Enma's cert)
```bash
sudo certbot --nginx -d dev.pawnai.duckdns.org
sudo nginx -t && sudo systemctl reload nginx
```

### 3.8 Verify staging (§8), then re-verify Enma (§9).

---

## 4. Promote `dev` → `main`

Only after staging fully passes §8. From any clean checkout that has both
branches (your dev machine, or `/opt/pawn-dev` after `git fetch`):
```bash
scripts/promote-to-main.sh        # normal merge + strips docs off main
git push origin main
```
This is the FIRST run — it removes `.claude/`, `workspace/`, `CLAUDE.md`,
`AGENTS.md` from `main` for good (keeps `README.md`, `deployment.md`, the
compose/env-example files, and all code). **Never** `git merge dev` into `main`
directly afterward — always use this script, or the docs flow back.

---

## 5. Deploy PROD (`main` → `pawnai.duckdns.org`)

Identical to §3 with the prod values. Clone `main` into `/opt/pawn`:
```bash
sudo mkdir -p /opt/pawn && sudo chown "$USER" /opt/pawn
GIT_SSH_COMMAND='ssh -i ~/.ssh/pawn_deploy' \
  git clone -b main git@github.com:<you>/PAWN.git /opt/pawn
cd /opt/pawn
cp .env.prod.example .env.prod                          # ports 8001/3001, prod URLs
# §3.3 secrets — generate a SEPARATE set in /opt/pawn/secrets (NOT copied from staging)
cd frontend && npm ci && npm run build && cd ..         # uses frontend/.env.production
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d --build
curl -fsS http://127.0.0.1:8001/health
```
Nginx block `/etc/nginx/sites-available/pawn` — same as §3.6 but
`server_name pawnai.duckdns.org`, `root /opt/pawn/frontend/dist`, and ports
`8001` / `3001`. Then:
```bash
sudo ln -s /etc/nginx/sites-available/pawn /etc/nginx/sites-enabled/pawn
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d pawnai.duckdns.org
```
Verify prod (§8), then re-verify Enma (§9).

---

## 6. Firewall / exposure summary

| Port | Bind | Purpose |
|---|---|---|
| 80/443 | public | System Nginx (Enma + both PAWN blocks by `server_name`) |
| 5000 | `127.0.0.1` | Enma backend — do not touch |
| 8001 / 3001 | `127.0.0.1` | PAWN prod backend / PostgREST |
| 8002 / 3002 | `127.0.0.1` | PAWN staging backend / PostgREST |
| 5432 | none | Postgres — internal compose network only |

Only 80/443 are internet-facing. Everything else is loopback; the internet
reaches PAWN solely through Nginx's TLS-terminated `server_name` routing.

---

## 7. Release / update workflow

**Staging** (frequent): `cd /opt/pawn-dev && git pull origin dev`, rebuild
frontend (§3.4), then
`docker compose --env-file .env.staging -f docker-compose.prod.yml up -d --build`.

**Prod**: run `scripts/promote-to-main.sh` + `git push origin main` (§4), then
`cd /opt/pawn && git pull origin main`, rebuild frontend, and
`docker compose --env-file .env.prod -f docker-compose.prod.yml up -d --build`.

Schema changes: the init scripts run **only on an empty volume**. For migrations
against an existing DB, apply SQL manually (`docker compose ... exec postgres
psql -U pawn -d pawn`) — never `down -v` to "reset."

---

## 8. Per-environment verification checklist

Against the env's own HTTPS domain:
- [ ] `GET /health` → `{"status":"ok"}` over HTTPS, valid cert.
- [ ] App loads; browser console shows **no CSP violations**.
- [ ] Full Google OAuth round-trip (login → callback → logged in).
- [ ] Link Google Drive; create a conversation → persists to Drive; a
      Drive-less action returns a clean **412**, not a 500.
- [ ] Save a BYOK key (Settings) → a chat streams a real reply over SSE.
- [ ] One Kaggle image-gen job (highest-risk — exercises the PostgREST
      rendezvous via `/pgrst/`). Warm session reaches `Warm`; an image returns.

## 9. Enma safety re-check (after every shared-VM action)

```bash
curl -fsS https://enmaquant.duckdns.org/api/v1/health
docker compose -f /opt/enma/docker-compose.prod.yml ps
dig +short enmaquant.duckdns.org
```
All green + unchanged. If Nginx broke Enma, `sudo nginx -t`, fix the PAWN block,
reload.

---

## 10. Data safety & rollback

- **Backup** PAWN's DB before risky changes:
  ```bash
  docker compose --env-file .env.prod -f docker-compose.prod.yml \
    exec -T postgres pg_dump -U pawn pawn > pawn_prod_$(date +%F).sql
  ```
- **User conversations/uploads** live in each user's own Google Drive, not on
  the VM — the Postgres volume holds accounts, BYOK keys (encrypted), memory
  embeddings, Drive tokens (encrypted), and image-job state.
- **Rollback a release**: `git checkout <previous-sha>` in the env dir, rebuild
  frontend, `up -d --build`. The DB volume is untouched by code rollbacks.
- **Never** `docker compose down -v` in any PAWN or Enma directory.

---

## Known deferrals (carried from earlier phases)

- **PostgREST is publicly reachable** (via `/pgrst/`) with the permissive
  `pawn_anon` role (SELECT/INSERT/UPDATE on `image_sessions`/`image_jobs`
  only). Scoped per-session JWT is **deferred and MANDATORY before real
  multi-user** — see `postgres/schema.sql` and the Phase W notes. Fine for the
  single-user trial.
- Client-side encryption of stored data is foundation-only and unwired (see
  `implemented_phases/phase_8_encryption.md` on `dev`).
