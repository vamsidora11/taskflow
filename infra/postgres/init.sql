-- Runs once, on first start of an empty data volume.
-- DEV-ONLY placeholder passwords that match .env.example. Phase 1 replaces this with
-- env-driven credentials and the grants/RLS policies described in PLAN.md section 4.
-- The runtime role must never own tables or be a superuser, or RLS is bypassed.
CREATE ROLE owner LOGIN PASSWORD 'change-me-owner';
CREATE ROLE app_user LOGIN PASSWORD 'change-me-app' NOSUPERUSER NOCREATEDB NOCREATEROLE;
