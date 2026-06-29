-- PAWN — Supabase schema (run once in the Supabase SQL editor).
--
-- Application data lives here: user profiles, encrypted Google Drive tokens,
-- encrypted BYOK provider keys, and per-user memory embeddings (pgvector).
-- User conversation/upload content does NOT live here — that goes to each
-- user's own Google Drive.

create extension if not exists vector;

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
-- so PAWN and the kernel rendezvous here: PAWN writes rows with the service key
-- (bypasses RLS), the kernel reads/writes with the public anon key.
--
-- W.0 (this step) proves the loop with a CPU echo kernel. RLS is intentionally
-- left DISABLED on these two tables for the single-user trial — the anon key has
-- full access (the documented W.0 fallback). W.1 adds the scoped per-session JWT
-- + RLS policies so a kernel can only touch rows of its own session_id; the
-- service key is NEVER injected into the notebook.

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
  created_at  timestamptz not null default now(),
  started_at  timestamptz,
  done_at     timestamptz
);

create index if not exists image_jobs_user_idx
  on image_jobs (user_id, created_at desc);
create index if not exists image_jobs_session_status_idx
  on image_jobs (session_id, status);
