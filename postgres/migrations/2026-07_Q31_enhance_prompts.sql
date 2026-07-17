-- imageLab Q3.1 pass 2: wires the vision-grounded prompt enhancer (pass 1)
-- into job creation. Adds the two columns image_jobs needs to persist both
-- the raw user prompt and the enhancer's rewrite, per
-- workspace/plan/imageLab/phase_Q3_prompting_presets.md §3.1.
--
-- postgres/schema.sql only runs on a fresh volume via
-- docker-entrypoint-initdb.d -- local dev and prod both have initialized
-- volumes, so this must be applied manually:
--
--   docker compose exec postgres psql -U <user> -d <db> \
--     -f /path/to/2026-07_Q31_enhance_prompts.sql

alter table image_jobs
  add column if not exists original_prompt text,
  add column if not exists enhanced_prompt text;
