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

-- Phase M (memory scoping) — redefined from the original cross-chat-visible
-- design (Step 15 / SM-1). scope_type/scope_id give hard isolation: a chunk
-- is only ever visible to queries within its own scope ('chat', scope_id =
-- conv_id) or ('project', scope_id = project_id). conv_id is retained as
-- provenance (which chat actually wrote the chunk) even inside a project
-- scope. kind/doc_id are pre-provisioned for the follow-on
-- plan_chat_agent_refinement.md's document indexing — Phase M itself only
-- ever writes kind='message'.
drop function if exists match_memory_chunks(vector, text, text, int);
drop function if exists search_memory_chunks(text, text, text, int);
drop table if exists memory_chunks;

create table if not exists memory_chunks (
  id         bigserial primary key,
  chunk_id   uuid not null,              -- matches the Drive rag_chunks.jsonl record; idempotency key
  user_id    text references users(user_id) on delete cascade,
  scope_type text not null,              -- 'chat' | 'project'
  scope_id   text not null,              -- conv_id when 'chat', project_id when 'project'
  conv_id    text not null,              -- originating chat (provenance; = scope_id for 'chat')
  kind       text not null default 'message',  -- 'message' | 'document'
  doc_id     text,                       -- set only when kind='document'
  msg_index  int,
  text       text not null,
  embedding  vector(768),               -- gemini-embedding-2, output_dimensionality=768
  fts_doc    tsvector generated always as (to_tsvector('english', text)) stored,
  created_at timestamptz default now(),
  unique (user_id, chunk_id)
);

create index if not exists memory_chunks_embedding_idx
  on memory_chunks using ivfflat (embedding vector_cosine_ops) with (lists = 10);
create index if not exists memory_chunks_fts_idx
  on memory_chunks using gin (fts_doc);
create index if not exists memory_chunks_scope_idx
  on memory_chunks (user_id, scope_type, scope_id);

-- ---------------------------------------------------------------------------
-- RPC functions used by backend/app/memory/retrieve.py
-- ---------------------------------------------------------------------------

-- Vector similarity search (pgvector cosine), scoped strictly to one
-- (user, scope_type, scope_id) — the inverse of the old exclude-based
-- semantics. No query can ever reach another scope. Returns cosine
-- similarity as `score` (1 = identical). `doc_id`/`kind` returned so callers
-- (Phase A / A.4's doc_search) can label document hits by their source
-- upload — null/`'message'` for chat-turn chunks.
drop function if exists match_scoped_chunks(vector, text, text, text, text, int);
create function match_scoped_chunks(
  query_embedding vector(768),
  match_user_id   text,
  match_scope_type text,
  match_scope_id  text,
  match_kind      text,
  match_count     int
)
returns table (id bigint, conv_id text, text text, score float, kind text, doc_id text)
language sql stable
as $$
  select
    mc.id,
    mc.conv_id,
    mc.text,
    1 - (mc.embedding <=> query_embedding) as score,
    mc.kind,
    mc.doc_id
  from memory_chunks mc
  where mc.user_id = match_user_id
    and mc.scope_type = match_scope_type
    and mc.scope_id = match_scope_id
    and (match_kind is null or mc.kind = match_kind)
    and mc.embedding is not null
  order by mc.embedding <=> query_embedding
  limit match_count;
$$;

-- Full-text keyword search (Postgres FTS), scoped strictly to one
-- (user, scope_type, scope_id).
drop function if exists search_scoped_chunks(text, text, text, text, text, int);
create function search_scoped_chunks(
  query_text      text,
  match_user_id   text,
  match_scope_type text,
  match_scope_id  text,
  match_kind      text,
  match_count     int
)
returns table (id bigint, conv_id text, text text, kind text, doc_id text)
language sql stable
as $$
  select
    mc.id,
    mc.conv_id,
    mc.text,
    mc.kind,
    mc.doc_id
  from memory_chunks mc
  where mc.user_id = match_user_id
    and mc.scope_type = match_scope_type
    and mc.scope_id = match_scope_id
    and (match_kind is null or mc.kind = match_kind)
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
  created_at    timestamptz not null default now(),
  stop_requested_at timestamptz                      -- set when stop_session() is called; the
                                                       -- basis for the 'stopping' grace-period
                                                       -- check (NOT created_at -- see image_session.py)
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

-- RLS scoped by the per-session `session_token` (2026-07-04). Previously any
-- pawn_anon caller could read/write ANY row on these two tables -- since
-- /pgrst/ is a public, unauthenticated-at-the-network-level endpoint, this
-- meant anyone on the internet (no PAWN account needed) could read every
-- user's generated images/prompts or corrupt/hijack any live session or job.
-- session_token was already generated per session and sent to the Kaggle
-- kernel (backend/app/core/image_session.py's start_session payload) but was
-- never actually enforced anywhere until now -- it was inert. The kernel now
-- sends it back as the `X-Session-Token` header on every PostgREST call
-- (see kaggle_templates/image_{sdxl,flux}_session/notebook.ipynb), and these
-- policies require it to match before permitting access to a session's own
-- rows. PostgREST exposes all incoming request headers as a JSON GUC
-- (documented, stable since early v9) -- current_setting('request.headers',
-- true)::json->>'x-session-token'. A full scoped-JWT design remains a
-- possible future upgrade but is no longer required before real multi-user;
-- this closes the same gap with much less new surface.
alter table image_sessions enable row level security;
alter table image_jobs     enable row level security;

drop policy if exists image_sessions_anon_trial on image_sessions;
drop policy if exists image_jobs_anon_trial     on image_jobs;

create or replace function pawn_current_session_token() returns text
language sql stable as $$
  select coalesce(current_setting('request.headers', true)::json->>'x-session-token', '');
$$;

create policy image_sessions_scoped_select on image_sessions
  for select to pawn_anon
  using (session_token = pawn_current_session_token());

create policy image_sessions_scoped_update on image_sessions
  for update to pawn_anon
  using (session_token = pawn_current_session_token())
  with check (session_token = pawn_current_session_token());

create policy image_jobs_scoped_select on image_jobs
  for select to pawn_anon
  using (session_id in (
    select id from image_sessions where session_token = pawn_current_session_token()
  ));

create policy image_jobs_scoped_update on image_jobs
  for update to pawn_anon
  using (session_id in (
    select id from image_sessions where session_token = pawn_current_session_token()
  ))
  with check (session_id in (
    select id from image_sessions where session_token = pawn_current_session_token()
  ));
