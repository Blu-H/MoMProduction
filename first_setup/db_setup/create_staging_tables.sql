-- =============================================================================
-- create_staging_tables.sql
--
-- Staging tables are the user-facing entry point for all data ingestion.
-- Insert data here — the trigger handles everything else:
--
--   < 1 row      → batch is discarded, nothing touches _latest or history
--   timestamp already in history → batch is discarded (idempotent re-run guard)
--   otherwise    → data is pushed to the corresponding _latest table,
--                  which fires the history and ID-resolution triggers
--
-- Staging tables have no PK/FK constraints so inserts never fail on conflicts.
-- For GloFAS and Final Alert, omit matching_id — it is resolved automatically
-- inside the flush function before data is written to the _latest table.
--
-- Run AFTER create_all_tables.sql, create_id_resolution_triggers.sql,
-- and create_history_triggers.sql.
--
-- Run with:
--   sudo -u postgres psql -d postgres -f create_staging_tables.sql
-- =============================================================================


-- =============================================================================
-- GFMS
-- =============================================================================

CREATE TABLE IF NOT EXISTS stage_gfms (
    pfaf_id              INTEGER,
    "timestamp"          TIMESTAMPTZ,
    "GFMS_TotalArea_km"  DOUBLE PRECISION,
    "GFMS_perc_Area"     DOUBLE PRECISION,
    "GFMS_MeanDepth"     DOUBLE PRECISION,
    "GFMS_MaxDepth"      DOUBLE PRECISION,
    "GFMS_Duration"      INTEGER
);

CREATE OR REPLACE FUNCTION fn_stage_gfms_flush()
RETURNS TRIGGER LANGUAGE plpgsql SECURITY DEFINER AS $$
DECLARE
    rc             INTEGER;
    batch_ts       TIMESTAMPTZ;
    hist_count     INTEGER;
    expected_count INTEGER;
BEGIN
    SELECT COUNT(*), MAX("timestamp") INTO rc, batch_ts FROM new_rows;

    IF rc < 1 THEN
        DELETE FROM stage_gfms;
        RETURN NULL;
    END IF;

    expected_count := COALESCE(NULLIF(current_setting('mom.expected_rows', true), '')::INTEGER, rc);

    SELECT COUNT(*) INTO hist_count FROM summary_gfms WHERE "timestamp" = batch_ts;

    IF hist_count >= expected_count THEN
        DELETE FROM stage_gfms;
        RETURN NULL;
    END IF;

    IF hist_count > 0 THEN
        DELETE FROM summary_gfms WHERE "timestamp" = batch_ts;
    END IF;

    DELETE FROM summary_gfms_latest;

    INSERT INTO summary_gfms_latest (
        pfaf_id, "timestamp",
        "GFMS_TotalArea_km", "GFMS_perc_Area",
        "GFMS_MeanDepth", "GFMS_MaxDepth", "GFMS_Duration"
    )
    SELECT
        pfaf_id, "timestamp",
        "GFMS_TotalArea_km", "GFMS_perc_Area",
        "GFMS_MeanDepth", "GFMS_MaxDepth", "GFMS_Duration"
    FROM stage_gfms;

    DELETE FROM stage_gfms;
    RETURN NULL;
END;
$$;

CREATE TRIGGER trg_stage_gfms_flush
AFTER INSERT ON stage_gfms
REFERENCING NEW TABLE AS new_rows
FOR EACH STATEMENT EXECUTE FUNCTION fn_stage_gfms_flush();


-- =============================================================================
-- HWRF
-- =============================================================================

CREATE TABLE IF NOT EXISTS stage_hwrf (
    pfaf_id              INTEGER,
    "timestamp"          TIMESTAMPTZ,
    "Rain_TotalArea_km"  DOUBLE PRECISION,
    "perc_Area"          DOUBLE PRECISION,
    "MeanRain"           DOUBLE PRECISION,
    "MaxRain"            DOUBLE PRECISION
);

CREATE OR REPLACE FUNCTION fn_stage_hwrf_flush()
RETURNS TRIGGER LANGUAGE plpgsql SECURITY DEFINER AS $$
DECLARE
    rc             INTEGER;
    batch_ts       TIMESTAMPTZ;
    hist_count     INTEGER;
    expected_count INTEGER;
BEGIN
    SELECT COUNT(*), MAX("timestamp") INTO rc, batch_ts FROM new_rows;

    IF rc < 1 THEN
        DELETE FROM stage_hwrf;
        RETURN NULL;
    END IF;

    expected_count := COALESCE(NULLIF(current_setting('mom.expected_rows', true), '')::INTEGER, rc);

    SELECT COUNT(*) INTO hist_count FROM summary_hwrf WHERE "timestamp" = batch_ts;

    IF hist_count >= expected_count THEN
        DELETE FROM stage_hwrf;
        RETURN NULL;
    END IF;

    IF hist_count > 0 THEN
        DELETE FROM summary_hwrf WHERE "timestamp" = batch_ts;
    END IF;

    DELETE FROM summary_hwrf_latest;

    INSERT INTO summary_hwrf_latest (
        pfaf_id, "timestamp",
        "Rain_TotalArea_km", "perc_Area", "MeanRain", "MaxRain"
    )
    SELECT
        pfaf_id, "timestamp",
        "Rain_TotalArea_km", "perc_Area", "MeanRain", "MaxRain"
    FROM stage_hwrf;

    DELETE FROM stage_hwrf;
    RETURN NULL;
END;
$$;

CREATE TRIGGER trg_stage_hwrf_flush
AFTER INSERT ON stage_hwrf
REFERENCING NEW TABLE AS new_rows
FOR EACH STATEMENT EXECUTE FUNCTION fn_stage_hwrf_flush();


-- =============================================================================
-- VIIRS
-- =============================================================================

CREATE TABLE IF NOT EXISTS stage_viirs (
    pfaf_id                  INTEGER,
    "timestamp"              TIMESTAMPTZ,
    "onedayFlood_Area_km"    DOUBLE PRECISION,
    "onedayperc_Area"        DOUBLE PRECISION,
    "fivedayFlood_Area_km"   DOUBLE PRECISION,
    "fivedayperc_Area"       DOUBLE PRECISION
);

CREATE OR REPLACE FUNCTION fn_stage_viirs_flush()
RETURNS TRIGGER LANGUAGE plpgsql SECURITY DEFINER AS $$
DECLARE
    rc             INTEGER;
    batch_ts       TIMESTAMPTZ;
    hist_count     INTEGER;
    expected_count INTEGER;
BEGIN
    SELECT COUNT(*), MAX("timestamp") INTO rc, batch_ts FROM new_rows;

    IF rc < 1 THEN
        DELETE FROM stage_viirs;
        RETURN NULL;
    END IF;

    expected_count := COALESCE(NULLIF(current_setting('mom.expected_rows', true), '')::INTEGER, rc);

    SELECT COUNT(*) INTO hist_count FROM summary_viirs WHERE "timestamp" = batch_ts;

    IF hist_count >= expected_count THEN
        DELETE FROM stage_viirs;
        RETURN NULL;
    END IF;

    IF hist_count > 0 THEN
        DELETE FROM summary_viirs WHERE "timestamp" = batch_ts;
    END IF;

    DELETE FROM summary_viirs_latest;

    INSERT INTO summary_viirs_latest (
        pfaf_id, "timestamp",
        "onedayFlood_Area_km", "onedayperc_Area",
        "fivedayFlood_Area_km", "fivedayperc_Area"
    )
    SELECT
        pfaf_id, "timestamp",
        "onedayFlood_Area_km", "onedayperc_Area",
        "fivedayFlood_Area_km", "fivedayperc_Area"
    FROM stage_viirs;

    DELETE FROM stage_viirs;
    RETURN NULL;
END;
$$;

CREATE TRIGGER trg_stage_viirs_flush
AFTER INSERT ON stage_viirs
REFERENCING NEW TABLE AS new_rows
FOR EACH STATEMENT EXECUTE FUNCTION fn_stage_viirs_flush();


-- =============================================================================
-- DFO
-- =============================================================================

CREATE TABLE IF NOT EXISTS stage_dfo (
    pfaf_id                   INTEGER,
    "timestamp"               TIMESTAMPTZ,
    "1-Day_TotalArea_km2"     DOUBLE PRECISION,
    "1-Day_perc_Area"         DOUBLE PRECISION,
    "1-Day_CS_TotalArea_km2"  DOUBLE PRECISION,
    "1-Day_CS_perc_Area"      DOUBLE PRECISION,
    "2-Day_TotalArea_km2"     DOUBLE PRECISION,
    "2-Day_perc_Area"         DOUBLE PRECISION,
    "3-Day_TotalArea_km2"     DOUBLE PRECISION,
    "3-Day_perc_Area"         DOUBLE PRECISION
);

CREATE OR REPLACE FUNCTION fn_stage_dfo_flush()
RETURNS TRIGGER LANGUAGE plpgsql SECURITY DEFINER AS $$
DECLARE
    rc             INTEGER;
    batch_ts       TIMESTAMPTZ;
    hist_count     INTEGER;
    expected_count INTEGER;
BEGIN
    SELECT COUNT(*), MAX("timestamp") INTO rc, batch_ts FROM new_rows;

    IF rc < 1 THEN
        DELETE FROM stage_dfo;
        RETURN NULL;
    END IF;

    expected_count := COALESCE(NULLIF(current_setting('mom.expected_rows', true), '')::INTEGER, rc);

    SELECT COUNT(*) INTO hist_count FROM summary_dfo WHERE "timestamp" = batch_ts;

    IF hist_count >= expected_count THEN
        DELETE FROM stage_dfo;
        RETURN NULL;
    END IF;

    IF hist_count > 0 THEN
        DELETE FROM summary_dfo WHERE "timestamp" = batch_ts;
    END IF;

    DELETE FROM summary_dfo_latest;

    INSERT INTO summary_dfo_latest (
        pfaf_id, "timestamp",
        "1-Day_TotalArea_km2", "1-Day_perc_Area",
        "1-Day_CS_TotalArea_km2", "1-Day_CS_perc_Area",
        "2-Day_TotalArea_km2", "2-Day_perc_Area",
        "3-Day_TotalArea_km2", "3-Day_perc_Area"
    )
    SELECT
        pfaf_id, "timestamp",
        "1-Day_TotalArea_km2", "1-Day_perc_Area",
        "1-Day_CS_TotalArea_km2", "1-Day_CS_perc_Area",
        "2-Day_TotalArea_km2", "2-Day_perc_Area",
        "3-Day_TotalArea_km2", "3-Day_perc_Area"
    FROM stage_dfo;

    DELETE FROM stage_dfo;
    RETURN NULL;
END;
$$;

CREATE TRIGGER trg_stage_dfo_flush
AFTER INSERT ON stage_dfo
REFERENCING NEW TABLE AS new_rows
FOR EACH STATEMENT EXECUTE FUNCTION fn_stage_dfo_flush();


-- =============================================================================
-- GloFAS
-- Omit matching_id_station — resolved automatically by the BEFORE trigger
-- on summary_glofas_latest when the staging flush pushes data through.
-- =============================================================================

CREATE TABLE IF NOT EXISTS stage_glofas (
    "timestamp"          TIMESTAMPTZ,
    pfaf_id              INTEGER,
    "ID"                 TEXT,
    "Point No"           INTEGER,
    "Alert_level"        INTEGER,
    "Days_until_peak"    INTEGER,
    "GloFAS_2yr"         DOUBLE PRECISION,
    "GloFAS_5yr"         DOUBLE PRECISION,
    "GloFAS_20yr"        DOUBLE PRECISION,
    "max_EPS"            TEXT,
    "Forecast Date"      TIMESTAMP,
    "Station"            TEXT,
    "Basin"              TEXT,
    "Country"            TEXT,
    "Country_code"       VARCHAR(8),
    "Continent"          TEXT,
    "Location"           TEXT,
    "Lat"                NUMERIC(8,3),
    "Lon"                NUMERIC(8,3),
    "Upstream area"      NUMERIC(15,3)
);

CREATE OR REPLACE FUNCTION fn_stage_glofas_flush()
RETURNS TRIGGER LANGUAGE plpgsql SECURITY DEFINER AS $$
DECLARE
    rc             INTEGER;
    batch_ts       TIMESTAMPTZ;
    hist_count     INTEGER;
    expected_count INTEGER;
BEGIN
    SELECT COUNT(*), MAX("timestamp") INTO rc, batch_ts FROM new_rows;

    IF rc < 1 THEN
        DELETE FROM stage_glofas;
        RETURN NULL;
    END IF;

    expected_count := COALESCE(NULLIF(current_setting('mom.expected_rows', true), '')::INTEGER, rc);

    SELECT COUNT(*) INTO hist_count FROM summary_glofas WHERE "timestamp" = batch_ts;

    IF hist_count >= expected_count THEN
        DELETE FROM stage_glofas;
        RETURN NULL;
    END IF;

    IF hist_count > 0 THEN
        DELETE FROM summary_glofas WHERE "timestamp" = batch_ts;
    END IF;

    -- Resolve matching_id_station: insert any new stations into the reference table,
    -- then JOIN to get the ID. Station metadata stays in all_glofas_stations only.
    INSERT INTO all_glofas_stations (
        matching_id_station,
        "Station", "Basin", "Country", "Country_code",
        "Continent", "Location",
        "Lat", "Lon", "Upstream area",
        pfaf_id
    )
    SELECT DISTINCT ON (s."Station", s."Country", s."Lat", s."Lon", s.pfaf_id)
        nextval('seq_glofas_station_id'),
        s."Station", s."Basin", s."Country", s."Country_code",
        s."Continent", s."Location",
        s."Lat", s."Lon", s."Upstream area",
        s.pfaf_id
    FROM stage_glofas s
    ON CONFLICT ("Station", "Country", "Lat", "Lon", pfaf_id) DO NOTHING;

    DELETE FROM summary_glofas_latest;

    INSERT INTO summary_glofas_latest (
        matching_id_station,
        "timestamp", pfaf_id,
        "ID", "Point No",
        "Alert_level", "Days_until_peak",
        "GloFAS_2yr", "GloFAS_5yr", "GloFAS_20yr",
        "max_EPS", "Forecast Date"
    )
    SELECT
        (SELECT MIN(st."matching_id_station")
         FROM all_glofas_stations st
         WHERE st."Station" = s."Station"
           AND st."Country" IS NOT DISTINCT FROM s."Country"
           AND st."Lat"     = s."Lat"
           AND st."Lon"     = s."Lon"
           AND st.pfaf_id   = s.pfaf_id),
        s."timestamp", s.pfaf_id,
        s."ID", s."Point No",
        s."Alert_level", s."Days_until_peak",
        s."GloFAS_2yr", s."GloFAS_5yr", s."GloFAS_20yr",
        s."max_EPS", s."Forecast Date"
    FROM stage_glofas s;

    DELETE FROM stage_glofas;
    RETURN NULL;
END;
$$;

CREATE TRIGGER trg_stage_glofas_flush
AFTER INSERT ON stage_glofas
REFERENCING NEW TABLE AS new_rows
FOR EACH STATEMENT EXECUTE FUNCTION fn_stage_glofas_flush();


-- =============================================================================
-- MoM GFMS
-- =============================================================================

-- stage_mom_gfms: captures both Attributes_Clean (base) and Final_Attributes (scores).
-- Resilience columns are pass-through only — backfilled to watershed_shapes, not forwarded.
-- No Flag column at the GFMS stage.
CREATE TABLE IF NOT EXISTS stage_mom_gfms (
    pfaf_id                      INTEGER,
    "timestamp"                  TIMESTAMPTZ,
    "FID"                        DOUBLE PRECISION,
    -- Pass-through only: backfilled to watershed_shapes, never forwarded to mom_gfms_latest
    "Resilience_Index"           DOUBLE PRECISION,
    "NormalizedLackofResilience" DOUBLE PRECISION,
    "Alert"                      TEXT,
    "Alert_level"                DOUBLE PRECISION,
    "Days_until_peak"            DOUBLE PRECISION,
    "GloFAS_2yr"                 DOUBLE PRECISION,
    "GloFAS_5yr"                 DOUBLE PRECISION,
    "GloFAS_20yr"                DOUBLE PRECISION,
    "Alert_Score"                DOUBLE PRECISION,
    "PeakArrivalScore"           DOUBLE PRECISION,
    "TwoYScore"                  DOUBLE PRECISION,
    "FiveYScore"                 DOUBLE PRECISION,
    "TwtyYScore"                 DOUBLE PRECISION,
    "Sum_Score_x"                DOUBLE PRECISION,
    "GFMS_TotalArea_km"          DOUBLE PRECISION,
    "GFMS_perc_Area"             DOUBLE PRECISION,
    "GFMS_MeanDepth"             DOUBLE PRECISION,
    "GFMS_MaxDepth"              DOUBLE PRECISION,
    "GFMS_Duration"              DOUBLE PRECISION,
    "GFMS_area_score"            DOUBLE PRECISION,
    "GFMS_perc_area_score"       DOUBLE PRECISION,
    "MeanD_Score"                DOUBLE PRECISION,
    "MaxD_Score"                 DOUBLE PRECISION,
    "Duration_Score"             DOUBLE PRECISION,
    "Sum_Score_y"                DOUBLE PRECISION,
    "Hazard_Score"               DOUBLE PRECISION,
    "Scaled_Riverine_Risk"       DOUBLE PRECISION,
    "Scaled_Coastal_Risk"        DOUBLE PRECISION,
    "Severity"                   DOUBLE PRECISION
);

-- Supports two-phase upsert: Attributes_Clean inserts base rows (score cols NULL),
-- Final_Attributes enriches matching rows. COALESCE preserves non-null values from
-- whichever phase ran first, so phases are order-independent and re-runnable.
CREATE OR REPLACE FUNCTION fn_stage_mom_gfms_flush()
RETURNS TRIGGER LANGUAGE plpgsql SECURITY DEFINER AS $$
DECLARE
    rc       INTEGER;
    batch_ts TIMESTAMPTZ;
BEGIN
    SELECT COUNT(*), MAX("timestamp") INTO rc, batch_ts FROM new_rows;

    IF rc < 1 THEN
        DELETE FROM stage_mom_gfms;
        RETURN NULL;
    END IF;

    -- Backfill watershed_shapes with resilience data for any pfaf_id not yet set.
    UPDATE watershed_shapes ws
    SET
        "Resilience_Index"           = s."Resilience_Index",
        "NormalizedLackofResilience" = s."NormalizedLackofResilience"
    FROM stage_mom_gfms s
    WHERE ws.pfaf_id = s.pfaf_id
      AND s."Resilience_Index" IS NOT NULL
      AND ws."Resilience_Index" IS NULL;

    DELETE FROM mom_gfms_latest;

    INSERT INTO mom_gfms_latest (
        pfaf_id, "timestamp",
        "FID", "Alert",
        "Alert_level", "Days_until_peak",
        "GloFAS_2yr", "GloFAS_5yr", "GloFAS_20yr",
        "Alert_Score", "PeakArrivalScore",
        "TwoYScore", "FiveYScore", "TwtyYScore", "Sum_Score_x",
        "GFMS_TotalArea_km", "GFMS_perc_Area",
        "GFMS_MeanDepth", "GFMS_MaxDepth", "GFMS_Duration",
        "GFMS_area_score", "GFMS_perc_area_score",
        "MeanD_Score", "MaxD_Score", "Duration_Score", "Sum_Score_y",
        "Hazard_Score", "Scaled_Riverine_Risk", "Scaled_Coastal_Risk", "Severity"
    )
    SELECT
        pfaf_id, "timestamp",
        "FID", "Alert",
        "Alert_level", "Days_until_peak",
        "GloFAS_2yr", "GloFAS_5yr", "GloFAS_20yr",
        "Alert_Score", "PeakArrivalScore",
        "TwoYScore", "FiveYScore", "TwtyYScore", "Sum_Score_x",
        "GFMS_TotalArea_km", "GFMS_perc_Area",
        "GFMS_MeanDepth", "GFMS_MaxDepth", "GFMS_Duration",
        "GFMS_area_score", "GFMS_perc_area_score",
        "MeanD_Score", "MaxD_Score", "Duration_Score", "Sum_Score_y",
        "Hazard_Score", "Scaled_Riverine_Risk", "Scaled_Coastal_Risk", "Severity"
    FROM stage_mom_gfms;

    DELETE FROM stage_mom_gfms;
    RETURN NULL;
END;
$$;

CREATE TRIGGER trg_stage_mom_gfms_flush
AFTER INSERT ON stage_mom_gfms
REFERENCING NEW TABLE AS new_rows
FOR EACH STATEMENT EXECUTE FUNCTION fn_stage_mom_gfms_flush();


-- =============================================================================
-- MoM HWRF
-- =============================================================================

-- stage_mom_hwrf: captures Attributes_Clean (base) and Final_Attributes (HWRF scores).
-- Resilience columns are pass-through only — backfilled to watershed_shapes, not forwarded.
-- GloFAS/GFMS columns are ignored (upsert_dataframe silently drops unknown cols).
CREATE TABLE IF NOT EXISTS stage_mom_hwrf (
    pfaf_id                      INTEGER,
    "timestamp"                  TIMESTAMPTZ,
    "FID"                        DOUBLE PRECISION,
    -- Pass-through only: backfilled to watershed_shapes, never forwarded to mom_hwrf_latest
    "Resilience_Index"           DOUBLE PRECISION,
    "NormalizedLackofResilience" DOUBLE PRECISION,
    "Alert"                      TEXT,
    "Flag"                       TEXT,
    "Rain_TotalArea_km"          DOUBLE PRECISION,
    "perc_Area"                  DOUBLE PRECISION,
    "MeanRain"                   DOUBLE PRECISION,
    "MaxRain"                    DOUBLE PRECISION,
    "HWRF_area_score"            DOUBLE PRECISION,
    "HWRF_percarea_score"        DOUBLE PRECISION,
    "MeanRain_Score"             DOUBLE PRECISION,
    "MaxRain_Score"              DOUBLE PRECISION,
    "HWRFTot_Score"              DOUBLE PRECISION,
    "MOM_Score"                  DOUBLE PRECISION,
    "Hazard_Score"               DOUBLE PRECISION,
    "Severity"                   DOUBLE PRECISION
);

-- Supports two-phase upsert: Attributes_Clean inserts base rows (score cols NULL),
-- Final_Attributes enriches matching rows. COALESCE preserves non-null values from
-- whichever phase ran first, so phases are order-independent and re-runnable.
CREATE OR REPLACE FUNCTION fn_stage_mom_hwrf_flush()
RETURNS TRIGGER LANGUAGE plpgsql SECURITY DEFINER AS $$
DECLARE
    rc       INTEGER;
    batch_ts TIMESTAMPTZ;
BEGIN
    SELECT COUNT(*), MAX("timestamp") INTO rc, batch_ts FROM new_rows;

    IF rc < 1 THEN
        DELETE FROM stage_mom_hwrf;
        RETURN NULL;
    END IF;

    -- Backfill watershed_shapes with resilience data for any pfaf_id not yet set.
    UPDATE watershed_shapes ws
    SET
        "Resilience_Index"           = s."Resilience_Index",
        "NormalizedLackofResilience" = s."NormalizedLackofResilience"
    FROM stage_mom_hwrf s
    WHERE ws.pfaf_id = s.pfaf_id
      AND s."Resilience_Index" IS NOT NULL
      AND ws."Resilience_Index" IS NULL;

    DELETE FROM mom_hwrf_latest;

    INSERT INTO mom_hwrf_latest (
        pfaf_id, "timestamp",
        "FID", "Alert", "Flag",
        "Rain_TotalArea_km", "perc_Area", "MeanRain", "MaxRain",
        "HWRF_area_score", "HWRF_percarea_score",
        "MeanRain_Score", "MaxRain_Score", "HWRFTot_Score",
        "MOM_Score", "Hazard_Score", "Severity"
    )
    SELECT
        pfaf_id, "timestamp",
        "FID", "Alert", "Flag",
        "Rain_TotalArea_km", "perc_Area", "MeanRain", "MaxRain",
        "HWRF_area_score", "HWRF_percarea_score",
        "MeanRain_Score", "MaxRain_Score", "HWRFTot_Score",
        "MOM_Score", "Hazard_Score", "Severity"
    FROM stage_mom_hwrf;

    DELETE FROM stage_mom_hwrf;
    RETURN NULL;
END;
$$;

CREATE TRIGGER trg_stage_mom_hwrf_flush
AFTER INSERT ON stage_mom_hwrf
REFERENCING NEW TABLE AS new_rows
FOR EACH STATEMENT EXECUTE FUNCTION fn_stage_mom_hwrf_flush();


-- =============================================================================
-- MoM DFO
-- =============================================================================

-- stage_mom_dfo: captures Attributes_Clean (base) and Final_Attributes (DFO scores).
-- Resilience columns are pass-through only — backfilled to watershed_shapes, not forwarded.
-- GloFAS/GFMS/HWRF columns are ignored (upsert_dataframe silently drops unknown cols).
CREATE TABLE IF NOT EXISTS stage_mom_dfo (
    pfaf_id                      INTEGER,
    "timestamp"                  TIMESTAMPTZ,
    "FID"                        DOUBLE PRECISION,
    "Alert"                      TEXT,
    "Flag"                       TEXT,
    -- Pass-through only: backfilled to watershed_shapes, never forwarded to mom_dfo_latest
    "Resilience_Index"           DOUBLE PRECISION,
    "NormalizedLackofResilience" DOUBLE PRECISION,
    "1-Day_TotalArea_km2"        DOUBLE PRECISION,
    "1-Day_perc_Area"            DOUBLE PRECISION,
    "1-Day_CS_TotalArea_km2"     DOUBLE PRECISION,
    "1-Day_CS_perc_Area"         DOUBLE PRECISION,
    "2-Day_TotalArea_km2"        DOUBLE PRECISION,
    "2-Day_perc_Area"            DOUBLE PRECISION,
    "3-Day_TotalArea_km2"        DOUBLE PRECISION,
    "3-Day_perc_Area"            DOUBLE PRECISION,
    "DFO_area_1day_score"        DOUBLE PRECISION,
    "DFO_percarea_1day_score"    DOUBLE PRECISION,
    "DFO_area_2day_score"        DOUBLE PRECISION,
    "DFO_percarea_2day_score"    DOUBLE PRECISION,
    "DFO_area_3day_score"        DOUBLE PRECISION,
    "DFO_percarea_3day_score"    DOUBLE PRECISION,
    "DFOTotal_Score"             DOUBLE PRECISION,
    "Hazard_Score"               DOUBLE PRECISION,
    "Severity"                   DOUBLE PRECISION
);

-- Supports two-phase upsert: Attributes_Clean inserts base rows (score cols NULL),
-- Final_Attributes enriches matching rows. COALESCE preserves non-null values from
-- whichever phase ran first, so phases are order-independent and re-runnable.
CREATE OR REPLACE FUNCTION fn_stage_mom_dfo_flush()
RETURNS TRIGGER LANGUAGE plpgsql SECURITY DEFINER AS $$
DECLARE
    rc       INTEGER;
    batch_ts TIMESTAMPTZ;
BEGIN
    SELECT COUNT(*), MAX("timestamp") INTO rc, batch_ts FROM new_rows;

    IF rc < 1 THEN
        DELETE FROM stage_mom_dfo;
        RETURN NULL;
    END IF;

    -- Backfill watershed_shapes with resilience data for any pfaf_id not yet set.
    UPDATE watershed_shapes ws
    SET
        "Resilience_Index"           = s."Resilience_Index",
        "NormalizedLackofResilience" = s."NormalizedLackofResilience"
    FROM stage_mom_dfo s
    WHERE ws.pfaf_id = s.pfaf_id
      AND s."Resilience_Index" IS NOT NULL
      AND ws."Resilience_Index" IS NULL;

    DELETE FROM mom_dfo_latest;

    INSERT INTO mom_dfo_latest (
        pfaf_id, "timestamp",
        "FID", "Alert", "Flag",
        "1-Day_TotalArea_km2", "1-Day_perc_Area",
        "1-Day_CS_TotalArea_km2", "1-Day_CS_perc_Area",
        "2-Day_TotalArea_km2", "2-Day_perc_Area",
        "3-Day_TotalArea_km2", "3-Day_perc_Area",
        "DFO_area_1day_score", "DFO_percarea_1day_score",
        "DFO_area_2day_score", "DFO_percarea_2day_score",
        "DFO_area_3day_score", "DFO_percarea_3day_score",
        "DFOTotal_Score", "Hazard_Score", "Severity"
    )
    SELECT
        pfaf_id, "timestamp",
        "FID", "Alert", "Flag",
        "1-Day_TotalArea_km2", "1-Day_perc_Area",
        "1-Day_CS_TotalArea_km2", "1-Day_CS_perc_Area",
        "2-Day_TotalArea_km2", "2-Day_perc_Area",
        "3-Day_TotalArea_km2", "3-Day_perc_Area",
        "DFO_area_1day_score", "DFO_percarea_1day_score",
        "DFO_area_2day_score", "DFO_percarea_2day_score",
        "DFO_area_3day_score", "DFO_percarea_3day_score",
        "DFOTotal_Score", "Hazard_Score", "Severity"
    FROM stage_mom_dfo;

    DELETE FROM stage_mom_dfo;
    RETURN NULL;
END;
$$;

CREATE TRIGGER trg_stage_mom_dfo_flush
AFTER INSERT ON stage_mom_dfo
REFERENCING NEW TABLE AS new_rows
FOR EACH STATEMENT EXECUTE FUNCTION fn_stage_mom_dfo_flush();


-- =============================================================================
-- MoM VIIRS
-- =============================================================================

-- stage_mom_viirs: captures Attributes_Clean (base) and Final_Attributes (VIIRS scores).
-- Resilience columns are pass-through only — backfilled to watershed_shapes, not forwarded.
-- GloFAS/GFMS/HWRF/DFO columns are ignored (upsert_dataframe silently drops unknown cols).
CREATE TABLE IF NOT EXISTS stage_mom_viirs (
    pfaf_id                      INTEGER,
    "timestamp"                  TIMESTAMPTZ,
    "FID"                        DOUBLE PRECISION,
    -- Pass-through only: backfilled to watershed_shapes, never forwarded to mom_viirs_latest
    "Resilience_Index"           DOUBLE PRECISION,
    "NormalizedLackofResilience" DOUBLE PRECISION,
    "Alert"                      TEXT,
    "Flag"                       TEXT,
    "onedayFlood_Area_km"        DOUBLE PRECISION,
    "onedayperc_Area"            DOUBLE PRECISION,
    "fivedayFlood_Area_km"       DOUBLE PRECISION,
    "fivedayperc_Area"           DOUBLE PRECISION,
    "VIIRS_area_1day_score"      DOUBLE PRECISION,
    "VIIRS_percarea_1day_score"  DOUBLE PRECISION,
    "VIIRS_area_5day_score"      DOUBLE PRECISION,
    "VIIRS_percarea_5day_score"  DOUBLE PRECISION,
    "VIIRSTotal_Score"           DOUBLE PRECISION,
    "Hazard_Score"               DOUBLE PRECISION,
    "Severity"                   DOUBLE PRECISION
);

-- Supports two-phase upsert: Attributes_Clean inserts base rows (score cols NULL),
-- Final_Attributes enriches matching rows. COALESCE preserves non-null values from
-- whichever phase ran first, so phases are order-independent and re-runnable.
CREATE OR REPLACE FUNCTION fn_stage_mom_viirs_flush()
RETURNS TRIGGER LANGUAGE plpgsql SECURITY DEFINER AS $$
DECLARE
    rc       INTEGER;
    batch_ts TIMESTAMPTZ;
BEGIN
    SELECT COUNT(*), MAX("timestamp") INTO rc, batch_ts FROM new_rows;

    IF rc < 1 THEN
        DELETE FROM stage_mom_viirs;
        RETURN NULL;
    END IF;

    -- Backfill watershed_shapes with resilience data for any pfaf_id not yet set.
    UPDATE watershed_shapes ws
    SET
        "Resilience_Index"           = s."Resilience_Index",
        "NormalizedLackofResilience" = s."NormalizedLackofResilience"
    FROM stage_mom_viirs s
    WHERE ws.pfaf_id = s.pfaf_id
      AND s."Resilience_Index" IS NOT NULL
      AND ws."Resilience_Index" IS NULL;

    DELETE FROM mom_viirs_latest;

    INSERT INTO mom_viirs_latest (
        pfaf_id, "timestamp",
        "FID", "Alert", "Flag",
        "onedayFlood_Area_km", "onedayperc_Area",
        "fivedayFlood_Area_km", "fivedayperc_Area",
        "VIIRS_area_1day_score", "VIIRS_percarea_1day_score",
        "VIIRS_area_5day_score", "VIIRS_percarea_5day_score",
        "VIIRSTotal_Score", "Hazard_Score", "Severity"
    )
    SELECT
        pfaf_id, "timestamp",
        "FID", "Alert", "Flag",
        "onedayFlood_Area_km", "onedayperc_Area",
        "fivedayFlood_Area_km", "fivedayperc_Area",
        "VIIRS_area_1day_score", "VIIRS_percarea_1day_score",
        "VIIRS_area_5day_score", "VIIRS_percarea_5day_score",
        "VIIRSTotal_Score", "Hazard_Score", "Severity"
    FROM stage_mom_viirs;

    DELETE FROM stage_mom_viirs;
    RETURN NULL;
END;
$$;

CREATE TRIGGER trg_stage_mom_viirs_flush
AFTER INSERT ON stage_mom_viirs
REFERENCING NEW TABLE AS new_rows
FOR EACH STATEMENT EXECUTE FUNCTION fn_stage_mom_viirs_flush();


-- =============================================================================
-- Final Alert
-- Omit matching_id_watershed — resolved automatically by the BEFORE trigger
-- on summary_final_alert_latest when the staging flush pushes data through.
-- =============================================================================

CREATE TABLE IF NOT EXISTS stage_final_alert (
    "timestamp"                 TIMESTAMPTZ,
    pfaf_id                     INTEGER,
    "rfr_score"                 DOUBLE PRECISION,
    "cfr_score"                 DOUBLE PRECISION,
    "Alert_level"               DOUBLE PRECISION,
    "Days_until_peak"           DOUBLE PRECISION,
    "GloFAS_2yr"                DOUBLE PRECISION,
    "GloFAS_5yr"                DOUBLE PRECISION,
    "GloFAS_20yr"               DOUBLE PRECISION,
    "Alert_Score"               DOUBLE PRECISION,
    "PeakArrivalScore"          DOUBLE PRECISION,
    "TwoYScore"                 DOUBLE PRECISION,
    "FiveYScore"                DOUBLE PRECISION,
    "TwtyYScore"                DOUBLE PRECISION,
    "Sum_Score_x"               DOUBLE PRECISION,
    "GFMS_TotalArea_km"         DOUBLE PRECISION,
    "GFMS_perc_Area"            DOUBLE PRECISION,
    "GFMS_MeanDepth"            DOUBLE PRECISION,
    "GFMS_MaxDepth"             DOUBLE PRECISION,
    "GFMS_Duration"             DOUBLE PRECISION,
    "GFMS_area_score"           DOUBLE PRECISION,
    "GFMS_perc_area_score"      DOUBLE PRECISION,
    "MeanD_Score"               DOUBLE PRECISION,
    "MaxD_Score"                DOUBLE PRECISION,
    "Duration_Score"            DOUBLE PRECISION,
    "Sum_Score_y"               DOUBLE PRECISION,
    "MOM_Score"                 DOUBLE PRECISION,
    "Hazard_Score"              DOUBLE PRECISION,
    "Scaled_Riverine_Risk"      DOUBLE PRECISION,
    "Scaled_Coastal_Risk"       DOUBLE PRECISION,
    "Flag"                      DOUBLE PRECISION,
    "1-Day_TotalArea_km2"       DOUBLE PRECISION,
    "1-Day_perc_Area"           DOUBLE PRECISION,
    "1-Day_CS_TotalArea_km2"    DOUBLE PRECISION,
    "1-Day_CS_perc_Area"        DOUBLE PRECISION,
    "2-Day_TotalArea_km2"       DOUBLE PRECISION,
    "2-Day_perc_Area"           DOUBLE PRECISION,
    "3-Day_TotalArea_km2"       DOUBLE PRECISION,
    "3-Day_perc_Area"           DOUBLE PRECISION,
    "DFO_area_1day_score"       DOUBLE PRECISION,
    "DFO_percarea_1day_score"   DOUBLE PRECISION,
    "DFO_area_2day_score"       DOUBLE PRECISION,
    "DFO_percarea_2day_score"   DOUBLE PRECISION,
    "DFO_area_3day_score"       DOUBLE PRECISION,
    "DFO_percarea_3day_score"   DOUBLE PRECISION,
    "DFOTotal_Score"            DOUBLE PRECISION,
    "onedayFlood_Area_km"       DOUBLE PRECISION,
    "onedayperc_Area"           DOUBLE PRECISION,
    "fivedayFlood_Area_km"      DOUBLE PRECISION,
    "fivedayperc_Area"          DOUBLE PRECISION,
    "VIIRS_area_1day_score"     DOUBLE PRECISION,
    "VIIRS_percarea_1day_score" DOUBLE PRECISION,
    "VIIRS_area_5day_score"     DOUBLE PRECISION,
    "VIIRS_percarea_5day_score" DOUBLE PRECISION,
    "VIIRSTotal_Score"          DOUBLE PRECISION,
    "Severity"                  DOUBLE PRECISION,
    "Alert"                     TEXT,
    "Status"                    TEXT,
    "name"                      TEXT,
    "name_1"                    TEXT,
    "CentroidX"                 NUMERIC(10,6),
    "CentroidY"                 NUMERIC(10,6),
    "Admin1_count"              INTEGER,
    "Admin1_names"              TEXT
);

CREATE OR REPLACE FUNCTION fn_stage_final_alert_flush()
RETURNS TRIGGER LANGUAGE plpgsql SECURITY DEFINER AS $$
DECLARE
    rc             INTEGER;
    batch_ts       TIMESTAMPTZ;
    hist_count     INTEGER;
    expected_count INTEGER;
BEGIN
    SELECT COUNT(*), MAX("timestamp") INTO rc, batch_ts FROM new_rows;

    IF rc < 1 THEN
        DELETE FROM stage_final_alert;
        RETURN NULL;
    END IF;

    expected_count := COALESCE(NULLIF(current_setting('mom.expected_rows', true), '')::INTEGER, rc);

    SELECT COUNT(*) INTO hist_count FROM summary_final_alert WHERE "timestamp" = batch_ts;

    IF hist_count >= expected_count THEN
        DELETE FROM stage_final_alert;
        RETURN NULL;
    END IF;

    IF hist_count > 0 THEN
        DELETE FROM summary_final_alert WHERE "timestamp" = batch_ts;
    END IF;

    -- Resolve matching_id_watershed: insert any new watershed slices into the
    -- reference table, then JOIN to get the ID. Watershed metadata
    -- (name, name_1, CentroidX, CentroidY, Admin1_count, Admin1_names) stays
    -- in all_watersheds only and is no longer stored in the latest/history tables.
    INSERT INTO all_watersheds (
        matching_id_watershed,
        pfaf_id,
        "name", "name_1",
        "CentroidX", "CentroidY",
        "Admin1_count", "Admin1_names"
    )
    SELECT DISTINCT ON (s.pfaf_id, s."name", s."name_1", s."CentroidX", s."CentroidY")
        nextval('seq_watershed_id'),
        s.pfaf_id,
        s."name", s."name_1",
        s."CentroidX"::NUMERIC(10,6), s."CentroidY"::NUMERIC(10,6),
        s."Admin1_count", s."Admin1_names"
    FROM stage_final_alert s
    ON CONFLICT (pfaf_id, "name", "name_1", "CentroidX", "CentroidY") DO NOTHING;

    DELETE FROM summary_final_alert_latest;

    INSERT INTO summary_final_alert_latest (
        matching_id_watershed,
        "timestamp", pfaf_id,
        "Alert_level", "Days_until_peak",
        "GloFAS_2yr", "GloFAS_5yr", "GloFAS_20yr",
        "Alert_Score", "PeakArrivalScore",
        "TwoYScore", "FiveYScore", "TwtyYScore", "Sum_Score_x",
        "GFMS_TotalArea_km", "GFMS_perc_Area", "GFMS_MeanDepth",
        "GFMS_MaxDepth", "GFMS_Duration",
        "GFMS_area_score", "GFMS_perc_area_score",
        "MeanD_Score", "MaxD_Score", "Duration_Score",
        "Sum_Score_y", "MOM_Score", "Hazard_Score",
        "Scaled_Riverine_Risk", "Scaled_Coastal_Risk", "Flag",
        "1-Day_TotalArea_km2", "1-Day_perc_Area",
        "1-Day_CS_TotalArea_km2", "1-Day_CS_perc_Area",
        "2-Day_TotalArea_km2", "2-Day_perc_Area",
        "3-Day_TotalArea_km2", "3-Day_perc_Area",
        "DFO_area_1day_score", "DFO_percarea_1day_score",
        "DFO_area_2day_score", "DFO_percarea_2day_score",
        "DFO_area_3day_score", "DFO_percarea_3day_score",
        "DFOTotal_Score",
        "onedayFlood_Area_km", "onedayperc_Area",
        "fivedayFlood_Area_km", "fivedayperc_Area",
        "VIIRS_area_1day_score", "VIIRS_percarea_1day_score",
        "VIIRS_area_5day_score", "VIIRS_percarea_5day_score",
        "VIIRSTotal_Score",
        "Severity", "Alert", "Status"
    )
    SELECT
        (SELECT MIN(w."matching_id_watershed")
         FROM all_watersheds w
         WHERE w.pfaf_id      = s.pfaf_id
           AND w."name"       = s."name"
           AND w."name_1"     = s."name_1"
           AND w."CentroidX"  = s."CentroidX"::NUMERIC(10,6)
           AND w."CentroidY"  = s."CentroidY"::NUMERIC(10,6)),
        s."timestamp", s.pfaf_id,
        s."Alert_level", s."Days_until_peak",
        s."GloFAS_2yr", s."GloFAS_5yr", s."GloFAS_20yr",
        s."Alert_Score", s."PeakArrivalScore",
        s."TwoYScore", s."FiveYScore", s."TwtyYScore", s."Sum_Score_x",
        s."GFMS_TotalArea_km", s."GFMS_perc_Area", s."GFMS_MeanDepth",
        s."GFMS_MaxDepth", s."GFMS_Duration",
        s."GFMS_area_score", s."GFMS_perc_area_score",
        s."MeanD_Score", s."MaxD_Score", s."Duration_Score",
        s."Sum_Score_y", s."MOM_Score", s."Hazard_Score",
        s."Scaled_Riverine_Risk", s."Scaled_Coastal_Risk", s."Flag",
        s."1-Day_TotalArea_km2", s."1-Day_perc_Area",
        s."1-Day_CS_TotalArea_km2", s."1-Day_CS_perc_Area",
        s."2-Day_TotalArea_km2", s."2-Day_perc_Area",
        s."3-Day_TotalArea_km2", s."3-Day_perc_Area",
        s."DFO_area_1day_score", s."DFO_percarea_1day_score",
        s."DFO_area_2day_score", s."DFO_percarea_2day_score",
        s."DFO_area_3day_score", s."DFO_percarea_3day_score",
        s."DFOTotal_Score",
        s."onedayFlood_Area_km", s."onedayperc_Area",
        s."fivedayFlood_Area_km", s."fivedayperc_Area",
        s."VIIRS_area_1day_score", s."VIIRS_percarea_1day_score",
        s."VIIRS_area_5day_score", s."VIIRS_percarea_5day_score",
        s."VIIRSTotal_Score",
        s."Severity", s."Alert", s."Status"
    FROM stage_final_alert s;

    DELETE FROM stage_final_alert;
    RETURN NULL;
END;
$$;

CREATE TRIGGER trg_stage_final_alert_flush
AFTER INSERT ON stage_final_alert
REFERENCING NEW TABLE AS new_rows
FOR EACH STATEMENT EXECUTE FUNCTION fn_stage_final_alert_flush();


-- =============================================================================
-- Shared pre-insert clear: truncates the staging table before each batch so
-- that retries never accumulate duplicate rows.
-- =============================================================================

CREATE OR REPLACE FUNCTION fn_stage_clear()
RETURNS TRIGGER LANGUAGE plpgsql SECURITY DEFINER AS $$
BEGIN
    EXECUTE 'DELETE FROM ' || TG_TABLE_NAME;
    RETURN NULL;
END;
$$;


CREATE TRIGGER trg_stage_gfms_clear        BEFORE INSERT ON stage_gfms        FOR EACH STATEMENT EXECUTE FUNCTION fn_stage_clear();
CREATE TRIGGER trg_stage_hwrf_clear        BEFORE INSERT ON stage_hwrf        FOR EACH STATEMENT EXECUTE FUNCTION fn_stage_clear();
CREATE TRIGGER trg_stage_viirs_clear       BEFORE INSERT ON stage_viirs       FOR EACH STATEMENT EXECUTE FUNCTION fn_stage_clear();
CREATE TRIGGER trg_stage_dfo_clear         BEFORE INSERT ON stage_dfo         FOR EACH STATEMENT EXECUTE FUNCTION fn_stage_clear();
CREATE TRIGGER trg_stage_glofas_clear      BEFORE INSERT ON stage_glofas      FOR EACH STATEMENT EXECUTE FUNCTION fn_stage_clear();
CREATE TRIGGER trg_stage_mom_gfms_clear    BEFORE INSERT ON stage_mom_gfms    FOR EACH STATEMENT EXECUTE FUNCTION fn_stage_clear();
CREATE TRIGGER trg_stage_mom_hwrf_clear    BEFORE INSERT ON stage_mom_hwrf    FOR EACH STATEMENT EXECUTE FUNCTION fn_stage_clear();
CREATE TRIGGER trg_stage_mom_dfo_clear     BEFORE INSERT ON stage_mom_dfo     FOR EACH STATEMENT EXECUTE FUNCTION fn_stage_clear();
CREATE TRIGGER trg_stage_mom_viirs_clear   BEFORE INSERT ON stage_mom_viirs   FOR EACH STATEMENT EXECUTE FUNCTION fn_stage_clear();
CREATE TRIGGER trg_stage_final_alert_clear BEFORE INSERT ON stage_final_alert FOR EACH STATEMENT EXECUTE FUNCTION fn_stage_clear();
