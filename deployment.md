# PAWN — Deployment Runbook

Deploys PAWN to a Google Cloud **`e2-micro`** VM (Always Free tier,
x86_64, 1 shared vCPU / 1GB RAM), with Postgres+pgvector hosted on
**Supabase's free tier** instead of self-hosted. **Single environment:
`main` → prod only.** `dev` is never deployed here — it stays local-only on
your own machine (its own local Postgres, its own secrets), used to test
changes before promoting.

> **History note:** PAWN originally ran on a dedicated Oracle Cloud
> "Always Free" ARM VM (`pawn`, `144.24.119.184`, 1 OCPU/6GB,
> self-hosted Postgres). Oracle terminated that account/instance on
> 2026-08-30 (involuntary, unrecoverable) — no data survived, since Drive
> is the only place *user* data (conversations, uploads) ever lived;
> Postgres only held accounts/BYOK keys/embeddings, all lost with the VM.
> PAWN was migrated the same day to this GCP + Supabase topology as a
> **fresh deploy**, not a data migration. GCP's `e2-micro` was chosen as
> the most durable "always free" VM offer among major clouds (unchanged
> since ~2017) — still not a contractual guarantee, just the best
> available track record after Oracle proved free tiers can be revoked.
> Supabase was chosen because self-hosting Postgres alongside
> backend+postgrest doesn't fit in 1GB RAM (see §0 resource notes).

| Env | Branch | Domain | Dir | Project | Backend | PostgREST | DB |
|---|---|---|---|---|---|---|---|
| local dev | `dev` | `localhost` | your machine | `docker-compose.yml` (dev) | `127.0.0.1:8001` | n/a | local Postgres |
| **prod** | `main` | `pawnai.duckdns.org` | `/opt/pawn` | GCP `pawn-501409` | `127.0.0.1:8001` | `127.0.0.1:3001` | Supabase `mhrlwflwbhpkbqmmyuus` |

Flow: **verify locally (pytest + build) → `scripts/promote-to-main.sh`
(`dev`→`main`) → SSH to VM → `git pull` → rebuild → `docker compose up` →
validate.**

> **Why no staging box:** PAWN currently has no public user base at
> meaningful scale (the OAuth consent screen is published but the app is
> effectively still in early testing), so the blast radius of skipping a
> dedicated VM staging environment is small. Accepted tradeoff: local dev
> runs on x86, this VM is also x86_64 (unlike the old ARM Oracle box), so
> there's no longer even an architecture mismatch to worry about.

---

## 0. Ground rules

1. **Never bind 80/443 in more than one place.** The host's system Nginx
   owns them and reverse-proxies to PAWN's loopback ports; no container
   publishes 80/443 directly.
2. **Never publish a container port without `127.0.0.1:`**. PAWN's ports:
   `8001` (backend) / `3001` (postgrest). Both loopback-only.
3. **Never `docker compose down -v`**. There's no local Postgres volume to
   destroy anymore (DB is Supabase-hosted), but keep this habit if a local
   debug Postgres is ever added back temporarily.
4. **Prod's DB credentials are Supabase-managed, not shared with dev.**
   Local dev keeps its own local Postgres entirely. `encryption_secret`,
   `jwt_secret` must each be a fresh, independent value on the VM, never
   copied from your local dev machine. (The Google OAuth *client* is the
   one thing that IS shared between local dev and prod — see §1 — just
   two redirect URIs on one client.)
5. **`sudo nginx -t` before every reload.**
6. **Resource-cap PAWN's containers** (already set in
   `docker-compose.prod.yml`) — the box is genuinely small (1 shared
   vCPU / 1GB RAM, `e2-micro`). Current caps: `backend` 500m/0.5cpu,
   `postgrest` 128m/0.1cpu — no local `postgres` container anymore. A
   1GB swapfile (§3.6) absorbs transient spikes; validate with
   `docker stats` after any change to these caps.

---

## 1. Prerequisites (one-time)

- **GCP project**: `pawn-501409` (project name `pawn`), billing account
  linked (a card is required for GCP identity verification — this does
  **not** auto-charge for free-tier-eligible usage; see §7 for what would
  actually trigger billing). A **$1 budget alert** is configured
  (Billing → Budgets & alerts) as an early-warning tripwire.
- **SSH** to the `pawn` VM: static IP `136.114.65.94` (zone
  `us-central1-a`), user `pawndeploy` (passwordless sudo), key at
  `keys/pawn_gcp_vm_ssh_key` (gitignored):
  ```bash
  ssh -i keys/pawn_gcp_vm_ssh_key pawndeploy@136.114.65.94
  ```
- **Dedicated Gmail** for PAWN (`admin.pawnai@gmail.com`) — owns the
  DuckDNS domain and the Google Cloud project.
- **DuckDNS**: `pawnai` → the VM's static IP (`136.114.65.94`). Token
  saved at `keys/duckdns_token.txt`.
  ```bash
  curl "https://www.duckdns.org/update?domains=pawnai&token=<TOKEN>&ip=<NEW_IP>"
  dig +short pawnai.duckdns.org
  ```
- **Google Cloud OAuth client** (Web application, project `pawn-501409`),
  with:
  - **Google Drive API enabled** — Console → APIs & Services → Library →
    "Google Drive API" → Enable. **This is easy to skip and causes a
    silent, hard-to-diagnose failure**: Drive linking will complete
    OAuth successfully and store tokens, but every actual Drive call
    fails with `403 accessNotConfigured`, surfacing to users as "Connect
    your Google Drive in Providers" no matter how many times they
    reconnect. Found live during the first post-migration deploy — verify
    this is enabled before debugging anything else Drive-related.
  - OAuth consent screen configured — **currently Published (In
    production)**, not Testing. See §8's security deferral: this was a
    deliberate choice accepting a known risk, made explicit here so it's
    not silently forgotten.
  - Redirect URI: `https://pawnai.duckdns.org/auth/callback` — same
    client also serves local dev's
    `http://localhost:8001/auth/callback`, if that's still configured.
- **GitHub deploy key** for PAWN's private repo, generated **on the VM
  itself** (not copied from a dev machine) and added as a **read-only**
  deploy key on the repo (Settings → Deploy keys):
  ```bash
  ssh-keygen -t ed25519 -f ~/.ssh/pawn_deploy -N "" -C "pawn-gcp-deploy-key"
  cat ~/.ssh/pawn_deploy.pub   # add as a read-only GitHub deploy key
  ```

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
for good (keeps `README.md`, `deployment.md`, the compose/env-example
files, and all code). **Never** `git merge dev` into `main` directly
afterward — always use this script, or the docs flow back.

Infra-only changes (compose file, this runbook) can be committed directly
to `main` when they don't touch app code — no need to round-trip through
`dev` for those.

---

## 3. VM provisioning (one-time, or when re-provisioning)

### 3.1 Create the `e2-micro` instance

Must match these specs exactly to stay in GCP's Always Free tier:
- Machine type: **`e2-micro`** (not e2-small/e2-medium)
- Region: `us-central1`, `us-west1`, or `us-east1` only (any other region
  bills immediately)
- Boot disk: **Standard persistent disk** (not Balanced/SSD — those
  aren't free), 30GB, Ubuntu 24.04 LTS **x86/64** (the version picker
  sometimes defaults to an arm64 image under the same "24.04 LTS Minimal"
  label — watch for a boot-disk architecture warning at creation time and
  pick the x86/64 variant explicitly)
- Firewall: enable "Allow HTTP traffic" and "Allow HTTPS traffic" at
  creation (adds the `http-server`/`https-server` network tags + matching
  firewall rules)

Reserve a **static external IP** (VPC network → IP addresses → promote
the instance's ephemeral IP to static) — costs $0 while attached to a
running instance, and is what keeps DuckDNS from ever needing a second
update.

Set a **$1 GCP budget alert** right after project creation (Billing →
Budgets & alerts) — free to set up, catches any drift into billable
territory (wrong machine/disk/region, egress over the 1GB/month free
allowance, a detached reserved IP) before it shows up on a bill.

### 3.2 SSH access

The GCP Console's per-instance "SSH Keys" metadata field turned out to be
unreliable in practice (found live during the first deploy: a key pasted
there got silently mangled with a duplicate prefix, and even after
correcting it, the change never actually took effect — `curl`-ing the
instance metadata endpoint from inside the VM showed the same stale/wrong
value long after the Console showed it as saved). **Do not rely on it.**
Working alternative used for this deploy:

1. Use the Console's **browser-based SSH button** (works independently of
   the metadata SSH-keys mechanism — it provisions its own ephemeral
   account) to get an interactive shell once.
2. From that shell, manually create the real deploy user and install your
   public key directly:
   ```bash
   sudo useradd -m -s /bin/bash pawndeploy
   sudo usermod -aG sudo pawndeploy
   sudo mkdir -p /home/pawndeploy/.ssh
   echo "<your ssh-ed25519 public key>" | sudo tee /home/pawndeploy/.ssh/authorized_keys
   sudo chown -R pawndeploy:pawndeploy /home/pawndeploy/.ssh
   sudo chmod 700 /home/pawndeploy/.ssh
   sudo chmod 600 /home/pawndeploy/.ssh/authorized_keys
   echo "pawndeploy ALL=(ALL) NOPASSWD:ALL" | sudo tee /etc/sudoers.d/pawndeploy
   ```
3. Confirm `compute.requireOsLogin` is **Inactive** (both the managed and
   legacy constraint) under IAM & Admin → Organisation policies if
   anything about SSH auth looks broken — this project's default was
   already inactive, but it's the other thing that can silently break
   plain key-based SSH.

### 3.3 Base packages

```bash
# Swapfile — 1GB physical RAM is tight; this absorbs transient spikes
# (apt upgrades, docker build, journald growth) without hard OOM-kills.
sudo fallocate -l 1G /swapfile && sudo chmod 600 /swapfile
sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
sudo sysctl vm.swappiness=10
echo 'vm.swappiness=10' | sudo tee -a /etc/sysctl.conf

# Docker + Compose plugin
sudo apt-get update -qq
sudo apt-get install -y ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg
. /etc/os-release
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $VERSION_CODENAME stable" | sudo tee /etc/apt/sources.list.d/docker.list
sudo apt-get update -qq
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker pawndeploy   # log out/in (new SSH session) for this to take effect

# Nginx, certbot, git, Node 20 (frontend build), psql client (schema/role setup)
sudo apt-get install -y nginx certbot python3-certbot-nginx git postgresql-client
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt-get install -y nodejs
```

No host firewall (`iptables`/`ufw`/`nftables`) exists on this Ubuntu image
by default — unlike Oracle's stock image, there's no host-level
double-gate to configure. GCP's own firewall (opened at instance creation,
§3.1) is the only gate. If a future base image ships one, verify with
`sudo iptables -L INPUT -n --line-numbers` before assuming.

### 3.4 Clone the repo

```bash
sudo mkdir -p /opt/pawn && sudo chown pawndeploy:pawndeploy /opt/pawn
git clone -b main git@github.com:harshal31718/pawn_ai.git /opt/pawn
```
(Uses the `~/.ssh/pawn_deploy` key + matching GitHub deploy key from §1.)

---

## 4. Supabase setup (one-time, or when re-provisioning the DB)

1. Create a **free-tier** Supabase project. **Pick a US region** (e.g.
   East US/North Virginia) matching the GCP VM's `us-central1` — the
   region selector can silently default to a different continent even
   after you think you've changed it; double-check the pooler hostname
   shown in step 4 actually says `us-east-1` (or whichever US region)
   before proceeding, since Supabase doesn't support changing a project's
   region after creation and cross-continent DB latency is a real,
   permanent cost if missed.
2. **Enable pgvector**: Database → Extensions → search "vector" → toggle
   on. Also confirm `pgcrypto` (used for `gen_random_uuid()`) — usually
   enabled by default.
3. **Apply the schema** — no Docker init-script mechanism exists on a
   managed DB, so this is a manual one-time step:
   ```bash
   export PGPASSWORD='<supabase-postgres-superuser-password>'
   psql "postgresql://postgres.<project-ref>@<pooler-host>:5432/postgres?sslmode=require" \
     -f postgres/schema.sql
   ```
4. **Create the app's two roles** (previously bootstrapped automatically
   by the local Postgres container's env vars / init script — no
   equivalent hook on Supabase):
   ```sql
   -- pawn_anon already created by schema.sql; just set its login password:
   alter role pawn_anon with login password '<generated>';

   -- pawn (full-access role the backend connects as) doesn't exist yet:
   create role pawn with login password '<generated>';
   grant all on schema public to pawn;
   grant all on all tables in schema public to pawn;
   grant all on all sequences in schema public to pawn;
   alter default privileges in schema public grant all on tables to pawn;
   alter default privileges in schema public grant all on sequences to pawn;
   ```
5. **Grant both roles USAGE on the `extensions` schema.** Supabase installs
   pgvector into a dedicated `extensions` schema, not `public` (unlike a
   plain self-hosted Postgres, which is what `schema.sql` was originally
   written against). Two separate things are required for the `vector`
   type to actually resolve for these roles — missing either one
   surfaces as `psycopg.ProgrammingError: vector type not found in the
   database`, non-fatal at backend startup but **fatal on every OAuth
   callback** (breaks login with a 500), found live on the first
   post-migration deploy:
   ```sql
   grant usage on schema extensions to pawn;
   grant usage on schema extensions to pawn_anon;
   ```
   ```bash
   # and put extensions on the search_path via the connection string itself
   # (see §5 -- ALTER ROLE ... SET search_path alone is not reliably
   # honored through Supabase's Supavisor session pooler, which appears to
   # reuse pooled backend connections without re-applying role-level
   # session defaults; the DSN-level `options` startup parameter works
   # regardless of pooler internals)
   ```
6. **Connection strings** — use the **Session pooler** (port 5432,
   IPv4-compatible). Supabase's **direct** connection (also port 5432, a
   different host) is **IPv6-only by default**, which a stock GCP VPC
   cannot reach — the **Transaction pooler** (port 6543) can break
   psycopg's session-level assumptions, so Session mode is the correct
   choice, not either alternative. Get the exact pooler hostname from
   Supabase dashboard → Connect → Direct tab → select "Session pooler"
   (this is one of the least discoverable parts of Supabase's UI — the
   default "Connect" panel doesn't show it, and the "Server" tab shows
   JS-SDK setup instructions instead of a raw connection string; you want
   Project Settings-adjacent "Direct" tab's mode selector specifically).

   ```
   # secrets/postgres_dsn (role `pawn`)
   postgresql://pawn.<project-ref>:<pawn-password>@<pooler-host>:5432/postgres?sslmode=require&options=-c%20search_path%3Dpublic%2Cextensions

   # secrets/postgrest_db_uri (role `pawn_anon`)
   postgres://pawn_anon.<project-ref>:<anon-password>@<pooler-host>:5432/postgres?sslmode=require&options=-c%20search_path%3Dpublic%2Cextensions
   ```
   Database name is Supabase's default `postgres` (no separate `pawn`
   database — `schema.sql` doesn't care about the DB name, and creating
   one adds nothing).

No backend code changes were needed for any of this — `config.py` and
`postgres_client.py` read `postgres_dsn` from a Docker secret and pass it
straight to `psycopg.connect()`, so the entire DB swap from self-hosted
to Supabase was a secret-file content change, not application code.

---

## 5. Secrets (freshly generated — prod's OWN set, never copied from dev)

Each secret is a file in `./secrets/<name>` on the VM (gitignored, and
mirrored for reference to `keys/*.txt` in this repo's local checkout —
also gitignored). Generate:
```bash
cd /opt/pawn/secrets
openssl rand -hex 32 > encryption_secret
openssl rand -hex 32 > jwt_secret
# postgres_dsn / postgrest_db_uri: paste the Supabase connection strings from §4.6
# google_client_id / google_client_secret: from the OAuth client in §1
chmod 600 encryption_secret jwt_secret postgres_dsn google_client_id google_client_secret
```

**`postgrest_db_uri` needs a different fix** — this Compose version (the
`docker compose` CLI plugin, not Swarm) silently ignores the
`secrets.mode`/`uid`/`gid` properties entirely (prints a warning, does
nothing). Compose (non-Swarm) bind-mounts the secret file directly rather
than copying it into a root-owned tmpfs, so it keeps its host-side
ownership/permissions inside the container. postgrest's official image
runs as **UID 1000** — the host file must be owned by that UID, not
world-readable:
```bash
sudo chown 1000:1000 /opt/pawn/secrets/postgrest_db_uri
sudo chmod 400 /opt/pawn/secrets/postgrest_db_uri
```
Found live on the first post-migration deploy: `postgrest` crash-looped
with `openFile: permission denied` until this was applied — a plain
`chmod 644` (world-readable) would also fix the symptom but was
deliberately avoided (flagged by this session's own safety tooling) since
it exposes a live Supabase credential to every local user on the box; the
UID-1000-owned, mode-400 file is readable only by the exact process that
needs it.

> No trailing newline matters: `config.py` strips whitespace. Never commit
> these. **Note:** PAWN is BYOK-only — every LLM/search provider key comes
> from each user's own Settings/Providers page (encrypted per-user in
> Supabase), never from a Docker secret. There is no shared/fallback
> provider key file to generate here.

---

## 6. Deploy

### 6.1 Build the frontend static bundle (Nginx serves it)
```bash
cd /opt/pawn/frontend
npm ci
npm run build   # uses committed frontend/.env.production -> frontend/dist
cd /opt/pawn
```
Ran cleanly on the `e2-micro`'s 1GB RAM in practice (~470MB used at peak,
~50MB swap touched) — no special tuning needed for this step.

### 6.2 `.env.prod`
```bash
cp .env.prod.example .env.prod
# defaults already correct: COMPOSE_PROJECT_NAME=pawn, ports 8001/3001,
# pawnai.duckdns.org URLs. Edit only if you changed the domain.
```

### 6.3 Bring up the backend stack
```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d --build
docker compose --env-file .env.prod -f docker-compose.prod.yml ps
curl -fsS http://127.0.0.1:8001/health        # {"status":"ok"}
```
Expect exactly two containers: `backend` and `postgrest` — no local
`postgres` (Supabase-hosted, see §4). Schema is pre-applied to Supabase;
there's no "first boot runs schema.sql" step to wait for.

### 6.4 Nginx server block

Create `/etc/nginx/snippets/security-headers.conf`:
```nginx
add_header X-Frame-Options "DENY" always;
add_header X-Content-Type-Options "nosniff" always;
add_header Referrer-Policy "strict-origin-when-cross-origin" always;
add_header Content-Security-Policy "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self' https://pawnai.duckdns.org" always;
```
`img-src` MUST include `data:` — Image Lab renders fetched job results as
`<img src="data:image/...;base64,...">`, and `default-src 'self'` does
NOT implicitly cover the `data:` scheme.

Create `/etc/nginx/sites-available/pawn`:
```nginx
server {
    listen 80;
    server_name pawnai.duckdns.org;
    root /opt/pawn/frontend/dist;

    # Backend API (root-level routes; no /api prefix). SSE-friendly.
    # "chat" and "projects" are deliberately NOT in this list -- they
    # collide with same-named frontend page routes and get dedicated
    # method/auth-aware blocks below. KEEP THIS IN SYNC with
    # backend/app/routes/*.py's APIRouter prefixes.
    location ~ ^/(health|auth|account|admin|dashboard|generate|conversations|registry|keys|memory|upload|crypto) {
        proxy_pass http://127.0.0.1:8001;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Connection "";
        proxy_buffering off;               # SSE streaming
        proxy_read_timeout 3600s;
    }

    # PostgREST rendezvous for the warm Kaggle kernel. client_max_body_size
    # is REQUIRED here: Nginx defaults to 1m, but the warm kernel PATCHes
    # the finished base64 image back through this path, routinely several MB.
    location /pgrst/ {
        client_max_body_size 20m;
        proxy_pass http://127.0.0.1:3001/;
        proxy_set_header Host $host;
    }

    # /chat collides: POST is the real chat-completion API, GET is the
    # frontend page load. Route by method, not by path alone.
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

    # /chat/:id has no backend route at all -- always the SPA.
    location ~ ^/chat/ {
        include snippets/security-headers.conf;
        try_files $uri /index.html;
    }

    # /projects collides like /chat -- route by method + Authorization header.
    location = /projects {
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
        if ($http_authorization != "") {
            proxy_pass http://127.0.0.1:8001;
        }
        try_files $uri /index.html;
    }

    # /projects/<id>, /projects/<id>/chats/<cid> -- backend API only.
    location ~ ^/projects/ {
        proxy_pass http://127.0.0.1:8001;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Connection "";
        proxy_buffering off;
        proxy_read_timeout 3600s;
    }

    # SPA fallback for everything else (/, /privacy, /imagelab, /settings, ...).
    location / {
        include snippets/security-headers.conf;
        try_files $uri /index.html;
    }
}
```
```bash
sudo ln -sf /etc/nginx/sites-available/pawn /etc/nginx/sites-enabled/pawn
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx
```

### 6.5 TLS
```bash
sudo certbot --nginx -d pawnai.duckdns.org --non-interactive --agree-tos -m admin.pawnai@gmail.com --redirect
sudo nginx -t && sudo systemctl reload nginx
```
Certbot sets up its own auto-renewal scheduled task — no manual cron
needed.

### 6.6 Verify (§9).

---

## 7. Firewall / exposure summary + cost-safety notes

| Port | Bind | Purpose |
|---|---|---|
| 80/443 | public | System Nginx |
| 8001 / 3001 | `127.0.0.1` | PAWN backend / postgrest |
| 5432 | none (external, Supabase-hosted) | DB reached only via the pooler over the internet, not locally |

Only 80/443 are internet-facing on the VM itself. Everything else is
loopback or an outbound connection to Supabase's pooler.

**What could actually trigger GCP billing** (the free tier does not
auto-charge for normal usage, but these would):
- Re-provisioning with the wrong machine type/disk/region (§3.1 specs).
- Network egress over the 1GB/month free allowance — the one
  usage-driven risk; scales with real traffic, watch if usage grows.
- Adding extra resources later (a second VM, snapshots) or detaching the
  reserved static IP from a running instance.

The $1 budget alert from §3.1 is the safety net for all of these.

---

## 8. Known deferrals (carried from earlier phases + new ones)

- **PostgREST is publicly reachable** (via `/pgrst/`) with the permissive
  `pawn_anon` role (SELECT/INSERT/UPDATE on `image_sessions`/`image_jobs`
  only). Scoped per-session JWT is **deferred and MANDATORY before real
  multi-user** — see `postgres/schema.sql` and the Phase W notes.
- **The OAuth consent screen is Published (In production), not
  Testing**, as of the 2026-08-30 migration — a deliberate,
  explicitly-accepted tradeoff to unblock testing, made *while the
  PostgREST scoping gap above was still open*. Any Google account can now
  complete login, and reach the still-unscoped `/pgrst/` endpoint. Close
  the PostgREST scoping gap before this app gets real usage beyond
  personal testing — this combination (public login + unscoped REST
  endpoint) is the actual live risk, not either one alone.
- Client-side encryption of stored data is foundation-only and unwired
  (see `implemented_phases/phase_8_encryption.md` on `dev`).
- **Private/public repo mirror**: if this repo is ever made public, don't
  just flip GitHub visibility on the existing `origin` — rename it to
  `private`, add a separate `public` remote, and only ever
  `git push public main` (already strips workspace docs via
  `scripts/promote-to-main.sh`). Do this **before** the OAuth consent
  screen situation above gets any worse (it already violates the
  original "do this before going public" ordering — see history note at
  the top of this file).
- **Supabase free-tier auto-pause**: the project pauses after 7 days with
  zero API/DB activity; the owner must manually un-pause via the Supabase
  dashboard. A real user hitting the app resets the clock, so this only
  bites during a genuinely idle stretch. Not automated — just know it
  can happen.

---

## 9. Verification checklist

Against `https://pawnai.duckdns.org`:
- [ ] `GET /health` → `{"status":"ok"}` over HTTPS, valid cert.
- [ ] App loads; browser console shows **no CSP violations**.
- [ ] `docker compose ps` shows exactly `backend` + `postgrest` (no local
      `postgres`).
- [ ] Full Google OAuth round-trip (login → callback → logged in).
- [ ] Link Google Drive (Providers page → Google Drive → Connect) →
      `/conversations` and `/projects` return 200, not 412. If they
      return 412 after a successful-looking OAuth consent, check the
      backend logs for `accessNotConfigured` — almost certainly the
      Drive API isn't enabled on the GCP project (§1).
- [ ] Save a BYOK key (Providers page) → a chat streams a real reply over
      SSE.
- [ ] One Kaggle image-gen job (exercises the PostgREST rendezvous via
      `/pgrst/`). Warm session reaches `Warm`; an image returns.
- [ ] `docker stats` + `free -h` / `swapon --show` under light real use —
      caps not OOM-killing, swap not under constant heavy use.

All of the above except the Kaggle image-gen job were verified live
during the 2026-08-30 migration.

---

## 10. Data safety & rollback

- **User conversations/uploads** live in each user's own Google Drive,
  not on the VM or in Supabase — Supabase holds accounts, BYOK keys
  (encrypted), memory embeddings, Drive tokens (encrypted), and
  image-job state.
- **Backup** the Supabase DB before risky schema changes: use Supabase's
  own dashboard backup/export, or `pg_dump` against the pooler connection
  string.
- **Rollback a release**: `git checkout <previous-sha>` in `/opt/pawn`,
  rebuild frontend, `up -d --build`. Since there's no local DB volume,
  code rollbacks never touch data.
- **Never** `docker compose down -v` (moot today with no local volume,
  but keep the habit).

---

## 11. Release / update workflow

`scripts/promote-to-main.sh` + `git push origin main` (§2), then
`cd /opt/pawn && git pull origin main`, rebuild frontend if it changed
(§6.1), and:
```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d --build
```
Schema changes against Supabase: apply SQL manually via `psql` against
the Session pooler connection string (§4.6) or the Supabase SQL editor —
there's no init-script mechanism to run it automatically on a managed DB.

---

## 12. Local-dev PostgREST tunnel — NOT YET RE-ESTABLISHED

The Oracle-era runbook had a §9 documenting an SSH reverse-tunnel through
the prod VM so local dev's Image Lab warm-Kaggle-session feature could
reach a developer's local PostgREST instance (Kaggle can't reach
`localhost`). That mechanism (a restricted `pawn_tunnel_dev` SSH key,
`docker-compose.yml`'s `pgrst-tunnel` service, an `/pgrst-dev/` Nginx
location) has **not been recreated on the new GCP VM** as of this
migration. Local-dev warm-Kaggle-session testing will not work until it
is. Redo it following the same shape as the old setup (dedicated
restricted key generated on the VM, `permitopen="127.0.0.1:3002"` in
`authorized_keys`, a matching `/pgrst-dev/` `location` block in the Nginx
server block above) — the mechanism itself doesn't depend on Oracle vs.
GCP, it just needs to exist again on whichever VM prod is on.
