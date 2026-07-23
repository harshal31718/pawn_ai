-- R2: persistent, token-accurate endpoint quota accounting.
--
-- Why this exists:
--   1. app/core/rate_limiter.py held ALL quota state in memory, so every
--      backend restart silently reset every counter. A daily/monthly limit that
--      resets on restart is not a limit -- and once a shared free pool exists
--      (plan Phase 1b), a per-user allowance is a security control, so it must
--      survive restarts to mean anything.
--   2. record_call() accepted a token_count argument and discarded it, so the
--      tpm_limit/tpd_limit values already sitting in data/registry/
--      endpoints.json were registered but never enforced.
--
-- Grain: (user_id, endpoint_id, window_kind, window_start).
--
--   user_id is part of the key because PAWN is BYOK -- each user calls the
--   provider with their OWN key and therefore has their OWN quota. The
--   in-memory limiter keyed on endpoint_id alone, which meant one user's
--   traffic counted against every other user's limit (premature backoff on a
--   multi-user instance). Storing per-user is the correct grain and avoids
--   baking that bug into the database.
--
--   '' (empty string) is the sentinel for unattributed/shared usage -- calls
--   made with no user_id, and later the shared free pool, whose quota really is
--   shared across users. Deliberately NOT a FK to users(user_id): the sentinel
--   is not a real user, and usage history should outlive account deletion for
--   quota-window correctness.
--
-- Only DAY and MONTH windows are persisted. The short rpm/tpm windows stay
-- in-memory: they are ~60s wide, so losing them on restart costs at most one
-- minute of backoff accuracy and is not worth a database write per request.
--
-- postgres/schema.sql only runs on a fresh volume via
-- docker-entrypoint-initdb.d -- local dev and prod both have initialized
-- volumes, so this must be applied manually:
--
--   docker compose exec postgres psql -U <user> -d <db> \
--     -f /path/to/2026-07_R2_endpoint_usage.sql

create table if not exists endpoint_usage (
  user_id      text not null default '',   -- '' = unattributed / shared pool
  endpoint_id  text not null,              -- data/registry/endpoints.json id
  window_kind  text not null,              -- 'day' | 'month'
  window_start date not null,              -- day: the date; month: its 1st
  requests     bigint not null default 0,
  tokens       bigint not null default 0,
  updated_at   timestamptz not null default now(),
  primary key (user_id, endpoint_id, window_kind, window_start),
  constraint endpoint_usage_window_kind_chk check (window_kind in ('day', 'month')),
  constraint endpoint_usage_nonneg_chk check (requests >= 0 and tokens >= 0)
);

-- Startup seeding reads "all rows for the current windows" (see
-- rate_limiter.seed_from_store), and the R3 dashboard aggregates the same way.
create index if not exists endpoint_usage_window_idx
  on endpoint_usage (window_kind, window_start);

-- Per-user dashboard lookups.
create index if not exists endpoint_usage_user_idx
  on endpoint_usage (user_id, window_kind, window_start);
