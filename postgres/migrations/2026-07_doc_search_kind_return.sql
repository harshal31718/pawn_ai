-- Phase A / A.4 (doc_search) migration for an already-initialized Postgres
-- volume. postgres/schema.sql only runs on a fresh volume via
-- docker-entrypoint-initdb.d — local dev and prod both have initialized
-- volumes, so this must be applied manually:
--
--   docker compose exec postgres psql -U <user> -d <db> \
--     -f /path/to/2026-07_doc_search_kind_return.sql
--
-- match_scoped_chunks/search_scoped_chunks (Phase M) didn't return `kind`/
-- `doc_id` — fine while every row was kind='message', but A.4's doc_search
-- tool needs to know which chunk came from which uploaded document.
-- Postgres requires DROP before CREATE when a function's RETURNS TABLE
-- shape changes (CREATE OR REPLACE can't do it in place). No table/data
-- change — memory_chunks already had kind/doc_id columns since Phase M.

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
