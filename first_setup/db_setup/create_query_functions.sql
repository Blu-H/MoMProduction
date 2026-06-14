-- =============================================================================
-- create_query_functions.sql
--
-- Query helper functions for all history tables.
--
-- GFMS / DFO  — zero-filtered tables.  Three-case semantics:
--   Case 1 — timestamp not in the table → return 0 rows
--   Case 2 — timestamp exists, pfaf_id absent → return zeros
--   Case 3 — both exist → return real row
--
-- GloFAS / Final Alert — no zero-filtering.  Join with reference and
--   geometry tables to return the full denormalised view:
--     summary_glofas      → all_glofas_stations → watershed_shapes
--     summary_final_alert → all_watersheds      → watershed_shapes
--
-- GFMS / DFO batch functions return only rows present in the history table
-- for that timestamp — no join to external tables.
--
-- Functions:
--   fn_get_gfms(p_ts, p_pfaf_id)           — single watershed lookup
--   fn_get_gfms_batch(p_ts)                — all watersheds for a timestamp
--   fn_get_hwrf(p_ts, p_pfaf_id)           — single watershed lookup
--   fn_get_hwrf_batch(p_ts)                — all watersheds for a timestamp
--   fn_get_viirs(p_ts, p_pfaf_id)          — single watershed lookup
--   fn_get_viirs_batch(p_ts)               — all watersheds for a timestamp
--   fn_get_dfo(p_ts, p_pfaf_id)            — single watershed lookup
--   fn_get_dfo_batch(p_ts)                 — all watersheds for a timestamp
--   fn_get_glofas(p_ts, p_pfaf_id)         — all stations for a watershed + timestamp
--   fn_get_glofas_batch(p_ts)              — all stations for a timestamp
--   fn_get_final_alert(p_ts, p_pfaf_id)    — single watershed lookup
--   fn_get_final_alert_batch(p_ts)         — all watersheds for a timestamp
--
-- Run AFTER create_all_tables.sql.
-- Run with:
--   sudo -u postgres psql -d postgres -f create_query_functions.sql
-- =============================================================================


-- =============================================================================
-- GFMS — single watershed lookup
-- =============================================================================

CREATE OR REPLACE FUNCTION fn_get_gfms(p_ts TIMESTAMPTZ, p_pfaf_id INTEGER)
RETURNS TABLE (
    pfaf_id             INTEGER,
    "timestamp"         TIMESTAMPTZ,
    "GFMS_TotalArea_km" DOUBLE PRECISION,
    "GFMS_perc_Area"    DOUBLE PRECISION,
    "GFMS_MeanDepth"    DOUBLE PRECISION,
    "GFMS_MaxDepth"     DOUBLE PRECISION,
    "GFMS_Duration"     DOUBLE PRECISION
) LANGUAGE plpgsql AS $$
BEGIN
    -- Case 1: timestamp not in table — return nothing
    IF NOT EXISTS (
        SELECT 1 FROM summary_gfms WHERE "timestamp" = p_ts
    ) THEN
        RETURN;
    END IF;

    -- Cases 2 & 3: timestamp exists — real row or synthesised zero row
    RETURN QUERY
    SELECT
        p_pfaf_id,
        p_ts,
        COALESCE(g."GFMS_TotalArea_km", 0.0),
        COALESCE(g."GFMS_perc_Area",    0.0),
        COALESCE(g."GFMS_MeanDepth",    0.0),
        COALESCE(g."GFMS_MaxDepth",     0.0),
        COALESCE(g."GFMS_Duration",     0.0)
    FROM (SELECT 1) dummy
    LEFT JOIN summary_gfms g
        ON g."timestamp" = p_ts
       AND g.pfaf_id     = p_pfaf_id;
END;
$$;


-- =============================================================================
-- GFMS — all rows for a given timestamp
-- Returns only pfaf_ids that have real data for p_ts.
-- =============================================================================

CREATE OR REPLACE FUNCTION fn_get_gfms_batch(p_ts TIMESTAMPTZ)
RETURNS TABLE (
    pfaf_id             INTEGER,
    "timestamp"         TIMESTAMPTZ,
    "GFMS_TotalArea_km" DOUBLE PRECISION,
    "GFMS_perc_Area"    DOUBLE PRECISION,
    "GFMS_MeanDepth"    DOUBLE PRECISION,
    "GFMS_MaxDepth"     DOUBLE PRECISION,
    "GFMS_Duration"     DOUBLE PRECISION
) LANGUAGE plpgsql AS $$
BEGIN
    RETURN QUERY
    SELECT
        g.pfaf_id,
        g."timestamp",
        g."GFMS_TotalArea_km",
        g."GFMS_perc_Area",
        g."GFMS_MeanDepth",
        g."GFMS_MaxDepth",
        g."GFMS_Duration"::DOUBLE PRECISION
    FROM summary_gfms g
    WHERE g."timestamp" = p_ts
    ORDER BY g.pfaf_id;
END;
$$;


-- =============================================================================
-- HWRF — single watershed lookup
-- =============================================================================

CREATE OR REPLACE FUNCTION fn_get_hwrf(p_ts TIMESTAMPTZ, p_pfaf_id INTEGER)
RETURNS TABLE (
    pfaf_id              INTEGER,
    "timestamp"          TIMESTAMPTZ,
    "Rain_TotalArea_km"  DOUBLE PRECISION,
    "perc_Area"          DOUBLE PRECISION,
    "MeanRain"           DOUBLE PRECISION,
    "MaxRain"            DOUBLE PRECISION
) LANGUAGE plpgsql AS $$
BEGIN
    -- Case 1: timestamp not in table — return nothing
    IF NOT EXISTS (
        SELECT 1 FROM summary_hwrf WHERE "timestamp" = p_ts
    ) THEN
        RETURN;
    END IF;

    -- Cases 2 & 3: timestamp exists — real row or synthesised zero row
    RETURN QUERY
    SELECT
        p_pfaf_id,
        p_ts,
        COALESCE(h."Rain_TotalArea_km", 0.0),
        COALESCE(h."perc_Area",         0.0),
        COALESCE(h."MeanRain",          0.0),
        COALESCE(h."MaxRain",           0.0)
    FROM (SELECT 1) dummy
    LEFT JOIN summary_hwrf h
        ON h."timestamp" = p_ts
       AND h.pfaf_id     = p_pfaf_id;
END;
$$;


-- =============================================================================
-- HWRF — all rows for a given timestamp
-- Returns only pfaf_ids that have real data for p_ts.
-- =============================================================================

CREATE OR REPLACE FUNCTION fn_get_hwrf_batch(p_ts TIMESTAMPTZ)
RETURNS TABLE (
    pfaf_id              INTEGER,
    "timestamp"          TIMESTAMPTZ,
    "Rain_TotalArea_km"  DOUBLE PRECISION,
    "perc_Area"          DOUBLE PRECISION,
    "MeanRain"           DOUBLE PRECISION,
    "MaxRain"            DOUBLE PRECISION
) LANGUAGE plpgsql AS $$
BEGIN
    RETURN QUERY
    SELECT
        h.pfaf_id,
        h."timestamp",
        h."Rain_TotalArea_km",
        h."perc_Area",
        h."MeanRain",
        h."MaxRain"
    FROM summary_hwrf h
    WHERE h."timestamp" = p_ts
    ORDER BY h.pfaf_id;
END;
$$;


-- =============================================================================
-- VIIRS — single watershed lookup
-- =============================================================================

CREATE OR REPLACE FUNCTION fn_get_viirs(p_ts TIMESTAMPTZ, p_pfaf_id INTEGER)
RETURNS TABLE (
    pfaf_id                  INTEGER,
    "timestamp"              TIMESTAMPTZ,
    "onedayFlood_Area_km"    DOUBLE PRECISION,
    "onedayperc_Area"        DOUBLE PRECISION,
    "fivedayFlood_Area_km"   DOUBLE PRECISION,
    "fivedayperc_Area"       DOUBLE PRECISION
) LANGUAGE plpgsql AS $$
BEGIN
    -- Case 1: timestamp not in table — return nothing
    IF NOT EXISTS (
        SELECT 1 FROM summary_viirs WHERE "timestamp" = p_ts
    ) THEN
        RETURN;
    END IF;

    -- Cases 2 & 3: timestamp exists — real row or synthesised zero row
    RETURN QUERY
    SELECT
        p_pfaf_id,
        p_ts,
        COALESCE(v."onedayFlood_Area_km",  0.0),
        COALESCE(v."onedayperc_Area",      0.0),
        COALESCE(v."fivedayFlood_Area_km", 0.0),
        COALESCE(v."fivedayperc_Area",     0.0)
    FROM (SELECT 1) dummy
    LEFT JOIN summary_viirs v
        ON v."timestamp" = p_ts
       AND v.pfaf_id     = p_pfaf_id;
END;
$$;


-- =============================================================================
-- VIIRS — all rows for a given timestamp
-- Returns only pfaf_ids that have real data for p_ts.
-- =============================================================================

CREATE OR REPLACE FUNCTION fn_get_viirs_batch(p_ts TIMESTAMPTZ)
RETURNS TABLE (
    pfaf_id                  INTEGER,
    "timestamp"              TIMESTAMPTZ,
    "onedayFlood_Area_km"    DOUBLE PRECISION,
    "onedayperc_Area"        DOUBLE PRECISION,
    "fivedayFlood_Area_km"   DOUBLE PRECISION,
    "fivedayperc_Area"       DOUBLE PRECISION
) LANGUAGE plpgsql AS $$
BEGIN
    RETURN QUERY
    SELECT
        v.pfaf_id,
        v."timestamp",
        v."onedayFlood_Area_km",
        v."onedayperc_Area",
        v."fivedayFlood_Area_km",
        v."fivedayperc_Area"
    FROM summary_viirs v
    WHERE v."timestamp" = p_ts
    ORDER BY v.pfaf_id;
END;
$$;


-- =============================================================================
-- DFO — single watershed lookup
-- =============================================================================

CREATE OR REPLACE FUNCTION fn_get_dfo(p_ts TIMESTAMPTZ, p_pfaf_id INTEGER)
RETURNS TABLE (
    pfaf_id                    INTEGER,
    "timestamp"                TIMESTAMPTZ,
    "1-Day_TotalArea_km2"      DOUBLE PRECISION,
    "1-Day_perc_Area"          DOUBLE PRECISION,
    "1-Day_CS_TotalArea_km2"   DOUBLE PRECISION,
    "1-Day_CS_perc_Area"       DOUBLE PRECISION,
    "2-Day_TotalArea_km2"      DOUBLE PRECISION,
    "2-Day_perc_Area"          DOUBLE PRECISION,
    "3-Day_TotalArea_km2"      DOUBLE PRECISION,
    "3-Day_perc_Area"          DOUBLE PRECISION
) LANGUAGE plpgsql AS $$
BEGIN
    -- Case 1: timestamp not in table — return nothing
    IF NOT EXISTS (
        SELECT 1 FROM summary_dfo WHERE "timestamp" = p_ts
    ) THEN
        RETURN;
    END IF;

    -- Cases 2 & 3: timestamp exists — real row or synthesised zero row
    RETURN QUERY
    SELECT
        p_pfaf_id,
        p_ts,
        COALESCE(d."1-Day_TotalArea_km2",    0.0),
        COALESCE(d."1-Day_perc_Area",        0.0),
        COALESCE(d."1-Day_CS_TotalArea_km2", 0.0),
        COALESCE(d."1-Day_CS_perc_Area",     0.0),
        COALESCE(d."2-Day_TotalArea_km2",    0.0),
        COALESCE(d."2-Day_perc_Area",        0.0),
        COALESCE(d."3-Day_TotalArea_km2",    0.0),
        COALESCE(d."3-Day_perc_Area",        0.0)
    FROM (SELECT 1) dummy
    LEFT JOIN summary_dfo d
        ON d."timestamp" = p_ts
       AND d.pfaf_id     = p_pfaf_id;
END;
$$;


-- =============================================================================
-- DFO — all rows for a given timestamp
-- Returns only pfaf_ids that have real data for p_ts.
-- =============================================================================

CREATE OR REPLACE FUNCTION fn_get_dfo_batch(p_ts TIMESTAMPTZ)
RETURNS TABLE (
    pfaf_id                    INTEGER,
    "timestamp"                TIMESTAMPTZ,
    "1-Day_TotalArea_km2"      DOUBLE PRECISION,
    "1-Day_perc_Area"          DOUBLE PRECISION,
    "1-Day_CS_TotalArea_km2"   DOUBLE PRECISION,
    "1-Day_CS_perc_Area"       DOUBLE PRECISION,
    "2-Day_TotalArea_km2"      DOUBLE PRECISION,
    "2-Day_perc_Area"          DOUBLE PRECISION,
    "3-Day_TotalArea_km2"      DOUBLE PRECISION,
    "3-Day_perc_Area"          DOUBLE PRECISION
) LANGUAGE plpgsql AS $$
BEGIN
    RETURN QUERY
    SELECT
        d.pfaf_id,
        d."timestamp",
        d."1-Day_TotalArea_km2",
        d."1-Day_perc_Area",
        d."1-Day_CS_TotalArea_km2",
        d."1-Day_CS_perc_Area",
        d."2-Day_TotalArea_km2",
        d."2-Day_perc_Area",
        d."3-Day_TotalArea_km2",
        d."3-Day_perc_Area"
    FROM summary_dfo d
    WHERE d."timestamp" = p_ts
    ORDER BY d.pfaf_id;
END;
$$;


-- =============================================================================
-- GloFAS — all stations for a given watershed (pfaf_id) and timestamp
--
-- Join chain:
--   summary_glofas
--     → all_glofas_stations  ON matching_id_station  (station metadata)
--     → watershed_shapes     ON pfaf_id              (area, ISO, Admin0/1, scores)
--
-- Note: one pfaf_id may have multiple stations; all are returned.
-- =============================================================================

CREATE OR REPLACE FUNCTION fn_get_glofas(p_ts TIMESTAMPTZ, p_pfaf_id INTEGER)
RETURNS TABLE (
    "timestamp"          TIMESTAMPTZ,
    matching_id_station  INTEGER,
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
    -- from all_glofas_stations
    "Station"            TEXT,
    "Basin"              TEXT,
    "Country"            TEXT,
    "Country_code"       VARCHAR(8),
    "Continent"          TEXT,
    "Location"           TEXT,
    "Lat"                NUMERIC(8,3),
    "Lon"                NUMERIC(8,3),
    "Upstream area"      NUMERIC(15,3),
    -- from watershed_shapes
    "area_km2"           DOUBLE PRECISION,
    "ISO"                VARCHAR(8),
    "Admin0"             TEXT,
    "Admin1"             TEXT,
    "rfr_score"          DOUBLE PRECISION,
    "cfr_score"          DOUBLE PRECISION
) LANGUAGE plpgsql AS $$
BEGIN
    RETURN QUERY
    SELECT
        g."timestamp",
        g.matching_id_station,
        g.pfaf_id,
        g."ID",
        g."Point No",
        g."Alert_level",
        g."Days_until_peak",
        g."GloFAS_2yr",
        g."GloFAS_5yr",
        g."GloFAS_20yr",
        g."max_EPS",
        g."Forecast Date",
        -- station metadata
        s."Station",
        s."Basin",
        s."Country",
        s."Country_code",
        s."Continent",
        s."Location",
        s."Lat",
        s."Lon",
        s."Upstream area",
        -- watershed geometry metadata
        ws."area_km2",
        ws."ISO",
        ws."Admin0",
        ws."Admin1",
        ws."rfr_score",
        ws."cfr_score"
    FROM summary_glofas g
    JOIN all_glofas_stations s
        ON s.matching_id_station = g.matching_id_station
    JOIN watershed_shapes ws
        ON ws.pfaf_id = g.pfaf_id
    WHERE g."timestamp" = p_ts
      AND g.pfaf_id     = p_pfaf_id
    ORDER BY g.matching_id_station;
END;
$$;


-- =============================================================================
-- GloFAS — all stations for a given timestamp
-- =============================================================================

CREATE OR REPLACE FUNCTION fn_get_glofas_batch(p_ts TIMESTAMPTZ)
RETURNS TABLE (
    "timestamp"          TIMESTAMPTZ,
    matching_id_station  INTEGER,
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
    -- from all_glofas_stations
    "Station"            TEXT,
    "Basin"              TEXT,
    "Country"            TEXT,
    "Country_code"       VARCHAR(8),
    "Continent"          TEXT,
    "Location"           TEXT,
    "Lat"                NUMERIC(8,3),
    "Lon"                NUMERIC(8,3),
    "Upstream area"      NUMERIC(15,3),
    -- from watershed_shapes
    "area_km2"           DOUBLE PRECISION,
    "ISO"                VARCHAR(8),
    "Admin0"             TEXT,
    "Admin1"             TEXT,
    "rfr_score"          DOUBLE PRECISION,
    "cfr_score"          DOUBLE PRECISION
) LANGUAGE plpgsql AS $$
BEGIN
    RETURN QUERY
    SELECT
        g."timestamp",
        g.matching_id_station,
        g.pfaf_id,
        g."ID",
        g."Point No",
        g."Alert_level",
        g."Days_until_peak",
        g."GloFAS_2yr",
        g."GloFAS_5yr",
        g."GloFAS_20yr",
        g."max_EPS",
        g."Forecast Date",
        s."Station",
        s."Basin",
        s."Country",
        s."Country_code",
        s."Continent",
        s."Location",
        s."Lat",
        s."Lon",
        s."Upstream area",
        ws."area_km2",
        ws."ISO",
        ws."Admin0",
        ws."Admin1",
        ws."rfr_score",
        ws."cfr_score"
    FROM summary_glofas g
    JOIN all_glofas_stations s
        ON s.matching_id_station = g.matching_id_station
    JOIN watershed_shapes ws
        ON ws.pfaf_id = g.pfaf_id
    WHERE g."timestamp" = p_ts
    ORDER BY g.pfaf_id, g.matching_id_station;
END;
$$;


-- =============================================================================
-- Final Alert — single watershed lookup
--
-- Join chain:
--   summary_final_alert
--     → all_watersheds   ON matching_id_watershed  (name, centroid, admin info)
--     → watershed_shapes ON pfaf_id                (area, ISO, Admin0/1, scores)
-- =============================================================================

CREATE OR REPLACE FUNCTION fn_get_final_alert(p_ts TIMESTAMPTZ, p_pfaf_id INTEGER)
RETURNS TABLE (
    "timestamp"                 TIMESTAMPTZ,
    matching_id_watershed       INTEGER,
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
    -- from all_watersheds
    "name"                      TEXT,
    "name_1"                    TEXT,
    "CentroidX"                 NUMERIC(10,6),
    "CentroidY"                 NUMERIC(10,6),
    "Admin1_count"              INTEGER,
    "Admin1_names"              TEXT,
    -- from watershed_shapes
    "area_km2"                  DOUBLE PRECISION,
    "ISO"                       VARCHAR(8),
    "Admin0"                    TEXT,
    "Admin1"                    TEXT,
    "rfr_score_shp"             DOUBLE PRECISION,
    "cfr_score_shp"             DOUBLE PRECISION
) LANGUAGE plpgsql AS $$
BEGIN
    RETURN QUERY
    SELECT
        f."timestamp",
        f.matching_id_watershed,
        f.pfaf_id,
        f."rfr_score",
        f."cfr_score",
        f."Alert_level",
        f."Days_until_peak",
        f."GloFAS_2yr",
        f."GloFAS_5yr",
        f."GloFAS_20yr",
        f."Alert_Score",
        f."PeakArrivalScore",
        f."TwoYScore",
        f."FiveYScore",
        f."TwtyYScore",
        f."Sum_Score_x",
        f."GFMS_TotalArea_km",
        f."GFMS_perc_Area",
        f."GFMS_MeanDepth",
        f."GFMS_MaxDepth",
        f."GFMS_Duration",
        f."GFMS_area_score",
        f."GFMS_perc_area_score",
        f."MeanD_Score",
        f."MaxD_Score",
        f."Duration_Score",
        f."Sum_Score_y",
        f."MOM_Score",
        f."Hazard_Score",
        f."Scaled_Riverine_Risk",
        f."Scaled_Coastal_Risk",
        f."Flag",
        f."1-Day_TotalArea_km2",
        f."1-Day_perc_Area",
        f."1-Day_CS_TotalArea_km2",
        f."1-Day_CS_perc_Area",
        f."2-Day_TotalArea_km2",
        f."2-Day_perc_Area",
        f."3-Day_TotalArea_km2",
        f."3-Day_perc_Area",
        f."DFO_area_1day_score",
        f."DFO_percarea_1day_score",
        f."DFO_area_2day_score",
        f."DFO_percarea_2day_score",
        f."DFO_area_3day_score",
        f."DFO_percarea_3day_score",
        f."DFOTotal_Score",
        f."onedayFlood_Area_km",
        f."onedayperc_Area",
        f."fivedayFlood_Area_km",
        f."fivedayperc_Area",
        f."VIIRS_area_1day_score",
        f."VIIRS_percarea_1day_score",
        f."VIIRS_area_5day_score",
        f."VIIRS_percarea_5day_score",
        f."VIIRSTotal_Score",
        f."Severity",
        f."Alert",
        f."Status",
        -- watershed admin metadata
        w."name",
        w."name_1",
        w."CentroidX",
        w."CentroidY",
        w."Admin1_count",
        w."Admin1_names",
        -- watershed geometry metadata
        ws."area_km2",
        ws."ISO",
        ws."Admin0",
        ws."Admin1",
        ws."rfr_score",
        ws."cfr_score"
    FROM summary_final_alert f
    JOIN all_watersheds w
        ON w.matching_id_watershed = f.matching_id_watershed
    JOIN watershed_shapes ws
        ON ws.pfaf_id = f.pfaf_id
    WHERE f."timestamp" = p_ts
      AND f.pfaf_id     = p_pfaf_id;
END;
$$;


-- =============================================================================
-- Final Alert — all watersheds for a given timestamp
-- =============================================================================

CREATE OR REPLACE FUNCTION fn_get_final_alert_batch(p_ts TIMESTAMPTZ)
RETURNS TABLE (
    "timestamp"                 TIMESTAMPTZ,
    matching_id_watershed       INTEGER,
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
    -- from all_watersheds
    "name"                      TEXT,
    "name_1"                    TEXT,
    "CentroidX"                 NUMERIC(10,6),
    "CentroidY"                 NUMERIC(10,6),
    "Admin1_count"              INTEGER,
    "Admin1_names"              TEXT,
    -- from watershed_shapes
    "area_km2"                  DOUBLE PRECISION,
    "ISO"                       VARCHAR(8),
    "Admin0"                    TEXT,
    "Admin1"                    TEXT,
    "rfr_score_shp"             DOUBLE PRECISION,
    "cfr_score_shp"             DOUBLE PRECISION
) LANGUAGE plpgsql AS $$
BEGIN
    RETURN QUERY
    SELECT
        f."timestamp",
        f.matching_id_watershed,
        f.pfaf_id,
        f."rfr_score",
        f."cfr_score",
        f."Alert_level",
        f."Days_until_peak",
        f."GloFAS_2yr",
        f."GloFAS_5yr",
        f."GloFAS_20yr",
        f."Alert_Score",
        f."PeakArrivalScore",
        f."TwoYScore",
        f."FiveYScore",
        f."TwtyYScore",
        f."Sum_Score_x",
        f."GFMS_TotalArea_km",
        f."GFMS_perc_Area",
        f."GFMS_MeanDepth",
        f."GFMS_MaxDepth",
        f."GFMS_Duration",
        f."GFMS_area_score",
        f."GFMS_perc_area_score",
        f."MeanD_Score",
        f."MaxD_Score",
        f."Duration_Score",
        f."Sum_Score_y",
        f."MOM_Score",
        f."Hazard_Score",
        f."Scaled_Riverine_Risk",
        f."Scaled_Coastal_Risk",
        f."Flag",
        f."1-Day_TotalArea_km2",
        f."1-Day_perc_Area",
        f."1-Day_CS_TotalArea_km2",
        f."1-Day_CS_perc_Area",
        f."2-Day_TotalArea_km2",
        f."2-Day_perc_Area",
        f."3-Day_TotalArea_km2",
        f."3-Day_perc_Area",
        f."DFO_area_1day_score",
        f."DFO_percarea_1day_score",
        f."DFO_area_2day_score",
        f."DFO_percarea_2day_score",
        f."DFO_area_3day_score",
        f."DFO_percarea_3day_score",
        f."DFOTotal_Score",
        f."onedayFlood_Area_km",
        f."onedayperc_Area",
        f."fivedayFlood_Area_km",
        f."fivedayperc_Area",
        f."VIIRS_area_1day_score",
        f."VIIRS_percarea_1day_score",
        f."VIIRS_area_5day_score",
        f."VIIRS_percarea_5day_score",
        f."VIIRSTotal_Score",
        f."Severity",
        f."Alert",
        f."Status",
        w."name",
        w."name_1",
        w."CentroidX",
        w."CentroidY",
        w."Admin1_count",
        w."Admin1_names",
        ws."area_km2",
        ws."ISO",
        ws."Admin0",
        ws."Admin1",
        ws."rfr_score",
        ws."cfr_score"
    FROM summary_final_alert f
    JOIN all_watersheds w
        ON w.matching_id_watershed = f.matching_id_watershed
    JOIN watershed_shapes ws
        ON ws.pfaf_id = f.pfaf_id
    WHERE f."timestamp" = p_ts
    ORDER BY f.pfaf_id;
END;
$$;
