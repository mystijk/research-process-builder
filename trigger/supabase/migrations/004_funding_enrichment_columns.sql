-- Company enrichment columns for funding_discoveries (Blitz/DiscoLike waterfall)
ALTER TABLE funding_discoveries ADD COLUMN IF NOT EXISTS linkedin_url text;
ALTER TABLE funding_discoveries ADD COLUMN IF NOT EXISTS employee_count integer;
ALTER TABLE funding_discoveries ADD COLUMN IF NOT EXISTS employee_range text;
ALTER TABLE funding_discoveries ADD COLUMN IF NOT EXISTS linkedin_followers integer;
ALTER TABLE funding_discoveries ADD COLUMN IF NOT EXISTS company_description text;
ALTER TABLE funding_discoveries ADD COLUMN IF NOT EXISTS founded_year integer;
ALTER TABLE funding_discoveries ADD COLUMN IF NOT EXISTS company_type text;
-- Track which provider filled the row + when, so the retry pass can target NULLs
ALTER TABLE funding_discoveries ADD COLUMN IF NOT EXISTS enriched_by text;
ALTER TABLE funding_discoveries ADD COLUMN IF NOT EXISTS enriched_at timestamptz;

-- Same tracking on product_launches (enrichment data columns already exist via 003)
ALTER TABLE product_launches ADD COLUMN IF NOT EXISTS enriched_by text;
ALTER TABLE product_launches ADD COLUMN IF NOT EXISTS enriched_at timestamptz;
