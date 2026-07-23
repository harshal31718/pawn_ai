-- PAWN 2.0 Phase B.2: operator-owned shared pool keys, admin-editable live
-- (no restart needed -- see core/pool_key_store.py's TTL cache + explicit
-- eviction on write). Docker-secret pool keys (Phase 1b) become an optional
-- bootstrap fallback once B.4 wires read_pool_key() to check this table first.
--
-- postgres/schema.sql only runs on a fresh volume via
-- docker-entrypoint-initdb.d -- local dev and prod both have initialized
-- volumes, so this must be applied manually:
--
--   docker compose exec postgres psql -U <user> -d <db> \
--     -f /path/to/2026-07_pool_api_keys.sql

create table if not exists pool_api_keys (
  provider       text primary key,
  key_enc        text not null,
  enabled        boolean not null default true,
  saturation_pct int,
  updated_at     timestamptz default now()
);
