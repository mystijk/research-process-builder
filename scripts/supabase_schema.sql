-- Series A Daily Monitor — Supabase Schema
-- Run this in Supabase SQL Editor to create the table

create table if not exists series_a_discoveries (
  id bigint generated always as identity primary key,
  discovered_date date not null,
  company_name text not null,
  company_domain text,
  amount_raised text,
  round_type text default 'Series A',
  source_url text,
  lead_investors text,
  round_reasoning text,
  discovered_by text,
  source_count integer default 1,
  score integer default 0,
  pipeline_version text default '1.0',
  created_at timestamptz default now(),

  -- Prevent duplicate company on same date
  unique (company_name, discovered_date)
);

-- Index for common queries
create index if not exists idx_series_a_date on series_a_discoveries (discovered_date desc);
create index if not exists idx_series_a_company on series_a_discoveries (company_name);
create index if not exists idx_series_a_domain on series_a_discoveries (company_domain);

-- RLS: enable if needed (disable for server-side inserts via service key)
-- alter table series_a_discoveries enable row level security;
