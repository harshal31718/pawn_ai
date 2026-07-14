-- Phase W (imageLab) migration for an already-initialized Postgres volume.
-- postgres/schema.sql only runs on a fresh volume via
-- docker-entrypoint-initdb.d -- local dev and prod both have initialized
-- volumes, so this must be applied manually:
--
--   docker compose exec postgres psql -U <user> -d <db> \
--     -f /path/to/2026-07_image_sessions_stop_requested_at.sql
--
-- Commit 472a170 (2026-07-05) added image_sessions.stop_requested_at to
-- schema.sql (the 'stopping' grace-period check's basis -- see
-- image_session.py) but shipped no migration for it, so any Postgres volume
-- initialized before that date is missing the column: stop_session() then
-- fails with psycopg.errors.UndefinedColumn on every call. Found live
-- 2026-07-14 diagnosing a reported Image Lab local-dev issue.

alter table image_sessions
  add column if not exists stop_requested_at timestamptz;
