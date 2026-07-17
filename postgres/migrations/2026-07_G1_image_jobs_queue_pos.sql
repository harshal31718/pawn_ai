-- imageLab G1: adds the nullable queue_pos column image_jobs needs for manual
-- queue reordering (up/down arrows). Dequeue order becomes
-- queue_pos.asc.nullslast,created_at.asc -- untouched rows keep today's plain
-- FIFO-by-created_at behavior. Per
-- workspace/plan/imageLab/phase_G1_generations_management.md §3.1/§4.
--
-- postgres/schema.sql only runs on a fresh volume via
-- docker-entrypoint-initdb.d -- local dev and prod both have initialized
-- volumes, so this must be applied manually:
--
--   docker compose exec postgres psql -U <user> -d <db> \
--     -f /path/to/2026-07_G1_image_jobs_queue_pos.sql

alter table image_jobs
  add column if not exists queue_pos double precision;

create index if not exists image_jobs_queue_pos_idx
  on image_jobs (session_id, queue_pos);
