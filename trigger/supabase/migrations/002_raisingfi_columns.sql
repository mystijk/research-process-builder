-- Add columns needed by RaisingFi ingest
ALTER TABLE funding_discoveries ADD COLUMN IF NOT EXISTS industry text;
ALTER TABLE funding_discoveries ADD COLUMN IF NOT EXISTS location text;
