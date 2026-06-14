-- ============================================================
-- History Views
-- Each view enriches its base table with reference data joined
-- strictly via the reference table's own primary key:
--   watershed_shapes    PK: pfaf_id              → geometry/shape data
--   all_watersheds      PK: matching_id_watershed → watershed metadata
--   all_glofas_stations PK: matching_id_station   → station metadata
--
-- pfaf_id is used only to join watershed_shapes.
-- Tables that lack matching_id_watershed or matching_id_station
-- do not join all_watersheds or all_glofas_stations.
--
-- feature_id is a stable unique string key (pfaf_id + timestamp)
-- used as the OGC API Features id_field.
-- ============================================================


-- ----------------------------------------------------------
-- view_summary_gfms
-- Joins: watershed_shapes (pfaf_id)
-- ----------------------------------------------------------
CREATE OR REPLACE VIEW view_summary_gfms AS
SELECT
    (g.pfaf_id::text || '_' || to_char(g."timestamp", 'YYYYMMDDHH24MISS')) AS feature_id,
    g.*,
    ws.area_km2,
    ws."ISO",
    ws."Admin0",
    ws."Admin1",
    ws.rfr_score,
    ws.cfr_score,
    ws."Resilience_Index",
    ws."NormalizedLackofResilience",
    ws.geom
FROM summary_gfms g
JOIN watershed_shapes ws ON ws.pfaf_id = g.pfaf_id;


-- ----------------------------------------------------------
-- view_summary_hwrf
-- Joins: watershed_shapes (pfaf_id)
-- ----------------------------------------------------------
CREATE OR REPLACE VIEW view_summary_hwrf AS
SELECT
    (g.pfaf_id::text || '_' || to_char(g."timestamp", 'YYYYMMDDHH24MISS')) AS feature_id,
    g.*,
    ws.area_km2,
    ws."ISO",
    ws."Admin0",
    ws."Admin1",
    ws.rfr_score,
    ws.cfr_score,
    ws."Resilience_Index",
    ws."NormalizedLackofResilience",
    ws.geom
FROM summary_hwrf g
JOIN watershed_shapes ws ON ws.pfaf_id = g.pfaf_id;


-- ----------------------------------------------------------
-- view_summary_viirs
-- Joins: watershed_shapes (pfaf_id)
-- ----------------------------------------------------------
CREATE OR REPLACE VIEW view_summary_viirs AS
SELECT
    (g.pfaf_id::text || '_' || to_char(g."timestamp", 'YYYYMMDDHH24MISS')) AS feature_id,
    g.*,
    ws.area_km2,
    ws."ISO",
    ws."Admin0",
    ws."Admin1",
    ws.rfr_score,
    ws.cfr_score,
    ws."Resilience_Index",
    ws."NormalizedLackofResilience",
    ws.geom
FROM summary_viirs g
JOIN watershed_shapes ws ON ws.pfaf_id = g.pfaf_id;


-- ----------------------------------------------------------
-- view_summary_dfo
-- Joins: watershed_shapes (pfaf_id)
-- ----------------------------------------------------------
CREATE OR REPLACE VIEW view_summary_dfo AS
SELECT
    (g.pfaf_id::text || '_' || to_char(g."timestamp", 'YYYYMMDDHH24MISS')) AS feature_id,
    g.*,
    ws.area_km2,
    ws."ISO",
    ws."Admin0",
    ws."Admin1",
    ws.rfr_score,
    ws.cfr_score,
    ws."Resilience_Index",
    ws."NormalizedLackofResilience",
    ws.geom
FROM summary_dfo g
JOIN watershed_shapes ws ON ws.pfaf_id = g.pfaf_id;


-- ----------------------------------------------------------
-- view_summary_glofas
-- Joins: all_glofas_stations (matching_id_station)
--        watershed_shapes    (pfaf_id)
-- Uses matching_id_station in feature_id since pfaf_id is nullable here.
-- ----------------------------------------------------------
CREATE OR REPLACE VIEW view_summary_glofas AS
SELECT
    (g.matching_id_station::text || '_' || to_char(g."timestamp", 'YYYYMMDDHH24MISS')) AS feature_id,
    g.*,
    s."Station",
    s."Basin",
    s."Country",
    s."Country_code",
    s."Continent",
    s."Location",
    s."Lat",
    s."Lon",
    s."Upstream area",
    ws.area_km2,
    ws."ISO",
    ws."Admin0",
    ws."Admin1",
    ws.rfr_score,
    ws.cfr_score,
    ws."Resilience_Index",
    ws."NormalizedLackofResilience",
    ws.geom
FROM summary_glofas g
JOIN all_glofas_stations s ON s.matching_id_station = g.matching_id_station
LEFT JOIN watershed_shapes ws ON ws.pfaf_id = g.pfaf_id;


-- ----------------------------------------------------------
-- view_summary_final_alert
-- Joins: all_watersheds   (matching_id_watershed)
--        watershed_shapes (pfaf_id)
-- ----------------------------------------------------------
CREATE OR REPLACE VIEW view_summary_final_alert AS
SELECT
    (f.pfaf_id::text || '_' || to_char(f."timestamp", 'YYYYMMDDHH24MISS')) AS feature_id,
    f.pfaf_id,
    f."timestamp",
    f."Alert",
    f.matching_id_watershed,
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
    f."Status",
    f.created_at,
    f.updated_at,
    aw."name",
    aw."name_1",
    aw."CentroidX",
    aw."CentroidY",
    aw."Admin1_count",
    aw."Admin1_names",
    ws.area_km2,
    ws."ISO",
    ws."Admin0",
    ws."Admin1",
    ws.rfr_score,
    ws.cfr_score,
    ws."Resilience_Index",
    ws."NormalizedLackofResilience",
    ws.geom
FROM summary_final_alert f
JOIN all_watersheds aw ON aw.matching_id_watershed = f.matching_id_watershed
LEFT JOIN watershed_shapes ws ON ws.pfaf_id = f.pfaf_id;


-- ----------------------------------------------------------
-- view_mom_gfms
-- Joins: watershed_shapes (pfaf_id)
-- ----------------------------------------------------------
CREATE OR REPLACE VIEW view_mom_gfms AS
SELECT
    (g.pfaf_id::text || '_' || to_char(g."timestamp", 'YYYYMMDDHH24MISS')) AS feature_id,
    g.pfaf_id,
    g."timestamp",
    g."Alert",
    g."FID",
    g."Alert_level",
    g."Days_until_peak",
    g."GloFAS_2yr",
    g."GloFAS_5yr",
    g."GloFAS_20yr",
    g."Alert_Score",
    g."PeakArrivalScore",
    g."TwoYScore",
    g."FiveYScore",
    g."TwtyYScore",
    g."Sum_Score_x",
    g."GFMS_TotalArea_km",
    g."GFMS_perc_Area",
    g."GFMS_MeanDepth",
    g."GFMS_MaxDepth",
    g."GFMS_Duration",
    g."GFMS_area_score",
    g."GFMS_perc_area_score",
    g."MeanD_Score",
    g."MaxD_Score",
    g."Duration_Score",
    g."Sum_Score_y",
    g."Hazard_Score",
    g."Scaled_Riverine_Risk",
    g."Scaled_Coastal_Risk",
    g."Severity",
    g.created_at,
    g.updated_at,
    ws.area_km2,
    ws."ISO",
    ws."Admin0",
    ws."Admin1",
    ws.rfr_score,
    ws.cfr_score,
    ws."Resilience_Index",
    ws."NormalizedLackofResilience",
    ws.geom
FROM mom_gfms g
JOIN watershed_shapes ws ON ws.pfaf_id = g.pfaf_id;


-- ----------------------------------------------------------
-- view_mom_hwrf
-- Joins: watershed_shapes (pfaf_id)
-- ----------------------------------------------------------
CREATE OR REPLACE VIEW view_mom_hwrf AS
SELECT
    (g.pfaf_id::text || '_' || to_char(g."timestamp", 'YYYYMMDDHH24MISS')) AS feature_id,
    g.pfaf_id,
    g."timestamp",
    g."Alert",
    g."FID",
    g."Flag",
    g."Rain_TotalArea_km",
    g."perc_Area",
    g."MeanRain",
    g."MaxRain",
    g."HWRF_area_score",
    g."HWRF_percarea_score",
    g."MeanRain_Score",
    g."MaxRain_Score",
    g."HWRFTot_Score",
    g."MOM_Score",
    g."Hazard_Score",
    g."Severity",
    g.created_at,
    g.updated_at,
    ws.area_km2,
    ws."ISO",
    ws."Admin0",
    ws."Admin1",
    ws.rfr_score,
    ws.cfr_score,
    ws."Resilience_Index",
    ws."NormalizedLackofResilience",
    ws.geom
FROM mom_hwrf g
JOIN watershed_shapes ws ON ws.pfaf_id = g.pfaf_id;


-- ----------------------------------------------------------
-- view_mom_dfo
-- Joins: watershed_shapes (pfaf_id)
-- ----------------------------------------------------------
CREATE OR REPLACE VIEW view_mom_dfo AS
SELECT
    (g.pfaf_id::text || '_' || to_char(g."timestamp", 'YYYYMMDDHH24MISS')) AS feature_id,
    g.pfaf_id,
    g."timestamp",
    g."Alert",
    g."FID",
    g."Flag",
    g."1-Day_TotalArea_km2",
    g."1-Day_perc_Area",
    g."1-Day_CS_TotalArea_km2",
    g."1-Day_CS_perc_Area",
    g."2-Day_TotalArea_km2",
    g."2-Day_perc_Area",
    g."3-Day_TotalArea_km2",
    g."3-Day_perc_Area",
    g."DFO_area_1day_score",
    g."DFO_percarea_1day_score",
    g."DFO_area_2day_score",
    g."DFO_percarea_2day_score",
    g."DFO_area_3day_score",
    g."DFO_percarea_3day_score",
    g."DFOTotal_Score",
    g."Hazard_Score",
    g."Severity",
    g.created_at,
    g.updated_at,
    ws.area_km2,
    ws."ISO",
    ws."Admin0",
    ws."Admin1",
    ws.rfr_score,
    ws.cfr_score,
    ws."Resilience_Index",
    ws."NormalizedLackofResilience",
    ws.geom
FROM mom_dfo g
JOIN watershed_shapes ws ON ws.pfaf_id = g.pfaf_id;


-- ----------------------------------------------------------
-- view_mom_viirs
-- Joins: watershed_shapes (pfaf_id)
-- ----------------------------------------------------------
CREATE OR REPLACE VIEW view_mom_viirs AS
SELECT
    (g.pfaf_id::text || '_' || to_char(g."timestamp", 'YYYYMMDDHH24MISS')) AS feature_id,
    g.pfaf_id,
    g."timestamp",
    g."Alert",
    g."FID",
    g."Flag",
    g."onedayFlood_Area_km",
    g."onedayperc_Area",
    g."fivedayFlood_Area_km",
    g."fivedayperc_Area",
    g."VIIRS_area_1day_score",
    g."VIIRS_percarea_1day_score",
    g."VIIRS_area_5day_score",
    g."VIIRS_percarea_5day_score",
    g."VIIRSTotal_Score",
    g."Hazard_Score",
    g."Severity",
    g.created_at,
    g.updated_at,
    ws.area_km2,
    ws."ISO",
    ws."Admin0",
    ws."Admin1",
    ws.rfr_score,
    ws.cfr_score,
    ws."Resilience_Index",
    ws."NormalizedLackofResilience",
    ws.geom
FROM mom_viirs g
JOIN watershed_shapes ws ON ws.pfaf_id = g.pfaf_id;
