-- PAWN — self-hosted Postgres schema. Run once via docker-entrypoint-initdb.d,
-- see docker-compose.yml's `postgres` service.
--
-- Application data lives here: user profiles, encrypted Google Drive tokens,
-- encrypted BYOK provider keys, and per-user memory embeddings (pgvector).
-- User conversation/upload content does NOT live here — that goes to each
-- user's own Google Drive.

create extension if not exists vector;
create extension if not exists pgcrypto;  -- gen_random_uuid() (image_sessions/image_jobs PKs)

-- ---------------------------------------------------------------------------
-- Tables
-- ---------------------------------------------------------------------------

create table if not exists users (
  user_id    text primary key,          -- Google OAuth "sub" claim
  email      text unique not null,
  name       text,
  picture    text,
  created_at timestamptz default now()
);

create table if not exists user_drive_tokens (
  user_id           text primary key references users(user_id) on delete cascade,
  access_token_enc  text not null,       -- AES-256-GCM encrypted
  refresh_token_enc text not null,       -- AES-256-GCM encrypted
  expires_at        timestamptz
);

create table if not exists user_api_keys (
  user_id    text references users(user_id) on delete cascade,
  provider   text not null,             -- google | groq | cerebras | huggingface | github | openrouter
  key_enc    text not null,             -- AES-256-GCM encrypted BYOK key
  updated_at timestamptz default now(),
  primary key (user_id, provider)
);

create table if not exists memory_chunks (
  id         bigserial primary key,
  user_id    text references users(user_id) on delete cascade,
  conv_id    text not null,
  text       text not null,
  embedding  vector(768),               -- text-embedding-004 dimensionality
  fts_doc    tsvector generated always as (to_tsvector('english', text)) stored,
  created_at timestamptz default now()
);

create index if not exists memory_chunks_embedding_idx
  on memory_chunks using ivfflat (embedding vector_cosine_ops) with (lists = 10);
create index if not exists memory_chunks_fts_idx
  on memory_chunks using gin (fts_doc);
create index if not exists memory_chunks_user_conv_idx
  on memory_chunks (user_id, conv_id);

-- ---------------------------------------------------------------------------
-- RPC functions used by backend/app/memory/retrieve.py
-- ---------------------------------------------------------------------------

-- Vector similarity search (pgvector cosine), scoped by user, excluding the
-- active conversation. Returns cosine similarity as `score` (1 = identical).
create or replace function match_memory_chunks(
  query_embedding vector(768),
  match_user_id   text,
  exclude_conv_id text,
  match_count     int
)
returns table (id bigint, conv_id text, text text, score float)
language sql stable
as $$
  select
    mc.id,
    mc.conv_id,
    mc.text,
    1 - (mc.embedding <=> query_embedding) as score
  from memory_chunks mc
  where mc.user_id = match_user_id
    and (exclude_conv_id is null or mc.conv_id <> exclude_conv_id)
    and mc.embedding is not null
  order by mc.embedding <=> query_embedding
  limit match_count;
$$;

-- Full-text keyword search (Postgres FTS), scoped by user, excluding the
-- active conversation.
create or replace function search_memory_chunks(
  query_text      text,
  match_user_id   text,
  exclude_conv_id text,
  match_count     int
)
returns table (id bigint, conv_id text, text text)
language sql stable
as $$
  select
    mc.id,
    mc.conv_id,
    mc.text
  from memory_chunks mc
  where mc.user_id = match_user_id
    and (exclude_conv_id is null or mc.conv_id <> exclude_conv_id)
    and mc.fts_doc @@ plainto_tsquery('english', query_text)
  limit match_count;
$$;

-- ---------------------------------------------------------------------------
-- Phase W — Warm/persistent Kaggle image sessions + durable job tracking
-- ---------------------------------------------------------------------------
-- A warm Kaggle kernel is unreachable through Kaggle's batch API once running,
-- so PAWN and the kernel rendezvous here: the backend writes rows directly via
-- its own Postgres connection (superuser/owner role, bypasses RLS), and the
-- kernel reads/writes over HTTPS through the self-hosted PostgREST instance
-- (D.4), which connects to Postgres as the restricted `pawn_anon` role.
--
-- W.0 originally proved the loop with a CPU echo kernel against Supabase's
-- REST API; D.4 replaced Supabase's REST/anon-key layer with self-hosted
-- PostgREST, connecting as `pawn_anon` (created below) instead of Supabase's
-- built-in `anon` role — same PERMISSIVE-policy, single-user-trial posture as
-- before (scoped per-session-JWT auth remains deferred, documented as
-- mandatory before multi-user, unchanged from the original Phase W decision).

create table if not exists image_sessions (
  id            uuid primary key default gen_random_uuid(),
  user_id       text not null,
  model         text not null,                       -- 'sdxl' | 'flux'
  session_token text not null,                       -- random secret the kernel presents
  status        text not null default 'starting',    -- starting | ready | stopping | ended | error
  expires_at    timestamptz not null,                -- the timer; kernel exits past this
  max_images    int,                                 -- optional cap (null = time-only)
  images_done   int not null default 0,
  heartbeat_at  timestamptz,                         -- kernel updates each loop → liveness
  error         text,
  created_at    timestamptz not null default now()
);

create table if not exists image_jobs (
  id          uuid primary key default gen_random_uuid(),
  user_id     text not null,                         -- direct ownership (cold jobs have no session)
  session_id  uuid references image_sessions(id) on delete cascade,  -- NULL = cold one-shot job
  model       text not null,                         -- 'sdxl' | 'flux'
  prompt      text not null,
  status      text not null default 'queued',        -- queued | running | done | error
  image_b64   text,
  mime        text default 'image/png',
  via         text,
  error       text,
  params      jsonb not null default '{}',           -- generation params (steps/guidance/size/...)
  created_at  timestamptz not null default now(),
  started_at  timestamptz,
  done_at     timestamptz
);

create index if not exists image_jobs_user_idx
  on image_jobs (user_id, created_at desc);
create index if not exists image_jobs_session_status_idx
  on image_jobs (session_id, status);

-- pawn_anon role (D.4) — replaces Supabase's built-in `anon` role. NOLOGIN here;
-- a companion init script (postgres/init_pawn_anon.sh, run right after this
-- file by docker-entrypoint-initdb.d) sets its password from the
-- `postgrest_anon_password` secret and grants LOGIN, since a plain .sql file
-- can't read a secret file. PostgREST connects to Postgres as this role.
do $$
begin
  if not exists (select from pg_roles where rolname = 'pawn_anon') then
    create role pawn_anon nologin;
  end if;
end
$$;

grant usage on schema public to pawn_anon;
grant select, insert, update on image_sessions, image_jobs to pawn_anon;

-- RLS + permissive policy for pawn_anon (W.0 single-user-trial fallback; see
-- note above). Same posture as the original Supabase anon-key design: any
-- request authenticated as pawn_anon can touch any row on these two tables
-- only. A scoped per-session-JWT policy remains deferred (documented as
-- mandatory before multi-user).
alter table image_sessions enable row level security;
alter table image_jobs     enable row level security;

drop policy if exists image_sessions_anon_trial on image_sessions;
drop policy if exists image_jobs_anon_trial     on image_jobs;

create policy image_sessions_anon_trial on image_sessions
  for all to pawn_anon using (true) with check (true);
create policy image_jobs_anon_trial on image_jobs
  for all to pawn_anon using (true) with check (true);
