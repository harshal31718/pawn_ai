# PAWN — Deployment Runbook

Deploys PAWN to its own **dedicated** Oracle Always-Free ARM VM (`pawn`,
reserved public IP, `VM.Standard.A1.Flex`, 1 OCPU/6GB, ARM64, Ubuntu). **Single
environment: `main` → prod only.** `dev` is never deployed here — it stays
local-only on your own machine (its own local Postgres, its own secrets),
used to test changes before promoting. Local dev and prod share the same
Google OAuth client (two redirect URIs registered on it) and the same Google
account(s) for login, but keep **separate** databases/secrets so a local test
can never touch real prod data.

> **History note:** an earlier draft of this runbook assumed PAWN would run
> as a second app sharing Enma's existing VM. That assumption turned out to
> be wrong in practice — Oracle's Always-Free pool is split across separate
> instances, not one shared host — so the first live deploy ran on a
> temporary bridge instance (`pawn-temp`), and PAWN was migrated to its own
> permanent dedicated instance (`pawn`, `144.24.119.184`) once free-tier
> Ampere capacity opened up. `pawn-temp` was terminated after the migration
> was verified. This runbook now reflects that real, dedicated-VM topology —
> there is no other app on this box and no coexistence rules to follow.

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

---

## 0. Ground rules

1. **Never bind 80/443 in more than one place.** The host's system Nginx owns
   them and reverse-proxies to PAWN's loopback ports; no container publishes
   80/443 directly.
2. **Never publish a container port without `127.0.0.1:`**. PAWN's ports:
   `8001` (backend) / `3001` (PostgREST). Both loopback-only.
3. **Never `docker compose down -v`**. `-v` destroys the Postgres volume.
4. **Local dev and prod get SEPARATE database secrets** — `encryption_secret`,
   `jwt_secret`, `postgres_password` must each be a fresh, independent value
   on the VM, never copied from your local dev machine. A shared
   `encryption_secret` would let a compromised dev machine decrypt prod's BYOK
   keys and Drive tokens. (The Google OAuth *client* is the one thing that IS
   shared — see §1.)
5. **`sudo nginx -t` before every reload.**
6. Resource-cap PAWN's containers (already set in `docker-compose.prod.yml`) —
   the box is small (1 OCPU/6GB); don't let one container starve the others.

---

## 1. Prerequisites (one-time)

- **SSH** to the `pawn` VM (reserved public IP `144.24.119.184`).
- **Dedicated Gmail** for PAWN — owns the DuckDNS domain and the Google Cloud
  project.
- **DuckDNS**: `pawnai` → the VM's reserved public IP.
  ```bash
  dig +short pawnai.duckdns.org
  ```
- **Google Cloud OAuth client** (Web application), with the **Drive API
  enabled** and the OAuth consent screen configured (Testing + your
  allowlisted users is fine — do not flip to Production/public until the
  known RLS gap in §9 is closed). This is the **same client local dev already
  uses** — just add the prod redirect URI alongside the existing local one:
  - `http://localhost:8001/auth/callback` (already registered, local dev)
  - `https://pawnai.duckdns.org/auth/callback` (add this one now)

  The redirect URI must match `OAUTH_REDIRECT_URI` exactly for whichever
  environment is making the request.
- **Read-only deploy key** for PAWN's private repo, added to the VM. e.g.
  `~/.ssh/pawn_deploy` + a matching GitHub deploy key.

---

## 2. Verify locally, then promote `dev` → `main`

Before touching the VM, confirm the pre-deploy gate passes on your own
machine: `python -m pytest backend/tests/` (369+ green), `npm run build`
clean in `frontend/`, `docker compose config` valid.

From any clean checkout that has both branches (your dev machine):
```bash
scripts/promote-to-main.sh        # normal merge + strips docs off main
git push origin main
```
This removes `.claude/`, `workspace/`, `CLAUDE.md`, `AGENTS.md` from `main`
for good (keeps `README.md`, `deployment.md`, the compose/env-example files,
and all code). **Never** `git merge dev` into `main` directly afterward —
always use this script, or the docs flow back.

---

## 3. Deploy PROD (`main` → `pawnai.duckdns.org`)

### 3.1 Clone
```bash
sudo mkdir -p /opt/pawn && sudo chown "$USER" /opt/pawn
GIT_SSH_COMMAND='ssh -i ~/.ssh/pawn_deploy' \
  git clone -b main git@github.com:<you>/PAWN.git /opt/pawn
cd /opt/pawn
```

### 3.2 Deploy env file
```bash
cp .env.prod.example .env.prod
# defaults already correct: COMPOSE_PROJECT_NAME=pawn, ports 8001/3001,
# pawnai.duckdns.org URLs. Edit only if you changed the domain.
```

### 3.3 Secrets (freshly generated — prod's OWN set, not copied from dev)
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
cd /opt/pawn
```
> No trailing newline matters: `config.py` strips whitespace. Never commit
> these. **Note:** PAWN is BYOK-only — every LLM/search provider key comes
> from each user's own Settings page (encrypted per-user in Postgres), never
> from a Docker secret. There is no shared/fallback provider key file to
> generate here.

### 3.4 Build the frontend static bundle (Nginx serves it)
```bash
cd /opt/pawn/frontend
npm ci
npm run build   # uses committed frontend/.env.production -> frontend/dist
cd /opt/pawn
```

### 3.5 Bring up the backend stack
```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d --build
docker compose --env-file .env.prod -f docker-compose.prod.yml ps
curl -fsS http://127.0.0.1:8001/health        # {"status":"ok"}
```
First boot runs `postgres/schema.sql` + `init_pawn_anon.sh` on the empty
`pawn_postgres_data` volume (pgvector, `pawn_anon` role, tables).

### 3.6 Open the host firewall for 80/443
The OCI Security List permits 80/443 already, but Oracle's stock Ubuntu image
ships its **host-level** iptables with only SSH (22) allowed for new
connections — everything else hits a default REJECT. Found live on the first
real deploy: Nginx was correctly configured and listening, but every external
request timed out until this was added. Insert the rule before the existing
REJECT line (check `sudo iptables -L INPUT -n --line-numbers` for its number
first — usually 5) and persist it:
```bash
sudo iptables -I INPUT 5 -p tcp -m state --state NEW -m multiport --dports 80,443 -j ACCEPT
sudo apt-get install -y iptables-persistent   # prompts to save current rules — accept
sudo netfilter-persistent save
```

### 3.7 Nginx server block

First, a shared snippet so the security headers (mirroring
`backend/app/middleware/security.py`'s `SecurityHeadersMiddleware`, since
Nginx doesn't inherit headers from proxied routes) don't need copy-pasting
into every SPA-serving location. `img-src` MUST include `data:` — Image Lab
renders fetched job results as `<img src="data:image/...;base64,...">`, and
`default-src 'self'` does NOT implicitly cover the `data:` scheme. Missing
this silently breaks every thumbnail/lightbox with no visible error beyond a
broken image icon. Found live on the first real deploy — keep this file and
`security.py`'s copy in sync if the policy ever changes.

Create `/etc/nginx/snippets/security-headers.conf`:
```nginx
add_header X-Frame-Options "DENY" always;
add_header X-Content-Type-Options "nosniff" always;
add_header Referrer-Policy "strict-origin-when-cross-origin" always;
add_header Content-Security-Policy "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self' https://pawnai.duckdns.org" always;
```

Create `/etc/nginx/sites-available/pawn`:
```nginx
server {
    listen 80;
    server_name pawnai.duckdns.org;
    root /opt/pawn/frontend/dist;

    # Backend API (root-level routes; no /api prefix). SSE-friendly.
    # NOTE: "chat" is deliberately NOT in this list — see the dedicated
    # `location = /chat` block below. Every other name here is exclusively a
    # backend path with no same-named frontend page route, so no collision.
    location ~ ^/(health|auth|generate|conversations|registry|keys|upload|crypto) {
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
    # client_max_body_size is REQUIRED here: Nginx defaults to 1m, but the warm
    # kernel PATCHes the finished base64 image back through this path, which is
    # routinely several MB. Without this, every generation silently gets stuck
    # at "running" forever — the kernel's write-back gets a 413 it doesn't
    # surface anywhere in PAWN's own UI. Found live on the first real deploy.
    location /pgrst/ {
        client_max_body_size 20m;
        proxy_pass http://127.0.0.1:3001/;
        proxy_set_header Host $host;
    }

    # /chat collides: POST is the real chat-completion API, GET is the
    # frontend page load for the chat UI. If "chat" were in the regex above,
    # every hard refresh / bookmarked /chat would 401 (the auth middleware
    # rejects the unauthenticated GET before FastAPI can even 405 it) instead
    # of loading the app. Route by method instead of by path alone. Found
    # live after the landing-page work made direct-URL testing routine.
    # proxy_set_header/proxy_buffering/etc. must live at the location level,
    # not inside `if` — Nginx only permits a handful of directives (proxy_pass
    # among them) inside an `if` block.
    location = /chat {
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Connection "";
        proxy_buffering off;
        proxy_read_timeout 3600s;
        include snippets/security-headers.conf;

        if ($request_method = POST) {
            proxy_pass http://127.0.0.1:8001;
        }
        try_files $uri /index.html;
    }

    # /chat/:id has no backend route at all — always the SPA.
    location ~ ^/chat/ {
        include snippets/security-headers.conf;
        try_files $uri /index.html;
    }

    # SPA fallback for everything else (/, /privacy, /imagelab, /settings, ...).
    location / {
        include snippets/security-headers.conf;
        try_files $uri /index.html;
    }
}
```
```bash
sudo ln -s /etc/nginx/sites-available/pawn /etc/nginx/sites-enabled/pawn
sudo nginx -t && sudo systemctl reload nginx
```

### 3.8 TLS
```bash
sudo certbot --nginx -d pawnai.duckdns.org
sudo nginx -t && sudo systemctl reload nginx
```

### 3.9 Verify prod (§6).

---

## 4. Firewall / exposure summary

| Port | Bind | Purpose |
|---|---|---|
| 80/443 | public | System Nginx |
| 8001 / 3001 | `127.0.0.1` | PAWN backend / PostgREST |
| 3002 | `127.0.0.1` | §9: local-dev PostgREST reverse-SSH tunnel endpoint (`/pgrst-dev/`) |
| 5432 | none | Postgres — internal compose network only |

Only 80/443 are internet-facing. Everything else is loopback; the internet
reaches PAWN solely through Nginx's TLS-terminated routing.

---

## 5. Release / update workflow

`scripts/promote-to-main.sh` + `git push origin main` (§2), then
`cd /opt/pawn && git pull origin main`, rebuild frontend (§3.4), and
`docker compose --env-file .env.prod -f docker-compose.prod.yml up -d --build`.

Schema changes: the init scripts run **only on an empty volume**. For migrations
against an existing DB, apply SQL manually (`docker compose ... exec postgres
psql -U pawn -d pawn`) — never `down -v` to "reset."

---

## 6. Verification checklist

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

---

## 7. Data safety & rollback

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
- **Never** `docker compose down -v`.

---

## 8. Known deferrals (carried from earlier phases)

- **PostgREST is publicly reachable** (via `/pgrst/`) with the permissive
  `pawn_anon` role (SELECT/INSERT/UPDATE on `image_sessions`/`image_jobs`
  only). Scoped per-session JWT is **deferred and MANDATORY before real
  multi-user** — see `postgres/schema.sql` and the Phase W notes. Fine while
  the OAuth consent screen stays in Testing mode with an allowlist; **must be
  closed before ever flipping it to Production/public.**
- Client-side encryption of stored data is foundation-only and unwired (see
  `implemented_phases/phase_8_encryption.md` on `dev`).
- **Private/public repo mirror (chat F-4, parked 2026-07-15/16):** if this repo
  is ever made public, don't just flip GitHub visibility on the existing
  `origin` — rename it to `private`, add a separate `public` remote, and only
  ever `git push public main` (which already strips workspace docs via
  `scripts/promote-to-main.sh`). Do this **before** ever flipping the OAuth
  consent screen to Production/public, same trigger as the PostgREST item
  above.

---

## 9. Local-dev PostgREST tunnel (one-time VM setup)

Local dev's Image Lab warm-Kaggle-session feature needs a running Kaggle
kernel to reach the **developer's local** PostgREST instance (Kaggle can't
reach `localhost`). This VM doubles as a stable, free relay point for that
tunnel via a restricted SSH reverse-forward — **production itself is
completely unaffected**; this section only adds a narrowly-scoped,
reversible piece of infra that local dev tooling uses. Replaces the old
`cloudflared` quick-tunnel (`docker-compose.yml`'s old `cloudflared`
service), which minted a new random hostname on every restart, breaking
any already-running Kaggle kernel and requiring a manual URL update every
time. Do this once; it survives dev-machine restarts, sleep, and network
blips automatically (Docker's `restart: unless-stopped` + ssh's own
keepalive reconnect the tunnel with no URL change ever needed again).

### 9.1 Generate a dedicated key on the VM

Separate from the deploy key (`keys/pawn_oci.key`) — a leaked tunnel key
must never be usable to administer the box, only to forward one port.

```bash
ssh -i keys/pawn_oci.key ubuntu@144.24.119.184
ssh-keygen -t ed25519 -f ~/.ssh/pawn_tunnel_dev -N "" -C "pawn-dev-tunnel"
cat ~/.ssh/pawn_tunnel_dev.pub   # copy this for §9.2
```

Before locking in the port, confirm `3002` is free (nothing already binds
it — prod's own PostgREST uses `3001`):
```bash
ss -tlnp | grep 3002    # expect no output
```

### 9.2 Restrict the key

Append one line to `~/.ssh/authorized_keys`:
```
command="echo 'PAWN dev tunnel only'",no-pty,no-agent-forwarding,no-X11-forwarding,no-user-rc,permitopen="127.0.0.1:3002" ssh-ed25519 AAAA...<pasted pubkey from §9.1>... pawn-dev-tunnel
```
This key can do nothing except open a forward to `127.0.0.1:3002` — no
shell, no other host/port, no agent/X11 forwarding.

### 9.3 New Nginx location

Extend the existing `server {}` block in `/etc/nginx/sites-available/pawn`
(§3.7), alongside the existing `/pgrst/` block — same `client_max_body_size`
fix is REQUIRED here too, same failure mode as prod's own (a warm-session
image PATCH-back is several MB; Nginx's 1m default silently wedges every
dev job at "running" with an unsurfaced 413):
```nginx
    # Dev-only rendezvous: local-dev PostgREST reached via SSH reverse
    # tunnel bound to 127.0.0.1:3002 (docker-compose.yml's pgrst-tunnel
    # service + the restricted authorized_keys entry from §9.2).
    location /pgrst-dev/ {
        client_max_body_size 20m;
        proxy_pass http://127.0.0.1:3002/;
        proxy_set_header Host $host;
    }
```
```bash
sudo nginx -t && sudo systemctl reload nginx
```
No iptables/Security-List change needed — 443 is already open, and this is
just a new `location` on the existing public HTTPS listener.

### 9.4 Move the key to the dev machine

Copy the **private** key (`~/.ssh/pawn_tunnel_dev`) off the VM into this
repo's `secrets/pgrst_tunnel_key` (gitignored — see `secrets/pgrst_tunnel_key.example`
for the expected format), then delete both key files from the VM's home
directory — the VM only ever needs the public half, already in
`authorized_keys`:
```bash
rm ~/.ssh/pawn_tunnel_dev ~/.ssh/pawn_tunnel_dev.pub
```

### 9.5 Start the dev-side tunnel and verify

On the dev machine:
```bash
docker compose --profile tunnel up -d pgrst-tunnel
docker compose logs -f pgrst-tunnel   # watch once for a clean connect
```
Then from the VM:
```bash
ss -tlnp | grep 3002                            # 127.0.0.1:3002 owned by sshd
curl -s https://pawnai.duckdns.org/pgrst-dev/    # PostgREST root JSON via Nginx+TLS
```
Copy `docker-compose.override.yml.example` → `docker-compose.override.yml`
(the fixed URL is already correct in the example) and
`docker compose up -d backend` to pick up the env var. Test end-to-end by
starting a real warm Kaggle session from the Image Lab UI and confirming a
generation completes.
