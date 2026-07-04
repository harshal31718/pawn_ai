# PAWN — Deployment Runbook

Deploys PAWN as a **second, fully isolated app** on the existing Oracle
Always-Free ARM VM that already runs **Enma** in production. **Single
environment: `main` → prod only.** `dev` is never deployed here — it stays
local-only on your own machine (its own local Postgres, its own secrets),
used to test changes before promoting. Local dev and prod share the same
Google OAuth client (two redirect URIs registered on it) and the same Google
account(s) for login, but keep **separate** databases/secrets so a local test
can never touch real prod data.

| Env | Branch | Domain | Dir | Project | Backend | PostgREST |
|---|---|---|---|---|---|---|
| local dev | `dev` | `localhost` | your machine | `docker-compose.yml` (dev) | `127.0.0.1:8001` | n/a |
| **prod** | `main` | `pawnai.duckdns.org` | `/opt/pawn` | `pawn` | `127.0.0.1:8001` | `127.0.0.1:3001` |

Flow: **verify locally (pytest + build + live Drive-less 412 check) →
`scripts/promote-to-main.sh` (`dev`→`main`) → deploy prod → validate.**

> **Why no staging box:** PAWN currently has no public user base (the Google
> OAuth consent screen is Testing-mode with an explicit allowlist, not the
> general public), so the blast radius of skipping a dedicated VM staging
> environment is small — the local pre-deploy gate substitutes for it.
> Accepted tradeoff: local dev runs on x86, this VM is ARM64, so any
> ARM-specific issue surfaces here, at the real deploy, for the first time.
> See `workspace/plan/plan_deployment.md` decision 8 for the full rationale.

---

## 0. Hard rules (never break — Enma is live on this box)

1. **Never bind 80/443** in any PAWN container. The host's system Nginx owns
   them; PAWN is reached via a new `server_name` block that reverse-proxies to
   PAWN's loopback ports.
2. **Never edit `/etc/nginx/sites-available/enma`** or Enma's compose/volumes.
   PAWN gets its own Nginx file, its own `/opt/pawn` dir, its own compose
   project.
3. **Never publish a container port without `127.0.0.1:`**. PAWN's ports:
   `8001` (backend) / `3001` (PostgREST). Enma owns `5000`. All loopback-only.
4. **Never reuse Enma's secrets, OAuth client, DB, or `.env`.** PAWN generates
   everything fresh (its own Gmail, its own OAuth client, its own Postgres).
5. **Never `docker compose down -v`** in `/opt/pawn` or `/opt/enma`. `-v`
   destroys the database volume.
6. **Local dev and prod get SEPARATE database secrets** — `encryption_secret`,
   `jwt_secret`, `postgres_password` must each be a fresh, independent value
   on the VM, never copied from your local dev machine. A shared
   `encryption_secret` would let a compromised dev machine decrypt prod's BYOK
   keys and Drive tokens. (The Google OAuth *client* is the one thing that IS
   shared — see §1.)
7. **`sudo nginx -t` before every reload**, and after any PAWN-side Nginx or
   certbot change **re-verify Enma** is still served (§8).
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
  ```bash
  dig +short pawnai.duckdns.org
  ```
- **Google Cloud OAuth client** (Web application) in PAWN's own project, with
  the **Drive API enabled** and the OAuth consent screen configured (Testing +
  your allowlisted users is fine — do not flip to Production/public until the
  known RLS gap in §11 is closed). This is the **same client local dev already
  uses** — just add the prod redirect URI alongside the existing local one:
  - `http://localhost:8001/auth/callback` (already registered, local dev)
  - `https://pawnai.duckdns.org/auth/callback` (add this one now)

  The redirect URI must match `OAUTH_REDIRECT_URI` exactly for whichever
  environment is making the request.
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

## 3. Verify locally, then promote `dev` → `main`

Before touching the VM, confirm the pre-deploy gate passes on your own
machine: `python -m pytest backend/tests/` (152+ green), `npm run build`
clean in `frontend/`, `docker compose config` valid. This is the substitute
for a staging environment — see the note at the top of this file.

From any clean checkout that has both branches (your dev machine):
```bash
scripts/promote-to-main.sh        # normal merge + strips docs off main
git push origin main
```
This is the FIRST run — it removes `.claude/`, `workspace/`, `CLAUDE.md`,
`AGENTS.md` from `main` for good (keeps `README.md`, `deployment.md`, the
compose/env-example files, and all code). **Never** `git merge dev` into `main`
directly afterward — always use this script, or the docs flow back.

---

## 4. Deploy PROD (`main` → `pawnai.duckdns.org`)

### 4.1 Clone
```bash
sudo mkdir -p /opt/pawn && sudo chown "$USER" /opt/pawn
GIT_SSH_COMMAND='ssh -i ~/.ssh/pawn_deploy' \
  git clone -b main git@github.com:<you>/PAWN.git /opt/pawn
cd /opt/pawn
```

### 4.2 Deploy env file
```bash
cp .env.prod.example .env.prod
# defaults already correct: COMPOSE_PROJECT_NAME=pawn, ports 8001/3001,
# pawnai.duckdns.org URLs. Edit only if you changed the domain.
```

### 4.3 Secrets (freshly generated — prod's OWN set, not copied from dev)
Each secret is a file in `./secrets/<name>` (gitignored). Generate:
```bash
cd /opt/pawn/secrets
openssl rand -hex 32 > encryption_secret          # 32-byte hex (AES-256-GCM)
openssl rand -hex 32 > jwt_secret
openssl rand -hex 24 > postgres_password
openssl rand -hex 24 > postgrest_anon_password
PGPW=$(cat postgres_password); ANONPW=$(cat postgrest_anon_password)
printf 'postgresql://pawn:%s@postgres:5432/pawn'      "$PGPW"   > postgres_dsn
printf 'postgres://pawn_anon:%s@postgres:5432/pawn'   "$ANONPW" > postgrest_db_uri
# Google OAuth (same client as local dev — see §1 — just this client's id/secret):
printf '%s' '<GOOGLE_CLIENT_ID>'     > google_client_id
printf '%s' '<GOOGLE_CLIENT_SECRET>' > google_client_secret
# Provider keys (shared app fallback; users add their own via BYOK). Paste real
# keys, or copy from your dev machine. Empty file = that provider only via BYOK.
for p in gemini cerebras groq huggingface github openrouter; do
  printf '%s' '<KEY or empty>' > "${p}_api_key"; done
cd /opt/pawn
```
> No trailing newline matters: `config.py` strips whitespace. Never commit these.

### 4.4 Build the frontend static bundle (Nginx serves it)
```bash
cd /opt/pawn/frontend
npm ci
npm run build   # uses committed frontend/.env.production -> frontend/dist
cd /opt/pawn
```

### 4.5 Bring up the backend stack
```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d --build
docker compose --env-file .env.prod -f docker-compose.prod.yml ps
curl -fsS http://127.0.0.1:8001/health        # {"status":"ok"}
```
First boot runs `postgres/schema.sql` + `init_pawn_anon.sh` on the empty
`pawn_postgres_data` volume (pgvector, `pawn_anon` role, tables).

### 4.6 Nginx server block
Create `/etc/nginx/sites-available/pawn`:
```nginx
server {
    listen 80;
    server_name pawnai.duckdns.org;
    root /opt/pawn/frontend/dist;

    # Backend API (root-level routes; no /api prefix). SSE-friendly.
    location ~ ^/(health|auth|chat|generate|conversations|registry|keys|upload|crypto) {
        proxy_pass http://127.0.0.1:8001;
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
        proxy_pass http://127.0.0.1:3001/;
        proxy_set_header Host $host;
    }

    # SPA fallback.
    location / { try_files $uri /index.html; }
}
```
```bash
sudo ln -s /etc/nginx/sites-available/pawn /etc/nginx/sites-enabled/pawn
sudo nginx -t && sudo systemctl reload nginx
```

### 4.7 TLS (additive — does not touch Enma's cert)
```bash
sudo certbot --nginx -d pawnai.duckdns.org
sudo nginx -t && sudo systemctl reload nginx
```

### 4.8 Verify prod (§9), then re-verify Enma (§10).

---

## 5. Firewall / exposure summary

| Port | Bind | Purpose |
|---|---|---|
| 80/443 | public | System Nginx (Enma + PAWN, by `server_name`) |
| 5000 | `127.0.0.1` | Enma backend — do not touch |
| 8001 / 3001 | `127.0.0.1` | PAWN backend / PostgREST |
| 5432 | none | Postgres — internal compose network only |

Only 80/443 are internet-facing. Everything else is loopback; the internet
reaches PAWN solely through Nginx's TLS-terminated `server_name` routing.

---

## 6. Release / update workflow

`scripts/promote-to-main.sh` + `git push origin main` (§3), then
`cd /opt/pawn && git pull origin main`, rebuild frontend (§4.4), and
`docker compose --env-file .env.prod -f docker-compose.prod.yml up -d --build`.

Schema changes: the init scripts run **only on an empty volume**. For migrations
against an existing DB, apply SQL manually (`docker compose ... exec postgres
psql -U pawn -d pawn`) — never `down -v` to "reset."

---

## 7. Verification checklist

Against `https://pawnai.duckdns.org`:
- [ ] `GET /health` → `{"status":"ok"}` over HTTPS, valid cert.
- [ ] App loads; browser console shows **no CSP violations**.
- [ ] Full Google OAuth round-trip (login → callback → logged in). This is
      also the first real test of the Drive-linked happy path — untestable
      locally without a live OAuth redirect.
- [ ] Link Google Drive; create a conversation → persists to Drive; a
      Drive-less action returns a clean **412**, not a 500.
- [ ] Save a BYOK key (Settings) → a chat streams a real reply over SSE.
- [ ] One Kaggle image-gen job (highest-risk — exercises the PostgREST
      rendezvous via `/pgrst/`). Warm session reaches `Warm`; an image returns.

## 8. Enma safety re-check (after every shared-VM action)

```bash
curl -fsS https://enmaquant.duckdns.org/api/v1/health
docker compose -f /opt/enma/docker-compose.prod.yml ps
dig +short enmaquant.duckdns.org
```
All green + unchanged. If Nginx broke Enma, `sudo nginx -t`, fix the PAWN block,
reload.

---

## 9. Data safety & rollback

- **Backup** PAWN's DB before risky changes:
  ```bash
  docker compose --env-file .env.prod -f docker-compose.prod.yml \
    exec -T postgres pg_dump -U pawn pawn > pawn_prod_$(date +%F).sql
  ```
- **User conversations/uploads** live in each user's own Google Drive, not on
  the VM — the Postgres volume holds accounts, BYOK keys (encrypted), memory
  embeddings, Drive tokens (encrypted), and image-job state.
- **Rollback a release**: `git checkout <previous-sha>` in `/opt/pawn`, rebuild
  frontend, `up -d --build`. The DB volume is untouched by code rollbacks.
- **Never** `docker compose down -v` in either PAWN or Enma directories.

---

## 10. Known deferrals (carried from earlier phases)

- **PostgREST is publicly reachable** (via `/pgrst/`) with the permissive
  `pawn_anon` role (SELECT/INSERT/UPDATE on `image_sessions`/`image_jobs`
  only). Scoped per-session JWT is **deferred and MANDATORY before real
  multi-user** — see `postgres/schema.sql` and the Phase W notes. Fine while
  the OAuth consent screen stays in Testing mode with an allowlist; **must be
  closed before ever flipping it to Production/public.**
- Client-side encryption of stored data is foundation-only and unwired (see
  `implemented_phases/phase_8_encryption.md` on `dev`).
