-- =====================================================================
-- 00_run_all.sql  --  builds the whole database from the CSV files.
--
--   Easiest: double-click / run  setup_db.bat  in the project folder.
--   Manually:
--   (use ABSOLUTE paths for -f, datadir and dbdir)
--   psql -U postgres -d olist -v datadir="C:/path/to/Dataset"
--        -v dbdir="C:/path/to/Dataset/olist-dbms/db" -f "C:/path/to/Dataset/olist-dbms/db/00_run_all.sql"
--
-- Takes about 1 minute. Safe to re-run: it drops and rebuilds everything.
-- =====================================================================
\set ON_ERROR_STOP 1
\timing off
\echo [1/8] Schema ...
\ir 01_schema.sql
\echo [2/8] Loading CSV files into staging ...
\ir 02_staging_load.sql
\echo [3/8] Cleaning and loading normalized tables ...
\ir 03_transform.sql
\echo [4/8] Indexes ...
\ir 04_indexes.sql
\echo [5/8] Views and materialized views ...
\ir 05_views.sql
\echo [6/8] Triggers ...
\ir 06_triggers.sql
\echo [7/8] Stored procedures and functions ...
\ir 07_procedures.sql
\echo [8/8] Roles, privileges, row-level security, demo users ...
\ir 08_security.sql
\echo
\echo Done. Next: run the ML training script (see README), then start the web app.
