-- current server: https://mom.tg-ear190027.projects.jetstream-cloud.org/ModelofModels/

-- Enable PostGIS extension
CREATE EXTENSION IF NOT EXISTS postgis;

-- ============================================================
-- Watershed Shapes: must be created first — all other tables
-- reference watershed_shapes(pfaf_id) as a foreign key.
-- One polygon per watershed from Watershed_pfaf_id.shp.
-- Columns mirror the shapefile schema exactly (WGS84 / EPSG:4326).
-- ============================================================
CREATE TABLE IF NOT EXISTS watershed_shapes (
    pfaf_id                      INTEGER         PRIMARY KEY,
    "area_km2"                   DOUBLE PRECISION,
    "ISO"                        VARCHAR(8),
    "Admin0"                     TEXT,
    "Admin1"                     TEXT,
    "rfr_score"                  DOUBLE PRECISION,
    "cfr_score"                  DOUBLE PRECISION,
    "Resilience_Index"           DOUBLE PRECISION,
    "NormalizedLackofResilience" DOUBLE PRECISION,
    geom                         GEOMETRY(MultiPolygon, 4326)
);

CREATE INDEX IF NOT EXISTS idx_watershed_shapes_geom
    ON watershed_shapes USING GIST (geom);


-- ============================================================
-- Reference tables
-- ============================================================

-- All GloFAS stations: static per-station metadata
-- Lat/Lon use NUMERIC(8,3) rather than DOUBLE PRECISION so that equality
-- comparisons in the unique constraint are always exact (GloFAS coordinates
-- are always 3 decimal places; binary float can produce false mismatches).
CREATE TABLE IF NOT EXISTS all_glofas_stations (
    matching_id_station INTEGER         PRIMARY KEY,
    "Station"           TEXT,
    "Basin"             TEXT,
    "Country"           TEXT,
    "Country_code"      VARCHAR(3),
    "Continent"         TEXT,
    "Location"          TEXT,
    "Lat"               NUMERIC(8,3),
    "Lon"               NUMERIC(8,3),
    "Upstream area"     NUMERIC(15,3),
    pfaf_id             INTEGER         REFERENCES watershed_shapes(pfaf_id),
    CONSTRAINT uq_station UNIQUE NULLS NOT DISTINCT ("Station", "Country", "Lat", "Lon", pfaf_id)
);

-- All Watersheds: static per-watershed metadata
-- CentroidX/CentroidY use NUMERIC(10,6) rather than DOUBLE PRECISION so that
-- equality comparisons in the unique constraint are always exact. 6 decimal
-- places matches the precision in the source data (~0.1 m resolution).
-- pfaf_id may appear more than once (one row per country slice of the watershed).
CREATE TABLE IF NOT EXISTS all_watersheds (
    matching_id_watershed INTEGER         PRIMARY KEY,
    pfaf_id               INTEGER         REFERENCES watershed_shapes(pfaf_id),
    "name"                TEXT,
    "name_1"              TEXT,
    "CentroidX"           NUMERIC(10,6),
    "CentroidY"           NUMERIC(10,6),
    "Admin1_count"        INTEGER,
    "Admin1_names"        TEXT,
    CONSTRAINT uq_watershed UNIQUE (pfaf_id, "name", "name_1", "CentroidX", "CentroidY")
);


-- ============================================================
-- History tables: one row per (entity, timestamp) per batch
-- ============================================================

-- GFMS (8 csvs per day, every 3h)
-- image (1-4 tiffs per day (inconsistent): Flood_byStore)
CREATE TABLE IF NOT EXISTS summary_gfms (
    pfaf_id              INTEGER         REFERENCES watershed_shapes(pfaf_id),
    "timestamp"          TIMESTAMPTZ,
    "GFMS_TotalArea_km"  DOUBLE PRECISION,
    "GFMS_perc_Area"     DOUBLE PRECISION,
    "GFMS_MeanDepth"     DOUBLE PRECISION,
    "GFMS_MaxDepth"      DOUBLE PRECISION,
    "GFMS_Duration"      INTEGER,
    created_at           TIMESTAMPTZ     DEFAULT NULL,
    updated_at           TIMESTAMPTZ     DEFAULT NULL,
    PRIMARY KEY ("timestamp", pfaf_id)
);

-- HWRF (1-4 csvs per day, inconsistent)
CREATE TABLE IF NOT EXISTS summary_hwrf (
    pfaf_id              INTEGER         REFERENCES watershed_shapes(pfaf_id),
    "timestamp"          TIMESTAMPTZ,
    "Rain_TotalArea_km"  DOUBLE PRECISION,
    "perc_Area"          DOUBLE PRECISION,
    "MeanRain"           DOUBLE PRECISION,
    "MaxRain"            DOUBLE PRECISION,
    created_at           TIMESTAMPTZ     DEFAULT NULL,
    updated_at           TIMESTAMPTZ     DEFAULT NULL,
    PRIMARY KEY ("timestamp", pfaf_id)
);

-- VIIRS (1 csv per day)
-- image (2 tiffs per day: 1day, 5day)
CREATE TABLE IF NOT EXISTS summary_viirs (
    pfaf_id                  INTEGER         REFERENCES watershed_shapes(pfaf_id),
    "timestamp"              TIMESTAMPTZ,
    "onedayFlood_Area_km"    DOUBLE PRECISION,
    "onedayperc_Area"        DOUBLE PRECISION,
    "fivedayFlood_Area_km"   DOUBLE PRECISION,
    "fivedayperc_Area"       DOUBLE PRECISION,
    created_at               TIMESTAMPTZ     DEFAULT NULL,
    updated_at               TIMESTAMPTZ     DEFAULT NULL,
    PRIMARY KEY ("timestamp", pfaf_id)
);

-- DFO (1 csv per day)
-- image (1 tiff per day (inconsistent, some days are missing): Flood_3-Day_250m)
CREATE TABLE IF NOT EXISTS summary_dfo (
    pfaf_id                   INTEGER         REFERENCES watershed_shapes(pfaf_id),
    "timestamp"               TIMESTAMPTZ,
    "1-Day_TotalArea_km2"     DOUBLE PRECISION,
    "1-Day_perc_Area"         DOUBLE PRECISION,
    "1-Day_CS_TotalArea_km2"  DOUBLE PRECISION,
    "1-Day_CS_perc_Area"      DOUBLE PRECISION,
    "2-Day_TotalArea_km2"     DOUBLE PRECISION,
    "2-Day_perc_Area"         DOUBLE PRECISION,
    "3-Day_TotalArea_km2"     DOUBLE PRECISION,
    "3-Day_perc_Area"         DOUBLE PRECISION,
    created_at                TIMESTAMPTZ     DEFAULT NULL,
    updated_at                TIMESTAMPTZ     DEFAULT NULL,
    PRIMARY KEY ("timestamp", pfaf_id)
);

-- GloFAS merged: dynamic per-timestamp forecast data (1 csv, 1 geojson per day)
CREATE TABLE IF NOT EXISTS summary_glofas (
    "timestamp"         TIMESTAMPTZ,
    matching_id_station INTEGER         REFERENCES all_glofas_stations(matching_id_station),
    pfaf_id             INTEGER         REFERENCES watershed_shapes(pfaf_id),
    "ID"                TEXT,
    "Point No"          INTEGER,
    "Alert_level"       INTEGER,
    "Days_until_peak"   INTEGER,
    "GloFAS_2yr"        DOUBLE PRECISION,
    "GloFAS_5yr"        DOUBLE PRECISION,
    "GloFAS_20yr"       DOUBLE PRECISION,
    "max_EPS"           TEXT,
    "Forecast Date"     TIMESTAMP,
    created_at          TIMESTAMPTZ     DEFAULT NULL,
    updated_at          TIMESTAMPTZ     DEFAULT NULL,
    PRIMARY KEY ("timestamp", matching_id_station)
);

-- Final Alert: dynamic per-timestamp alert data (4 csvs per day)
CREATE TABLE IF NOT EXISTS summary_final_alert (
    "timestamp"                 TIMESTAMPTZ,
    matching_id_watershed       INTEGER         REFERENCES all_watersheds(matching_id_watershed),
    pfaf_id                     INTEGER         REFERENCES watershed_shapes(pfaf_id),
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
    created_at                  TIMESTAMPTZ     DEFAULT NULL,
    updated_at                  TIMESTAMPTZ     DEFAULT NULL,
    PRIMARY KEY ("timestamp", matching_id_watershed)
);


-- ============================================================
-- MoM tables (Attributes_Clean): one row per (pfaf_id, timestamp)
-- Four stages: GFMS → HWRF → DFO → VIIRS
-- Columns in watershed_shapes (area, ISO, Admin0, Admin1,
-- rfr_score, cfr_score) are excluded here.
-- ============================================================

-- GFMS MoM (Attributes_Clean_YYYYMMDD.csv base + Final_Attributes_YYYYMMDD.csv enrichment)
-- Resilience_Index / NormalizedLackofResilience are backfilled to watershed_shapes and
-- not stored here. No Flag column at the GFMS stage.
CREATE TABLE IF NOT EXISTS mom_gfms (
    pfaf_id                      INTEGER         REFERENCES watershed_shapes(pfaf_id),
    "timestamp"                  TIMESTAMPTZ,
    "FID"                        DOUBLE PRECISION,
    "Alert"                      TEXT,
    -- GloFAS scores (sparse — only when GloFAS has an active signal)
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
    -- GFMS raw values and scores
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
    -- Composite scores
    "Hazard_Score"               DOUBLE PRECISION,
    "Scaled_Riverine_Risk"       DOUBLE PRECISION,
    "Scaled_Coastal_Risk"        DOUBLE PRECISION,
    "Severity"                   DOUBLE PRECISION,
    created_at                   TIMESTAMPTZ     DEFAULT NULL,
    updated_at                   TIMESTAMPTZ     DEFAULT NULL,
    PRIMARY KEY ("timestamp", pfaf_id)
);

-- HWRF MoM (Attributes_Clean_YYYYMMDDHHHWRFUpdated.csv base + Final_Attributes enrichment)
-- Stores only what is new at the HWRF stage. GloFAS/GFMS columns are in mom_gfms.
-- Resilience_Index / NormalizedLackofResilience are backfilled to watershed_shapes.
CREATE TABLE IF NOT EXISTS mom_hwrf (
    pfaf_id                      INTEGER         REFERENCES watershed_shapes(pfaf_id),
    "timestamp"                  TIMESTAMPTZ,
    "FID"                        DOUBLE PRECISION,
    "Alert"                      TEXT,
    "Flag"                       TEXT,
    -- HWRF raw values and scores (new at this stage)
    "Rain_TotalArea_km"          DOUBLE PRECISION,
    "perc_Area"                  DOUBLE PRECISION,
    "MeanRain"                   DOUBLE PRECISION,
    "MaxRain"                    DOUBLE PRECISION,
    "HWRF_area_score"            DOUBLE PRECISION,
    "HWRF_percarea_score"        DOUBLE PRECISION,
    "MeanRain_Score"             DOUBLE PRECISION,
    "MaxRain_Score"              DOUBLE PRECISION,
    "HWRFTot_Score"              DOUBLE PRECISION,
    -- Updated composite scores
    "MOM_Score"                  DOUBLE PRECISION,
    "Hazard_Score"               DOUBLE PRECISION,
    "Severity"                   DOUBLE PRECISION,
    created_at                   TIMESTAMPTZ     DEFAULT NULL,
    updated_at                   TIMESTAMPTZ     DEFAULT NULL,
    PRIMARY KEY ("timestamp", pfaf_id)
);

-- DFO MoM (Attributes_Clean_YYYYMMDDHHMOM+DFOUpdated.csv base + Final_Attributes enrichment)
-- Stores only what is new at the DFO stage. GloFAS/GFMS columns are in mom_gfms;
-- HWRF columns are in mom_hwrf.
-- Resilience_Index / NormalizedLackofResilience are backfilled to watershed_shapes.
CREATE TABLE IF NOT EXISTS mom_dfo (
    pfaf_id                      INTEGER         REFERENCES watershed_shapes(pfaf_id),
    "timestamp"                  TIMESTAMPTZ,
    "FID"                        DOUBLE PRECISION,
    "Alert"                      TEXT,
    "Flag"                       TEXT,
    -- DFO raw flood areas (new at this stage)
    "1-Day_TotalArea_km2"        DOUBLE PRECISION,
    "1-Day_perc_Area"            DOUBLE PRECISION,
    "1-Day_CS_TotalArea_km2"     DOUBLE PRECISION,
    "1-Day_CS_perc_Area"         DOUBLE PRECISION,
    "2-Day_TotalArea_km2"        DOUBLE PRECISION,
    "2-Day_perc_Area"            DOUBLE PRECISION,
    "3-Day_TotalArea_km2"        DOUBLE PRECISION,
    "3-Day_perc_Area"            DOUBLE PRECISION,
    -- DFO scoring (new at this stage)
    "DFO_area_1day_score"        DOUBLE PRECISION,
    "DFO_percarea_1day_score"    DOUBLE PRECISION,
    "DFO_area_2day_score"        DOUBLE PRECISION,
    "DFO_percarea_2day_score"    DOUBLE PRECISION,
    "DFO_area_3day_score"        DOUBLE PRECISION,
    "DFO_percarea_3day_score"    DOUBLE PRECISION,
    "DFOTotal_Score"             DOUBLE PRECISION,
    -- Updated composite scores
    "Hazard_Score"               DOUBLE PRECISION,
    "Severity"                   DOUBLE PRECISION,
    created_at                   TIMESTAMPTZ     DEFAULT NULL,
    updated_at                   TIMESTAMPTZ     DEFAULT NULL,
    PRIMARY KEY ("timestamp", pfaf_id)
);

-- VIIRS MoM (Attributes_clean_YYYYMMDDHHWRF+MOM+DFO+VIIRSUpdated.csv base + Final_Attributes enrichment)
-- Stores only what is new at the VIIRS stage. Earlier stage columns are in mom_gfms/hwrf/dfo.
-- Resilience_Index / NormalizedLackofResilience are backfilled to watershed_shapes.
CREATE TABLE IF NOT EXISTS mom_viirs (
    pfaf_id                      INTEGER         REFERENCES watershed_shapes(pfaf_id),
    "timestamp"                  TIMESTAMPTZ,
    "FID"                        DOUBLE PRECISION,
    "Alert"                      TEXT,
    "Flag"                       TEXT,
    -- VIIRS raw values and scores (new at this stage)
    "onedayFlood_Area_km"        DOUBLE PRECISION,
    "onedayperc_Area"            DOUBLE PRECISION,
    "fivedayFlood_Area_km"       DOUBLE PRECISION,
    "fivedayperc_Area"           DOUBLE PRECISION,
    "VIIRS_area_1day_score"      DOUBLE PRECISION,
    "VIIRS_percarea_1day_score"  DOUBLE PRECISION,
    "VIIRS_area_5day_score"      DOUBLE PRECISION,
    "VIIRS_percarea_5day_score"  DOUBLE PRECISION,
    "VIIRSTotal_Score"           DOUBLE PRECISION,
    -- Updated composite scores
    "Hazard_Score"               DOUBLE PRECISION,
    "Severity"                   DOUBLE PRECISION,
    created_at                   TIMESTAMPTZ     DEFAULT NULL,
    updated_at                   TIMESTAMPTZ     DEFAULT NULL,
    PRIMARY KEY ("timestamp", pfaf_id)
);


-- ============================================================
-- "Latest" tables: one row per entity, most recent snapshot
-- ============================================================

-- GFMS MoM Latest
CREATE TABLE IF NOT EXISTS mom_gfms_latest (
    "timestamp"                  TIMESTAMPTZ,
    pfaf_id                      INTEGER         PRIMARY KEY REFERENCES watershed_shapes(pfaf_id),
    "FID"                        DOUBLE PRECISION,
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
    "Severity"                   DOUBLE PRECISION,
    created_at                   TIMESTAMPTZ     DEFAULT NULL,
    updated_at                   TIMESTAMPTZ     DEFAULT NULL
);

-- HWRF MoM Latest
CREATE TABLE IF NOT EXISTS mom_hwrf_latest (
    "timestamp"                  TIMESTAMPTZ,
    pfaf_id                      INTEGER         PRIMARY KEY REFERENCES watershed_shapes(pfaf_id),
    "FID"                        DOUBLE PRECISION,
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
    "Severity"                   DOUBLE PRECISION,
    created_at                   TIMESTAMPTZ     DEFAULT NULL,
    updated_at                   TIMESTAMPTZ     DEFAULT NULL
);

-- DFO MoM Latest
CREATE TABLE IF NOT EXISTS mom_dfo_latest (
    "timestamp"                  TIMESTAMPTZ,
    pfaf_id                      INTEGER         PRIMARY KEY REFERENCES watershed_shapes(pfaf_id),
    "FID"                        DOUBLE PRECISION,
    "Alert"                      TEXT,
    "Flag"                       TEXT,
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
    "Severity"                   DOUBLE PRECISION,
    created_at                   TIMESTAMPTZ     DEFAULT NULL,
    updated_at                   TIMESTAMPTZ     DEFAULT NULL
);

-- VIIRS MoM Latest
CREATE TABLE IF NOT EXISTS mom_viirs_latest (
    "timestamp"                  TIMESTAMPTZ,
    pfaf_id                      INTEGER         PRIMARY KEY REFERENCES watershed_shapes(pfaf_id),
    "FID"                        DOUBLE PRECISION,
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
    "Severity"                   DOUBLE PRECISION,
    created_at                   TIMESTAMPTZ     DEFAULT NULL,
    updated_at                   TIMESTAMPTZ     DEFAULT NULL
);


-- GFMS Latest
CREATE TABLE IF NOT EXISTS summary_gfms_latest (
    "timestamp"          TIMESTAMPTZ,
    pfaf_id              INTEGER         PRIMARY KEY REFERENCES watershed_shapes(pfaf_id),
    "GFMS_TotalArea_km"  DOUBLE PRECISION,
    "GFMS_perc_Area"     DOUBLE PRECISION,
    "GFMS_MeanDepth"     DOUBLE PRECISION,
    "GFMS_MaxDepth"      DOUBLE PRECISION,
    "GFMS_Duration"      INTEGER,
    created_at           TIMESTAMPTZ     DEFAULT NULL,
    updated_at           TIMESTAMPTZ     DEFAULT NULL
);

-- HWRF Latest
CREATE TABLE IF NOT EXISTS summary_hwrf_latest (
    "timestamp"          TIMESTAMPTZ,
    pfaf_id              INTEGER         PRIMARY KEY REFERENCES watershed_shapes(pfaf_id),
    "Rain_TotalArea_km"  DOUBLE PRECISION,
    "perc_Area"          DOUBLE PRECISION,
    "MeanRain"           DOUBLE PRECISION,
    "MaxRain"            DOUBLE PRECISION,
    created_at           TIMESTAMPTZ     DEFAULT NULL,
    updated_at           TIMESTAMPTZ     DEFAULT NULL
);

-- GloFAS Latest: forecast data only — station metadata lives in all_glofas_stations.
-- PK is matching_id_station because multiple stations can map to the same
-- pfaf_id (watershed); pfaf_id alone is not unique within a batch.
CREATE TABLE IF NOT EXISTS summary_glofas_latest (
    matching_id_station  INTEGER         PRIMARY KEY REFERENCES all_glofas_stations(matching_id_station),
    "timestamp"          TIMESTAMPTZ,
    pfaf_id              INTEGER         REFERENCES watershed_shapes(pfaf_id),
    "ID"                 TEXT,
    "Point No"           INTEGER,
    "Alert_level"        INTEGER,
    "Days_until_peak"    INTEGER,
    "GloFAS_2yr"         DOUBLE PRECISION,
    "GloFAS_5yr"         DOUBLE PRECISION,
    "GloFAS_20yr"        DOUBLE PRECISION,
    "max_EPS"            TEXT,
    "Forecast Date"      TIMESTAMP,
    created_at           TIMESTAMPTZ     DEFAULT NULL,
    updated_at           TIMESTAMPTZ     DEFAULT NULL
);

-- VIIRS Latest
CREATE TABLE IF NOT EXISTS summary_viirs_latest (
    "timestamp"              TIMESTAMPTZ,
    pfaf_id                  INTEGER         PRIMARY KEY REFERENCES watershed_shapes(pfaf_id),
    "onedayFlood_Area_km"    DOUBLE PRECISION,
    "onedayperc_Area"        DOUBLE PRECISION,
    "fivedayFlood_Area_km"   DOUBLE PRECISION,
    "fivedayperc_Area"       DOUBLE PRECISION,
    created_at               TIMESTAMPTZ     DEFAULT NULL,
    updated_at               TIMESTAMPTZ     DEFAULT NULL
);

-- DFO Latest
CREATE TABLE IF NOT EXISTS summary_dfo_latest (
    "timestamp"               TIMESTAMPTZ,
    pfaf_id                   INTEGER         PRIMARY KEY REFERENCES watershed_shapes(pfaf_id),
    "1-Day_TotalArea_km2"     DOUBLE PRECISION,
    "1-Day_perc_Area"         DOUBLE PRECISION,
    "1-Day_CS_TotalArea_km2"  DOUBLE PRECISION,
    "1-Day_CS_perc_Area"      DOUBLE PRECISION,
    "2-Day_TotalArea_km2"     DOUBLE PRECISION,
    "2-Day_perc_Area"         DOUBLE PRECISION,
    "3-Day_TotalArea_km2"     DOUBLE PRECISION,
    "3-Day_perc_Area"         DOUBLE PRECISION,
    created_at                TIMESTAMPTZ     DEFAULT NULL,
    updated_at                TIMESTAMPTZ     DEFAULT NULL
);

-- Final Alert Latest: alert data only — watershed metadata lives in all_watersheds,
-- risk scores live in watershed_shapes.
-- PK is matching_id_watershed because a single pfaf_id can appear multiple times
-- (one row per country slice of the watershed); pfaf_id alone is not unique.
CREATE TABLE IF NOT EXISTS summary_final_alert_latest (
    matching_id_watershed       INTEGER         PRIMARY KEY REFERENCES all_watersheds(matching_id_watershed),
    "timestamp"                 TIMESTAMPTZ,
    pfaf_id                     INTEGER         REFERENCES watershed_shapes(pfaf_id),
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
    created_at                  TIMESTAMPTZ     DEFAULT NULL,
    updated_at                  TIMESTAMPTZ     DEFAULT NULL
);


-- ============================================================
-- Shared row-level timestamp trigger
-- Sets created_at on INSERT, updated_at on UPDATE.
-- Apply to all history and _latest tables.
-- ============================================================

CREATE OR REPLACE FUNCTION fn_set_timestamps()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        NEW.created_at = NOW();
    ELSIF TG_OP = 'UPDATE' THEN
        NEW.updated_at = NOW();
    END IF;
    RETURN NEW;
END;
$$;

-- History tables
CREATE TRIGGER trg_summary_gfms_ts           BEFORE INSERT OR UPDATE ON summary_gfms           FOR EACH ROW EXECUTE FUNCTION fn_set_timestamps();
CREATE TRIGGER trg_summary_hwrf_ts           BEFORE INSERT OR UPDATE ON summary_hwrf           FOR EACH ROW EXECUTE FUNCTION fn_set_timestamps();
CREATE TRIGGER trg_summary_viirs_ts          BEFORE INSERT OR UPDATE ON summary_viirs          FOR EACH ROW EXECUTE FUNCTION fn_set_timestamps();
CREATE TRIGGER trg_summary_dfo_ts            BEFORE INSERT OR UPDATE ON summary_dfo            FOR EACH ROW EXECUTE FUNCTION fn_set_timestamps();
CREATE TRIGGER trg_summary_glofas_ts         BEFORE INSERT OR UPDATE ON summary_glofas         FOR EACH ROW EXECUTE FUNCTION fn_set_timestamps();
CREATE TRIGGER trg_summary_final_alert_ts    BEFORE INSERT OR UPDATE ON summary_final_alert    FOR EACH ROW EXECUTE FUNCTION fn_set_timestamps();
CREATE TRIGGER trg_mom_gfms_ts               BEFORE INSERT OR UPDATE ON mom_gfms               FOR EACH ROW EXECUTE FUNCTION fn_set_timestamps();
CREATE TRIGGER trg_mom_hwrf_ts               BEFORE INSERT OR UPDATE ON mom_hwrf               FOR EACH ROW EXECUTE FUNCTION fn_set_timestamps();
CREATE TRIGGER trg_mom_dfo_ts                BEFORE INSERT OR UPDATE ON mom_dfo                FOR EACH ROW EXECUTE FUNCTION fn_set_timestamps();
CREATE TRIGGER trg_mom_viirs_ts              BEFORE INSERT OR UPDATE ON mom_viirs              FOR EACH ROW EXECUTE FUNCTION fn_set_timestamps();

-- Latest tables
CREATE TRIGGER trg_summary_gfms_latest_ts         BEFORE INSERT OR UPDATE ON summary_gfms_latest         FOR EACH ROW EXECUTE FUNCTION fn_set_timestamps();
CREATE TRIGGER trg_summary_hwrf_latest_ts         BEFORE INSERT OR UPDATE ON summary_hwrf_latest         FOR EACH ROW EXECUTE FUNCTION fn_set_timestamps();
CREATE TRIGGER trg_summary_viirs_latest_ts        BEFORE INSERT OR UPDATE ON summary_viirs_latest        FOR EACH ROW EXECUTE FUNCTION fn_set_timestamps();
CREATE TRIGGER trg_summary_dfo_latest_ts          BEFORE INSERT OR UPDATE ON summary_dfo_latest          FOR EACH ROW EXECUTE FUNCTION fn_set_timestamps();
CREATE TRIGGER trg_summary_glofas_latest_ts       BEFORE INSERT OR UPDATE ON summary_glofas_latest       FOR EACH ROW EXECUTE FUNCTION fn_set_timestamps();
CREATE TRIGGER trg_summary_final_alert_latest_ts  BEFORE INSERT OR UPDATE ON summary_final_alert_latest  FOR EACH ROW EXECUTE FUNCTION fn_set_timestamps();
CREATE TRIGGER trg_mom_gfms_latest_ts             BEFORE INSERT OR UPDATE ON mom_gfms_latest             FOR EACH ROW EXECUTE FUNCTION fn_set_timestamps();
CREATE TRIGGER trg_mom_hwrf_latest_ts             BEFORE INSERT OR UPDATE ON mom_hwrf_latest             FOR EACH ROW EXECUTE FUNCTION fn_set_timestamps();
CREATE TRIGGER trg_mom_dfo_latest_ts              BEFORE INSERT OR UPDATE ON mom_dfo_latest              FOR EACH ROW EXECUTE FUNCTION fn_set_timestamps();
CREATE TRIGGER trg_mom_viirs_latest_ts            BEFORE INSERT OR UPDATE ON mom_viirs_latest            FOR EACH ROW EXECUTE FUNCTION fn_set_timestamps();
