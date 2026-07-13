-- Phase M (memory scoping) migration for an already-initialized Postgres
-- volume. postgres/schema.sql only runs on a fresh volume via
-- docker-entrypoint-initdb.d — local dev and prod both have initialized
-- volumes, so this must be applied manually:
--
--   docker compose exec postgres psql -U <user> -d <db> \
--     -f /path/to/2026-07_memory_scoping.sql
--
-- (or pipe the file in via stdin if it isn't mounted into the container).
-- Forgetting this on prod = retrieval silently broken against missing SQL
-- functions / the old table shape.
--
-- Per plan_memory_scoping.md decision #10: existing memory_chunks data is
-- wiped (drop/recreate), not migrated row-by-row — there is no scope
-- information on old rows to migrate to.

drop function if exists match_memory_chunks(vector, text, text, int);
drop function if exists search_memory_chunks(text, text, text, int);
drop table if exists memory_chunks;

create table memory_chunks (
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
  embedding  vector(768),
  fts_doc    tsvector generated always as (to_tsvector('english', text)) stored,
  created_at timestamptz default now(),
  unique (user_id, chunk_id)
);

create index memory_chunks_embedding_idx
  on memory_chunks using ivfflat (embedding vector_cosine_ops) with (lists = 10);
create index memory_chunks_fts_idx
  on memory_chunks using gin (fts_doc);
create index memory_chunks_scope_idx
  on memory_chunks (user_id, scope_type, scope_id);

create or replace function match_scoped_chunks(
  query_embedding vector(768),
  match_user_id   text,
  match_scope_type text,
  match_scope_id  text,
  match_kind      text,
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
    and mc.scope_type = match_scope_type
    and mc.scope_id = match_scope_id
    and (match_kind is null or mc.kind = match_kind)
    and mc.embedding is not null
  order by mc.embedding <=> query_embedding
  limit match_count;
$$;

create or replace function search_scoped_chunks(
  query_text      text,
  match_user_id   text,
  match_scope_type text,
  match_scope_id  text,
  match_kind      text,
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
    and mc.scope_type = match_scope_type
    and mc.scope_id = match_scope_id
    and (match_kind is null or mc.kind = match_kind)
    and mc.fts_doc @@ plainto_tsquery('english', query_text)
  limit match_count;
$$;
