-- IP-1: Add params JSONB column to image_jobs
-- Run in the Supabase SQL editor. Existing rows get the default '{}'.
ALTER TABLE image_jobs ADD COLUMN IF NOT EXISTS params JSONB DEFAULT '{}';
