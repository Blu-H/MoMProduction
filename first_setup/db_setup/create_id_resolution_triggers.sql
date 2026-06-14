-- =============================================================================
-- create_id_resolution_triggers.sql
--
-- Sequences for matching_id_station and matching_id_watershed.
-- ID resolution is now handled inside the staging flush functions
-- (fn_stage_glofas_flush, fn_stage_final_alert_flush) where the full
-- metadata columns are available from the staging tables.
--
-- Run AFTER create_all_tables.sql.
-- Run with:
--   sudo -u postgres psql -d postgres -f create_id_resolution_triggers.sql
-- =============================================================================


CREATE SEQUENCE IF NOT EXISTS seq_glofas_station_id START 1;
SELECT setval('seq_glofas_station_id',
    GREATEST(1, COALESCE((SELECT MAX(matching_id_station) FROM all_glofas_stations), 0)));

CREATE SEQUENCE IF NOT EXISTS seq_watershed_id START 1;
SELECT setval('seq_watershed_id',
    GREATEST(1, COALESCE((SELECT MAX(matching_id_watershed) FROM all_watersheds), 0)));


