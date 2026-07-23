-- Login-change plan (2026-07-23): adds password-based login alongside
-- Google OAuth. password_hash is set only on a user's TRUE first insert
-- (see routes/auth.py's callback -- Google re-logins never touch it);
-- password_changed tracks whether the user has replaced the auto-generated
-- password at least once (drives the one-time-per-login nudge popup).
--
-- postgres/schema.sql only runs on a fresh volume via
-- docker-entrypoint-initdb.d -- local dev and prod both have initialized
-- volumes, so this must be applied manually:
--
--   docker compose exec postgres psql -U <user> -d <db> \
--     -f /path/to/2026-07_users_password.sql

alter table users
  add column if not exists password_hash text,
  add column if not exists password_changed boolean not null default false;
