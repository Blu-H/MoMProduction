"""
HWRF_MoM.py
    -- HWRF and MoM integration
"""

import csv
import glob
import logging
import os
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd
import requests

import settings
from processing.gfms.GFMS_MoM import gfms_scores
from processing.utilities import (
    find_latest_glofas,
    find_latest_viirs,
    get_current_processing_datehour,
    get_latestitems,
    hafs_storms,
    hwrf_today,
    read_data,
    severity_from_hazard_and_risk_scores,
    write_empty_rain_summary,
)


def mofunc_hwrf(row):
    if row["Severity"] >= 0.8 or row["Hazard_Score"] >= 80:
        return "Warning"
    elif row["Severity"] >= 0.6 or row["Hazard_Score"] >= 60:
        return "Watch"
    elif row["Severity"] >= 0.35 or row["Hazard_Score"] >= 35:
        return "Advisory"
    elif row["Severity"] > 0 or row["Hazard_Score"] > 0:
        return "Information"


def mofunc_dfo(row):
    if row["Severity"] >= 0.8 or row["Hazard_Score"] >= 80:
        return "Warning"
    elif row["Severity"] >= 0.6 or row["Hazard_Score"] >= 60:
        return "Watch"
    elif row["Severity"] >= 0.35 or row["Hazard_Score"] >= 35:
        return "Advisory"
    elif row["Severity"] > 0 or row["Hazard_Score"] > 0:
        return "Information"


def mofunc_viirs(row):
    if row["Severity"] >= 0.8 or row["Hazard_Score"] >= 80:
        return "Warning"
    elif row["Severity"] >= 0.6 or row["Hazard_Score"] >= 60:
        return "Watch"
    elif row["Severity"] >= 0.35 or row["Hazard_Score"] >= 35:
        return "Advisory"
    elif row["Severity"] > 0 or row["Hazard_Score"] > 0:
        return "Information"


# the previous cycle's HWRF rainfall is waited for until it is this old; after
# that the MoM is written without it
HWRF_MISSING_AFTER = timedelta(hours=12)
# from this age, a missing cycle that neither the HWRF host nor HAFS has any
# storm for gets an empty summary right away
HWRF_NO_STORMS_AFTER = timedelta(hours=6)


def hwrf_host_has_cycle(hwrf_cycle):
    """True/False from the HWRF host listings, None if they cannot be read
    (the host answers 403 both for a missing cycle and when rate limiting)"""
    host = settings.config.get("hwrf", "HOST").rstrip("/")
    day = f"hwrf.{hwrf_cycle[:8]}/"
    try:
        top = requests.get(f"{host}/", timeout=60)
        if top.status_code != 200:
            return None
        if f'href="{day}"' not in top.text:
            return False
        listing = requests.get(f"{host}/{day}", timeout=60)
        if listing.status_code != 200:
            return None
        return f'href="{hwrf_cycle[8:]}/"' in listing.text
    except requests.exceptions.RequestException:
        return None


def no_storms_published(hwrf_cycle):
    """True only when both hosts confirm there are no storms for the cycle:
    the HWRF host has no such cycle and HAFS lists no storms for it"""
    if not settings.HAFS_ENABLED:
        return False
    try:
        if hafs_storms(hwrf_cycle):
            return False
    except requests.exceptions.RequestException:
        return False
    return hwrf_host_has_cycle(hwrf_cycle) is False


def previous_rain_ready(hwrf_cycle, now=None):
    """True when the MoM can use, or go on without, the HWRF rainfall of
    hwrf_cycle (YYYYMMDDHH): its summary exists (empty when there was no
    rain), no storm is published for it (an empty summary is written then),
    or it is HWRF_MISSING_AFTER old"""
    hwrf_sum = os.path.join(
        settings.HWRF_SUM_DIR, f"{settings.HWRF_SUM_PREFIX}.{hwrf_cycle}rainfall.csv"
    )
    if os.path.exists(hwrf_sum):
        return True
    now = now or datetime.now(timezone.utc)
    age = now - datetime.strptime(hwrf_cycle, "%Y%m%d%H").replace(tzinfo=timezone.utc)
    if age >= HWRF_MISSING_AFTER:
        return True
    if age >= HWRF_NO_STORMS_AFTER and no_storms_published(hwrf_cycle):
        write_empty_rain_summary(hwrf_sum)
        logging.info(
            f"HWRF {hwrf_cycle}: no storms on the HWRF host or in HAFS, empty "
            f"summary written: {hwrf_sum}"
        )
        return True
    return False


def update_HWRF_MoM(adate):
    """HWRF MoM for a date: YYYYMMDDHH"""
    print(f"___________update_HWRF_MoM: {adate}")

    gfms_sum = os.path.join(settings.GFMS_SUM_DIR, "Flood_byStor_{}.csv".format(adate))
    glofas_sum = os.path.join(
        settings.GLOFAS_DIR, "threspoints_{}00.csv".format(adate[:-2])
    )
    # use the HWRF rainfall of the previous cycle: the current cycle's rainfall
    # is only published hours after the cycle time
    hwrf_cycle = (datetime.strptime(adate, "%Y%m%d%H") - timedelta(hours=6)).strftime(
        "%Y%m%d%H"
    )
    hwrf_sum = os.path.join(
        settings.HWRF_SUM_DIR, f"{settings.HWRF_SUM_PREFIX}.{hwrf_cycle}rainfall.csv"
    )

    # wait for the previous cycle's rainfall unless it is long overdue: a MoM
    # written without it is final and would not be redone when it arrives
    if not previous_rain_ready(hwrf_cycle):
        logging.info(
            f"HWRF MoM {adate}: rainfall of the previous cycle {hwrf_cycle} not "
            f"processed yet, waiting (written without it once "
            f"{HWRF_MISSING_AFTER.total_seconds() / 3600:.0f}h old)"
        )
        return

    # first check if file exists
    if not os.path.exists(gfms_sum):
        logging.warning(f"GFMS summary not found: {gfms_sum}")
        logging.info(f"calling GFMS_fixdate for: {adate[:8]}")
        from processing.gfms.GFMS_tool import GFMS_fixdate

        GFMS_fixdate(adate[:8])

    # if it's processed early in the day, older Glofas file will be used
    if not os.path.exists(glofas_sum) or int(adate[8:10]) < 10:
        glofas_latest = find_latest_glofas(settings.GLOFAS_DIR, adate, "csv")
        if glofas_latest:
            glofas_sum = os.path.join(settings.GLOFAS_DIR, glofas_latest)
            logging.warning(
                f"GloFAS for {adate}: using the previous available " f"{glofas_latest}"
            )
        elif os.path.exists(glofas_sum):
            # no earlier GloFAS to fall back to, use the same day file
            logging.warning(
                f"GloFAS for {adate}: no earlier file, using the same day "
                f"{os.path.basename(glofas_sum)}"
            )
        else:
            logging.error(f"no GloFAS available for {adate}, HWRF MoM skipped")
            return

    # previous cycle not available, continue without HWRF
    if not os.path.exists(hwrf_sum):
        logging.warning(
            f"no HWRF rainfall of the previous cycle {hwrf_cycle} for {adate}, "
            f"continuing without HWRF"
        )

    # hwrf_sum may not have
    Final_Attributes_csv = os.path.join(
        settings.HWRF_MOM_DIR,
        f"Final_Attributes_{adate}{settings.HWRF_FILE_TAG}Updated.csv",
    )
    Attributes_Clean_csv = os.path.join(
        settings.HWRF_MOM_DIR,
        f"Attributes_Clean_{adate}{settings.HWRF_FILE_TAG}Updated.csv",
    )

    # already processed
    if os.path.exists(Final_Attributes_csv) and os.path.exists(Attributes_Clean_csv):
        logging.info(f"HWRF MoM already processed: {adate}")
        return
    else:
        logging.info(f"processing HWRF MoM: {adate}")
        logging.info(
            f"HWRF MoM inputs for {adate}: "
            f"gfms={os.path.basename(str(gfms_sum))}, "
            f"glofas={os.path.basename(str(glofas_sum))}, "
            f"hwrf={os.path.basename(str(hwrf_sum))}"
        )

    weightage = read_data(os.path.join(settings.BASE_DATA_DIR, "GFMS_Weightage.csv"))
    HWRF_weightage = read_data(
        os.path.join(settings.BASE_DATA_DIR, "HWRF_Weightage.csv")
    )
    add_field_GloFas = [
        "Alert_Score",
        "PeakArrivalScore",
        "TwoYScore",
        "FiveYScore",
        "TwtyYScore",
        "Sum_Score",
    ]
    add_field_HWRF = [
        "HWRF_area_score",
        "HWRF_percarea_score",
        "MeanRain_Score",
        "MaxRain_Score",
        "HWRFTot_Score",
    ]

    # Read GFMS Processing data and calculte score
    GFMS_w_score_csv = "GFMS_w_score_{}.csv".format(adate)
    GFMS_w_score_csv = os.path.join(settings.HWRF_PROC_DIR, GFMS_w_score_csv)
    gfms_scores(gfms_sum, GFMS_w_score_csv)

    ##Read GloFas data and Calculate score
    with open(glofas_sum, "r", encoding="UTF-8") as GloFas_file:
        GloFas_reader = csv.reader(GloFas_file)
        GloFas_w_score_csv = "GloFas_w_score_{}.csv".format(adate)
        GloFas_w_score_csv = os.path.join(settings.HWRF_PROC_DIR, GloFas_w_score_csv)
        GloFas_Error_csv = "GloFas_Error_{}.csv".format(adate)
        GloFas_Error_csv = os.path.join(settings.HWRF_PROC_DIR, GloFas_Error_csv)
        csvfile = open(GloFas_w_score_csv, "w", newline="\n", encoding="utf-8")
        txtfile = open(GloFas_Error_csv, "w", newline="\n")
        GloFas_w_score = csv.writer(csvfile)
        errorfile = csv.writer(txtfile)
        row_count = 1
        error_flag = False
        for row in GloFas_reader:
            # GloFAS writes -9999 for the 2/5/20 yr EPS when no exceedance is forecast
            if row_count > 1:
                row[9:12] = ["0" if float(x) < 0 else x for x in row[9:12]]
            if row_count == 1:
                for x in add_field_GloFas:
                    row.append(x)
                write = [
                    row[14],
                    row[12],
                    row[13],
                    row[9],
                    row[10],
                    row[11],
                    row[15],
                    row[16],
                    row[17],
                    row[18],
                    row[19],
                    row[20],
                ]
                GloFas_w_score.writerow(write)
                errorfile.writerow([row[0], row[1], row[14], "Error"])
                row_count = row_count + 1
            elif float(row[12]) > 3 or float(row[12]) < 0:
                error = "Alert less than 0 or greater than 3 is encountered"
                errorfile.writerow([row[0], row[1], row[14], error])
                error_flag = True
            elif float(row[9]) > 100:
                error = "2 yr EPS greater than 100 is encountered"
                errorfile.writerow([row[0], row[1], row[14], error])
                error_flag = True
            elif float(row[10]) > 100:
                error = "5 yr EPS greater than 100 is encountered"
                errorfile.writerow([row[0], row[1], row[14], error])
                error_flag = True
            elif float(row[11]) > 100:
                error = "20 yr EPS greater than 100 is encountered"
                errorfile.writerow([row[0], row[1], row[14], error])
                error_flag = True
            elif float(row[13]) > 30:
                error = "Peak arrival days greater than 30 is encountered"
                errorfile.writerow([row[0], row[1], row[14], error])
                error_flag = True
            else:
                Alert_Score = str(
                    round(float(row[12]) * float(weightage.Alert_score[0]))
                )
                TwoYScore = str(float(row[9]) / float(weightage.EPS_Twoyear_wt[0]))
                FiveYScore = str(float(row[10]) / float(weightage.EPS_Fiveyear_wt[0]))
                TwtyYScore = str(float(row[11]) / float(weightage.EPS_Twtyyear_wt[0]))
                if (
                    int(row[9]) == 0
                    and int(row[10]) == 0
                    and int(row[11]) == 0
                    and int(row[12]) == 0
                ):
                    PeakArrival_Score = str(0)
                elif int(row[13]) == 10 or int(row[13]) > 10:
                    PeakArrival_Score = str(1)
                elif int(row[13]) == 9:
                    PeakArrival_Score = str(2)
                elif int(row[13]) == 8:
                    PeakArrival_Score = str(3)
                elif int(row[13]) == 7:
                    PeakArrival_Score = str(4)
                elif int(row[13]) == 6:
                    PeakArrival_Score = str(5)
                elif int(row[13]) == 5:
                    PeakArrival_Score = str(6)
                elif int(row[13]) == 4:
                    PeakArrival_Score = str(7)
                elif int(row[13]) == 3:
                    PeakArrival_Score = str(8)
                elif int(row[13]) == 2:
                    PeakArrival_Score = str(9)
                elif int(row[13]) == 1:
                    PeakArrival_Score = str(10)
                Sum_Score = str(
                    float(Alert_Score)
                    + float(PeakArrival_Score)
                    + float(TwoYScore)
                    + float(FiveYScore)
                    + float(TwtyYScore)
                )
                score_field = [
                    Alert_Score,
                    PeakArrival_Score,
                    TwoYScore,
                    FiveYScore,
                    TwtyYScore,
                    Sum_Score,
                ]
                for x in score_field:
                    row.append(x)
                write = [
                    row[14],
                    row[12],
                    row[13],
                    row[9],
                    row[10],
                    row[11],
                    row[15],
                    row[16],
                    row[17],
                    row[18],
                    row[19],
                    row[20],
                ]
                GloFas_w_score.writerow(write)

    csvfile.close()
    txtfile.close()
    if not error_flag:
        os.remove(GloFas_Error_csv)
    GloFas = read_data(GloFas_w_score_csv)
    GloFas.sort_values(by="pfaf_id", ascending=True, inplace=True)
    GloFas_w_score_sort_csv = "GloFas_w_score_sort_{}.csv".format(adate)
    GloFas_w_score_sort_csv = os.path.join(
        settings.HWRF_PROC_DIR, GloFas_w_score_sort_csv
    )
    GloFas.set_index("pfaf_id").to_csv(GloFas_w_score_sort_csv, encoding="utf-8")

    with open(GloFas_w_score_sort_csv, "r") as GloFas_file:
        GloFas_reader = csv.reader(GloFas_file)
        GloFas_w_Avgscore_csv = "GloFas_w_Avgscore_{}.csv".format(adate)
        GloFas_w_Avgscore_csv = os.path.join(
            settings.HWRF_PROC_DIR, GloFas_w_Avgscore_csv
        )
        csvfile = open(GloFas_w_Avgscore_csv, "w", newline="\n", encoding="utf-8")
        GloFas_w_score = csv.writer(csvfile)
        Haz_Score = 0
        pfaf_id = -1
        similarity = 0
        i = 1
        To_be_written = "False"
        write = []
        for row in GloFas_reader:
            if i == 1:
                i = i + 1
                GloFas_w_score.writerow(row)
            else:
                if pfaf_id == -1 or pfaf_id == row[0]:
                    pfaf_id = row[0]
                    Haz_Score = Haz_Score + float(row[11])
                    similarity = similarity + 1
                    last_row = row
                    To_be_written = "True"
                else:
                    last_row[11] = str(Haz_Score / similarity)
                    GloFas_w_score.writerow(last_row)
                    last_row = row
                    pfaf_id = row[0]
                    Haz_Score = float(row[11])
                    similarity = 1
                    To_be_written = "True"
    if To_be_written == "True":
        last_row[11] = str(Haz_Score / similarity)
        GloFas_w_score.writerow(last_row)
    csvfile.close()
    # Glofas Done
    os.remove(GloFas_w_score_sort_csv)

    ## Read HWRF rainfall processed data and calculate separate hazard Score
    try:
        with open(hwrf_sum, "r", encoding="UTF-8") as HWRF_file:
            logging.info(f"using: {hwrf_sum}")
            HWRF_reader = csv.reader(HWRF_file)
            HWRF_w_score_csv = f"{settings.HWRF_FILE_TAG}_w_score_{adate}.csv"
            HWRF_w_score_csv = os.path.join(settings.HWRF_PROC_DIR, HWRF_w_score_csv)
            csvfile = open(HWRF_w_score_csv, "w", newline="\n", encoding="utf-8")
            HWRF_w_score = csv.writer(csvfile)
            row_count = 1
            # csv_writer = csv.writer(write_obj)
            for row in HWRF_reader:
                if row_count == 1:
                    for x in add_field_HWRF:
                        row.append(x)
                    HWRF_w_score.writerow(row)
                    row_count = row_count + 1
                elif row == []:
                    continue
                else:
                    if float(row[1]) / float(HWRF_weightage.HWRF_Area_wt[0]) > float(
                        HWRF_weightage.HWRF_Area_max_pt[0]
                    ):
                        HWRF_area_score = str(float(HWRF_weightage.HWRF_Area_max_pt[0]))
                    else:
                        HWRF_area_score = str(
                            float(HWRF_weightage.HWRF_Area_Min_pt[0])
                            * float(row[1])
                            / float(HWRF_weightage.HWRF_Area_wt[0])
                        )
                    if float(row[2]) / float(
                        HWRF_weightage.HWRF_percArea_wt[0]
                    ) > float(HWRF_weightage.HWRF_percArea_Maxpt[0]):
                        HWRF_percarea_score = str(
                            float(HWRF_weightage.HWRF_percArea_Maxpt[0])
                        )
                    else:
                        HWRF_percarea_score = str(
                            float(HWRF_weightage.HWRF_percArea_Minpt[0])
                            * float(row[2])
                            / float(HWRF_weightage.HWRF_percArea_wt[0])
                        )
                    if float(row[3]) >= float(HWRF_weightage.HWRF_MeanRain_minwt[0]):
                        if (
                            (
                                float(row[3])
                                - float(HWRF_weightage.HWRF_MeanRain_minwt[0])
                            )
                            / float(HWRF_weightage.HWRF_MeanRain_increment[0])
                        ) + float(HWRF_weightage.HWRF_MeanRain_Minpt[0]) > float(
                            HWRF_weightage.HWRF_MeanRain_Maxpt[0]
                        ):
                            MeanRain_Score = str(
                                float(HWRF_weightage.HWRF_MeanRain_Maxpt[0])
                            )
                        else:
                            MeanRain_Score = str(
                                (
                                    (
                                        float(row[3])
                                        - float(HWRF_weightage.HWRF_MeanRain_minwt[0])
                                    )
                                    / float(HWRF_weightage.HWRF_MeanRain_increment[0])
                                )
                                + float(HWRF_weightage.HWRF_MeanRain_Minpt[0])
                            )
                    else:
                        MeanRain_Score = "0"
                    if float(row[4]) >= float(HWRF_weightage.HWRF_MaxRain_minwt[0]):
                        if (
                            (
                                float(row[4])
                                - float(HWRF_weightage.HWRF_MaxRain_minwt[0])
                            )
                            / float(HWRF_weightage.HWRF_MaxRain_increment[0])
                        ) + float(HWRF_weightage.HWRF_MaxRain_Minpt[0]) > float(
                            HWRF_weightage.HWRF_MaxRain_Maxpt[0]
                        ):
                            MaxRain_Score = str(
                                float(HWRF_weightage.HWRF_MaxRain_Maxpt[0])
                            )
                        else:
                            MaxRain_Score = str(
                                (
                                    (
                                        float(row[4])
                                        - float(HWRF_weightage.HWRF_MaxRain_minwt[0])
                                    )
                                    / float(HWRF_weightage.HWRF_MaxRain_increment[0])
                                )
                                + float(HWRF_weightage.HWRF_MaxRain_Minpt[0])
                            )
                    else:
                        MaxRain_Score = "0"
                    # only count rain area that reaches mean or max, otherwise it
                    # counts large area covered with barely any rain
                    if float(MeanRain_Score) == 0 and float(MaxRain_Score) == 0:
                        HWRF_area_score = "0"
                        HWRF_percarea_score = "0"
                    HWRFTot_Score = (
                        float(HWRF_area_score)
                        + float(HWRF_percarea_score)
                        + float(MeanRain_Score)
                        + float(MaxRain_Score)
                    ) * 2.5
                    results_list = [
                        row[0],
                        row[1],
                        row[2],
                        row[3],
                        row[4],
                        HWRF_area_score,
                        HWRF_percarea_score,
                        MeanRain_Score,
                        MaxRain_Score,
                        HWRFTot_Score,
                    ]
                    HWRF_w_score.writerow(results_list)
            csvfile.close()
    except Exception as e:
        if os.path.exists(hwrf_sum):
            logging.warning(f"HWRF scoring failed for {adate}, skipping HWRF: {e}")

    GFMS = read_data(GFMS_w_score_csv)
    GloFas = read_data(GloFas_w_Avgscore_csv)
    Attributes = read_data(os.path.join(settings.BASE_DATA_DIR, "Attributes.csv"))
    # HWRF=read_data('HWRF_w_score.csv')
    join = pd.merge(
        GloFas.set_index("pfaf_id"),
        GFMS.set_index("pfaf_id"),
        on="pfaf_id",
        how="outer",
    )
    # join0=pd.merge(join, HWRF.set_index('pfaf_id'), on='pfaf_id', how='outer')
    PDC_resilience = read_data(
        os.path.join(settings.BASE_DATA_DIR, "Resilience_Index.csv")
    )
    # left, not inner: the resilience columns feed no formula, and an inner
    # join dropped 21 watersheds whose ISO is missing from Resilience_Index.csv
    join1 = pd.merge(
        Attributes,
        PDC_resilience[["ISO", "Resilience_Index", " NormalizedLackofResilience "]],
        on="ISO",
        how="left",
    )
    # Final_Attributes = pd.merge(join1.set_index('pfaf_id'), join0, on='pfaf_id', how='outer')
    Final_Attributes = pd.merge(
        join1.set_index("pfaf_id"), join, on="pfaf_id", how="outer"
    )
    Final_Attributes[["Sum_Score_x", "Sum_Score_y"]] = Final_Attributes[
        ["Sum_Score_x", "Sum_Score_y"]
    ].fillna(value=0)
    Final_Attributes.loc[Final_Attributes["Sum_Score_y"] == 0, "Sum_Score_x"] = (
        Final_Attributes.loc[Final_Attributes["Sum_Score_y"] == 0, "Sum_Score_x"] * 2
    )
    Final_Attributes.loc[Final_Attributes["Sum_Score_x"] == 0, "Sum_Score_y"] = (
        Final_Attributes.loc[Final_Attributes["Sum_Score_x"] == 0, "Sum_Score_y"] * 2
    )
    Final_Attributes = Final_Attributes.assign(
        MOM_Score=lambda x: Final_Attributes["Sum_Score_x"]
        + Final_Attributes["Sum_Score_y"]
    )
    Final_Attributes["Hazard_Score"] = Final_Attributes[["MOM_Score"]]
    try:
        HWRF = read_data(HWRF_w_score_csv)
        Final_Attributes = pd.merge(
            Final_Attributes, HWRF.set_index("pfaf_id"), on="pfaf_id", how="outer"
        )
        Final_Attributes["Flag"] = np.where(
            (Final_Attributes["Hazard_Score"] < Final_Attributes["HWRFTot_Score"]),
            1,
            np.nan,
        ).astype(object)
        Final_Attributes["Hazard_Score"] = Final_Attributes[
            ["Hazard_Score", "HWRFTot_Score"]
        ].max(axis=1)
    except Exception as e:
        if os.path.exists(hwrf_sum):
            logging.warning(f"HWRF merge failed for {adate}, skipping HWRF: {e}")
    # Kept: dropping these also lost the GloFAS/GFMS/rain columns of watersheds
    # a later source keeps. Culled once, at the end of final_alert_pdc.
    # Final_Attributes = Final_Attributes[Final_Attributes.Hazard_Score != 0]
    Final_Attributes.drop(
        Final_Attributes.index[
            (Final_Attributes["rfr_score"] == 0) & (Final_Attributes["cfr_score"] == 0)
        ],
        inplace=True,
    )
    Final_Attributes = Final_Attributes.assign(
        Scaled_Riverine_Risk=lambda x: Final_Attributes["rfr_score"] * 20
    )
    Final_Attributes = Final_Attributes.assign(
        Scaled_Coastal_Risk=lambda x: Final_Attributes["cfr_score"] * 20
    )

    ################# TypeError: loop of ufunc does not support argument 0 of type float which has no callable log method
    cols = [
        "Scaled_Riverine_Risk",
        "Scaled_Coastal_Risk",
        "Hazard_Score",
    ]
    Final_Attributes[cols] = Final_Attributes[cols].apply(
        pd.to_numeric, errors="coerce"
    )

    Final_Attributes["Severity"] = severity_from_hazard_and_risk_scores(
        Final_Attributes
    )
    Final_Attributes["Alert"] = Final_Attributes.apply(mofunc_hwrf, axis=1)
    # Final_Attributes["Flag"] = Final_Attributes["Flag"].astype(object)
    Final_Attributes.loc[Final_Attributes["Alert"] == "Information", "Flag"] = ""
    Final_Attributes.loc[Final_Attributes["Alert"] == "Advisory", "Flag"] = ""
    Final_Attributes.to_csv(Final_Attributes_csv, encoding="utf-8-sig")
    # Final_Attributes.to_csv('Final_Attributes_2021081606.csv', encoding='utf-8-sig')
    Attributes_Clean = pd.merge(
        join1.set_index("pfaf_id"),
        Final_Attributes[["Alert"]],
        on="pfaf_id",
        how="right",
    )
    Attributes_Clean.to_csv(Attributes_Clean_csv, encoding="utf-8-sig")
    logging.info(f"generated: {Final_Attributes_csv}")

    # delete temp files
    os.remove(GloFas_w_score_csv)
    os.remove(GloFas_w_Avgscore_csv)
    os.remove(GFMS_w_score_csv)

    try:
        os.remove(HWRF_w_score_csv)
    except:
        pass

    return


def find_latest_summary(datestr, scanfolder, namepattern, hours):
    """find the latest summary data (DFO), from the start day of the cycle
    back; VIIRS: utilities.find_latest_viirs"""

    # NOTE (cron, to adjust): the day used depends on which summaries exist
    # when the job runs, so it follows the publication times and is not
    # reproducible. From the production logs (Sep-Oct 2026):
    #  - DFO of D is written on D by the 03:00 DFO run, but the 06 and 12
    #    cycles (run at 07:00 / 13:00) only look from D-1 (startd below)
    # turn the datestr into a real date
    da = datetime.strptime(datestr, "%Y%m%d")
    startd = 1
    if hours == "18":
        startd = 0
    # check the data
    for i in range(startd, 10):
        cdate = da - timedelta(days=i)
        cdatestr = cdate.strftime("%Y%m%d")
        cfile = os.path.join(scanfolder, namepattern.format(cdatestr))
        if os.path.exists(cfile):
            return [cdatestr, cfile]

    return ["", ""]


def update_HWRFMoM_DFO_VIIRS(adate):
    """
    update HWRFMoM with the latest available DFO and VIIRS
    """
    os.chdir(settings.HWRF_PROC_DIR)

    # first check if it is produced
    hwrf_pattern = adate + settings.HWRF_FILE_TAG + "+"
    file_list = os.listdir(settings.HWRF_MOM_DIR)
    file_found = [1 for x in file_list if hwrf_pattern in x]
    if len(file_found) > 0:
        # this date is already processed
        # print(file_found)
        return

    # find the latest DFO, VIIRS summary
    datestr = adate[:-2]
    hourstr = adate[-2:]
    # return '' if not found
    [dfo_date, dfo_summary] = find_latest_summary(
        datestr, settings.DFO_SUM_DIR, "DFO_{}.csv", hourstr
    )
    if dfo_date == "":
        return
    [viirs_date, summary_viirs_all] = find_latest_viirs(
        settings.VIIRS_SUM_DIR, datestr, hourstr
    )
    if viirs_date == "":
        return

    # geneate HWRF_DFO_MoM
    MOMOutput = os.path.join(
        settings.HWRF_MOM_DIR,
        f"Final_Attributes_{adate}{settings.HWRF_FILE_TAG}Updated.csv",
    )
    if not os.path.exists(MOMOutput):
        # print('can not find ' + MOMOutput)
        return

    DFO = dfo_summary
    # output
    # Final_Attributes_yyyymmddhhMOM+yyyymmddDFOUpdated.csv
    # Attributes_clean_yyyymmddhhMOM+yyyymmddDFOUpdated.csv
    DFO_Final_Attributes_csv = (
        f"Final_Attributes_{adate}{settings.HWRF_FILE_TAG}+{dfo_date}DFOUpdated.csv"
    )
    DFO_Attributes_Clean_csv = (
        f"Attributes_Clean_{adate}{settings.HWRF_FILE_TAG}+{dfo_date}DFOUpdated.csv"
    )

    weightage = read_data(os.path.join(settings.BASE_DATA_DIR, "DFO_Weightage.csv"))
    Attributes = read_data(os.path.join(settings.BASE_DATA_DIR, "Attributes.csv"))
    PDC_resilience = read_data(
        os.path.join(settings.BASE_DATA_DIR, "Resilience_Index.csv")
    )
    add_field_DFO = [
        "DFO_area_1day_score",
        "DFO_percarea_1day_score",
        "DFO_area_2day_score",
        "DFO_percarea_2day_score",
        "DFO_area_3day_score",
        "DFO_percarea_3day_score",
        "DFOTotal_Score",
    ]

    # Read DFO Processing data and calculate score
    with open(DFO, "r", encoding="UTF-8") as DFO_file:
        DFO_reader = csv.reader(DFO_file)
        DFO_w_score_csv = "DFO_w_score_{}.csv".format(dfo_date)
        csvfile = open(DFO_w_score_csv, "w", newline="\n", encoding="utf-8")
        DFO_w_score = csv.writer(csvfile)
        row_count = 1
        # csv_writer = csv.writer(write_obj)
        for row in DFO_reader:
            if row_count == 1:
                for x in add_field_DFO:
                    row.append(x)
                row_count = row_count + 1
            else:
                if float(row[4]) / float(weightage.DFO_Area_wt[0]) > float(
                    weightage.DFO_Area_max_pt[0]
                ):
                    DFO_area_1day_score = str(
                        float(weightage.DFO_Area_max_pt[0])
                        * float(weightage.one_Day_Multiplier[0])
                    )
                else:
                    DFO_area_1day_score = str(
                        float(weightage.DFO_Area_Min_pt[0])
                        * float(weightage.one_Day_Multiplier[0])
                        * float(row[4])
                        / float(weightage.DFO_Area_wt[0])
                    )
                if float(row[5]) / float(weightage.DFO_percArea_wt[0]) > float(
                    weightage.DFO_percArea_Maxpt[0]
                ):
                    DFO_perc_area_1day_score = str(
                        float(weightage.DFO_percArea_Maxpt[0])
                        * float(weightage.one_Day_Multiplier[0])
                    )
                else:
                    DFO_perc_area_1day_score = str(
                        float(weightage.DFO_percArea_Minpt[0])
                        * float(weightage.one_Day_Multiplier[0])
                        * float(row[5])
                        / float(weightage.DFO_percArea_wt[0])
                    )
                if float(row[6]) / float(weightage.DFO_Area_wt[0]) > float(
                    weightage.DFO_Area_max_pt[0]
                ):
                    DFO_area_2day_score = str(
                        float(weightage.DFO_Area_max_pt[0])
                        * float(weightage.two_Day_Multiplier[0])
                    )
                else:
                    DFO_area_2day_score = str(
                        float(weightage.DFO_Area_Min_pt[0])
                        * float(weightage.two_Day_Multiplier[0])
                        * float(row[6])
                        / float(weightage.DFO_Area_wt[0])
                    )
                if float(row[7]) / float(weightage.DFO_percArea_wt[0]) > float(
                    weightage.DFO_percArea_Maxpt[0]
                ):
                    DFO_perc_area_2day_score = str(
                        float(weightage.DFO_percArea_Maxpt[0])
                        * float(weightage.two_Day_Multiplier[0])
                    )
                else:
                    DFO_perc_area_2day_score = str(
                        float(weightage.DFO_percArea_Minpt[0])
                        * float(weightage.two_Day_Multiplier[0])
                        * float(row[7])
                        / float(weightage.DFO_percArea_wt[0])
                    )
                if float(row[8]) / float(weightage.DFO_Area_wt[0]) > float(
                    weightage.DFO_Area_max_pt[0]
                ):
                    DFO_area_3day_score = str(
                        float(weightage.DFO_Area_max_pt[0])
                        * float(weightage.three_Day_Multiplier[0])
                    )
                else:
                    DFO_area_3day_score = str(
                        float(weightage.DFO_Area_Min_pt[0])
                        * float(weightage.three_Day_Multiplier[0])
                        * float(row[8])
                        / float(weightage.DFO_Area_wt[0])
                    )
                if float(row[9]) / float(weightage.DFO_percArea_wt[0]) > float(
                    weightage.DFO_percArea_Maxpt[0]
                ):
                    DFO_perc_area_3day_score = str(
                        float(weightage.DFO_percArea_Maxpt[0])
                        * float(weightage.three_Day_Multiplier[0])
                    )
                else:
                    DFO_perc_area_3day_score = str(
                        float(weightage.DFO_percArea_Minpt[0])
                        * float(weightage.three_Day_Multiplier[0])
                        * float(row[9])
                        / float(weightage.DFO_percArea_wt[0])
                    )

                Sum_Score = str(
                    (
                        float(DFO_area_1day_score)
                        + float(DFO_perc_area_1day_score)
                        + float(DFO_area_2day_score)
                        + float(DFO_perc_area_2day_score)
                        + float(DFO_area_3day_score)
                        + float(DFO_perc_area_3day_score)
                    )
                )
                score_field = [
                    DFO_area_1day_score,
                    DFO_perc_area_1day_score,
                    DFO_area_2day_score,
                    DFO_perc_area_2day_score,
                    DFO_area_3day_score,
                    DFO_perc_area_3day_score,
                    Sum_Score,
                ]
                for x in score_field:
                    row.append(x)
            DFO_w_score.writerow(row)
    csvfile.close()

    DFO = read_data(DFO_w_score_csv)
    DFO = DFO[DFO.DFOTotal_Score > 0.1]
    DFO = DFO.iloc[:, 1:]
    MOM = read_data(MOMOutput)
    MOM.drop(
        columns=[
            "area_km2",
            "ISO",
            "Admin0",
            "Admin1",
            "rfr_score",
            "cfr_score",
            "Resilience_Index",
            " NormalizedLackofResilience ",
            "Severity",
            "Alert",
        ],
        inplace=True,
    )
    Final_Output_0 = pd.merge(
        MOM.set_index("pfaf_id"), DFO.set_index("pfaf_id"), on="pfaf_id", how="outer"
    )
    join1 = pd.merge(
        Attributes,
        PDC_resilience[["ISO", "Resilience_Index", " NormalizedLackofResilience "]],
        on="ISO",
        how="left",
    )
    Final_Output = pd.merge(
        join1.set_index("pfaf_id"), Final_Output_0, on="pfaf_id", how="outer"
    )
    Final_Output[["Hazard_Score"]] = Final_Output[["Hazard_Score"]].fillna(value=0)
    Final_Output.loc[
        (Final_Output["Hazard_Score"] < Final_Output["DFOTotal_Score"]), "Flag"
    ] = 2
    Final_Output["Hazard_Score"] = Final_Output[["Hazard_Score", "DFOTotal_Score"]].max(
        axis=1
    )
    # Kept: dropping these also lost the GloFAS/GFMS/rain columns of watersheds
    # a later source keeps. Culled once, at the end of final_alert_pdc.
    # Final_Output = Final_Output[Final_Output.Hazard_Score != 0]
    Final_Output.drop(
        Final_Output.index[
            (Final_Output["rfr_score"] == 0) & (Final_Output["cfr_score"] == 0)
        ],
        inplace=True,
    )
    Final_Output = Final_Output.assign(
        Scaled_Riverine_Risk=lambda x: Final_Output["rfr_score"] * 20
    )
    Final_Output = Final_Output.assign(
        Scaled_Coastal_Risk=lambda x: Final_Output["cfr_score"] * 20
    )

    ################# TypeError: loop of ufunc does not support argument 0 of type float which has no callable log method
    cols = [
        "Scaled_Riverine_Risk",
        "Scaled_Coastal_Risk",
        "Hazard_Score",
    ]
    Final_Output[cols] = Final_Output[cols].apply(pd.to_numeric, errors="coerce")

    Final_Output["Severity"] = severity_from_hazard_and_risk_scores(Final_Output)
    Final_Output["Alert"] = Final_Output.apply(mofunc_dfo, axis=1)
    Final_Output["Flag"] = Final_Output["Flag"].astype(object)
    Final_Output.loc[Final_Output["Alert"] == "Information", "Flag"] = ""
    Final_Output.loc[Final_Output["Alert"] == "Advisory", "Flag"] = ""
    Final_Output.to_csv(DFO_Final_Attributes_csv, encoding="utf-8-sig")
    # Final_Output.to_csv('Final_Attributes_20210701_DFOUpdated.csv', encoding='utf-8-sig')
    join1 = pd.merge(
        Attributes,
        PDC_resilience[["ISO", "Resilience_Index", " NormalizedLackofResilience "]],
        on="ISO",
        how="left",
    )
    Attributes_Clean_DFO_Updated = pd.merge(
        join1.set_index("pfaf_id"),
        Final_Output[["Alert", "Flag"]],
        on="pfaf_id",
        how="right",
    )
    Attributes_Clean_DFO_Updated.to_csv(DFO_Attributes_Clean_csv, encoding="utf-8-sig")
    os.remove(DFO_w_score_csv)

    # generate HWRF_DFO_VIIRS_MoM
    DFO_MOMOutput = DFO_Final_Attributes_csv
    VIIRS_summary_csv = summary_viirs_all

    # output files
    Final_Attributes_csv = f"Final_Attributes_{adate}{settings.HWRF_FILE_TAG}+{dfo_date}DFO+{viirs_date}VIIRSUpdated.csv"
    Final_Attributes_csv = os.path.join(settings.HWRF_MOM_DIR, Final_Attributes_csv)
    Attributes_Clean_csv = f"Attributes_clean_{adate}{settings.HWRF_FILE_TAG}+{dfo_date}DFO+{viirs_date}VIIRSUpdated.csv"
    Attributes_Clean_csv = os.path.join(settings.HWRF_MOM_DIR, Attributes_Clean_csv)

    weightage = read_data(os.path.join(settings.BASE_DATA_DIR, "VIIRS_Weightage.csv"))
    Attributes = read_data(os.path.join(settings.BASE_DATA_DIR, "Attributes.csv"))
    PDC_resilience = read_data(
        os.path.join(settings.BASE_DATA_DIR, "Resilience_Index.csv")
    )
    add_field_VIIRS = [
        "VIIRS_area_1day_score",
        "VIIRS_percarea_1day_score",
        "VIIRS_area_5day_score",
        "VIIRS_percarea_5day_score",
        "VIIRSTotal_Score",
    ]

    # Read VIIRS Processing data and calculate score
    with open(VIIRS_summary_csv, "r", encoding="UTF-8") as VIIRS_file:
        VIIRS_reader = csv.reader(VIIRS_file)
        VIIRS_w_score_csv = "VIIRS_w_score_{}.csv".format(viirs_date)
        csvfile = open(VIIRS_w_score_csv, "w", newline="\n", encoding="utf-8")
        VIIRS_w_score = csv.writer(csvfile)
        row_count = 1
        # csv_writer = csv.writer(write_obj)
        for row in VIIRS_reader:
            if row_count == 1:
                for x in add_field_VIIRS:
                    row.append(x)
                row_count = row_count + 1
            else:
                if float(row[1]) / float(weightage.VIIRS_Area_wt[0]) > float(
                    weightage.VIIRS_Area_max_pt[0]
                ):
                    VIIRS_area_1day_score = str(
                        float(weightage.VIIRS_Area_max_pt[0])
                        * float(weightage.one_Day_Multiplier[0])
                    )
                else:
                    VIIRS_area_1day_score = str(
                        float(weightage.VIIRS_Area_Min_pt[0])
                        * float(weightage.one_Day_Multiplier[0])
                        * float(row[1])
                        / float(weightage.VIIRS_Area_wt[0])
                    )
                if float(row[2]) / float(weightage.VIIRS_percArea_wt[0]) > float(
                    weightage.VIIRS_percArea_Maxpt[0]
                ):
                    VIIRS_perc_area_1day_score = str(
                        float(weightage.VIIRS_percArea_Maxpt[0])
                        * float(weightage.one_Day_Multiplier[0])
                    )
                else:
                    VIIRS_perc_area_1day_score = str(
                        float(weightage.VIIRS_percArea_Minpt[0])
                        * float(weightage.one_Day_Multiplier[0])
                        * float(row[2])
                        / float(weightage.VIIRS_percArea_wt[0])
                    )
                if float(row[3]) / float(weightage.VIIRS_Area_wt[0]) > float(
                    weightage.VIIRS_Area_max_pt[0]
                ):
                    VIIRS_area_5day_score = str(
                        float(weightage.VIIRS_Area_max_pt[0])
                        * float(weightage.five_Day_Multiplier[0])
                    )
                else:
                    VIIRS_area_5day_score = str(
                        float(weightage.VIIRS_Area_Min_pt[0])
                        * float(weightage.five_Day_Multiplier[0])
                        * float(row[3])
                        / float(weightage.VIIRS_Area_wt[0])
                    )
                if float(row[4]) / float(weightage.VIIRS_percArea_wt[0]) > float(
                    weightage.VIIRS_percArea_Maxpt[0]
                ):
                    VIIRS_perc_area_5day_score = str(
                        float(weightage.VIIRS_percArea_Maxpt[0])
                        * float(weightage.five_Day_Multiplier[0])
                    )
                else:
                    VIIRS_perc_area_5day_score = str(
                        float(weightage.VIIRS_percArea_Minpt[0])
                        * float(weightage.five_Day_Multiplier[0])
                        * float(row[4])
                        / float(weightage.VIIRS_percArea_wt[0])
                    )
                Sum_Score = str(
                    (
                        float(VIIRS_area_1day_score)
                        + float(VIIRS_perc_area_1day_score)
                        + float(VIIRS_area_5day_score)
                        + float(VIIRS_perc_area_5day_score)
                    )
                )
                score_field = [
                    VIIRS_area_1day_score,
                    VIIRS_perc_area_1day_score,
                    VIIRS_area_5day_score,
                    VIIRS_perc_area_5day_score,
                    Sum_Score,
                ]
                for x in score_field:
                    row.append(x)
            VIIRS_w_score.writerow(row)
    csvfile.close()

    VIIRS = read_data(VIIRS_w_score_csv)
    VIIRS = VIIRS[VIIRS.VIIRSTotal_Score > 0.1]
    MOM = read_data(DFO_MOMOutput)
    MOM.drop(
        columns=[
            "area_km2",
            "ISO",
            "Admin0",
            "Admin1",
            "rfr_score",
            "cfr_score",
            "Resilience_Index",
            " NormalizedLackofResilience ",
            "Severity",
            "Alert",
        ],
        inplace=True,
    )
    Final_Output_0 = pd.merge(
        MOM.set_index("pfaf_id"), VIIRS.set_index("pfaf_id"), on="pfaf_id", how="outer"
    )
    join1 = pd.merge(
        Attributes,
        PDC_resilience[["ISO", "Resilience_Index", " NormalizedLackofResilience "]],
        on="ISO",
        how="left",
    )
    Final_Output = pd.merge(
        join1.set_index("pfaf_id"), Final_Output_0, on="pfaf_id", how="right"
    )
    Final_Output[["Hazard_Score"]] = Final_Output[["Hazard_Score"]].fillna(value=0)
    Final_Output.loc[
        (Final_Output["Hazard_Score"] < Final_Output["VIIRSTotal_Score"]), "Flag"
    ] = 3
    Final_Output["Hazard_Score"] = Final_Output[
        ["Hazard_Score", "VIIRSTotal_Score"]
    ].max(axis=1)
    # Kept: dropping these also lost the GloFAS/GFMS/rain columns of watersheds
    # a later source keeps. Culled once, at the end of final_alert_pdc.
    # Final_Output = Final_Output[Final_Output.Hazard_Score != 0]
    Final_Output.drop(
        Final_Output.index[
            (Final_Output["rfr_score"] == 0) & (Final_Output["cfr_score"] == 0)
        ],
        inplace=True,
    )
    Final_Output = Final_Output.assign(
        Scaled_Riverine_Risk=lambda x: Final_Output["rfr_score"] * 20
    )
    Final_Output = Final_Output.assign(
        Scaled_Coastal_Risk=lambda x: Final_Output["cfr_score"] * 20
    )

    ################# TypeError: loop of ufunc does not support argument 0 of type float which has no callable log method
    cols = [
        "Scaled_Riverine_Risk",
        "Scaled_Coastal_Risk",
        "Hazard_Score",
    ]
    Final_Output[cols] = Final_Output[cols].apply(pd.to_numeric, errors="coerce")

    Final_Output["Severity"] = severity_from_hazard_and_risk_scores(Final_Output)
    Final_Output["Alert"] = Final_Output.apply(mofunc_viirs, axis=1)
    Final_Output["Flag"] = Final_Output["Flag"].astype(object)
    Final_Output.loc[Final_Output["Alert"] == "Information", "Flag"] = ""
    Final_Output.loc[Final_Output["Alert"] == "Advisory", "Flag"] = ""
    Final_Output.to_csv(Final_Attributes_csv, encoding="utf-8-sig")
    join1 = pd.merge(
        Attributes,
        PDC_resilience[["ISO", "Resilience_Index", " NormalizedLackofResilience "]],
        on="ISO",
        how="left",
    )
    Attributes_Clean_VIIRS_Updated = pd.merge(
        join1.set_index("pfaf_id"),
        Final_Output[["Alert", "Flag"]],
        on="pfaf_id",
        how="right",
    )
    Attributes_Clean_VIIRS_Updated.to_csv(Attributes_Clean_csv, encoding="utf-8-sig")
    logging.info(f"generated: {Attributes_Clean_csv}")

    os.remove(VIIRS_w_score_csv)

    # remove DFO output
    os.remove(DFO_Final_Attributes_csv)
    os.remove(DFO_Attributes_Clean_csv)

    os.chdir(settings.BASE_DIR)

    return


def find_pair_HWRFoutput(adate):
    """return pair of HWRF Mom output
    [MoM_adate, MoM_1daybefore]
    if not found: ["",""]
    """
    # first find the hwrf hour output
    hwrfh_list = glob.glob(os.path.join(settings.HWRF_MOM_DIR, "Final*.csv"))
    # Final_Attributes_2021102800HWRF+20211028DFO+20211027VIIRSUpdated.csv
    matching = [s for s in hwrfh_list if adate + settings.HWRF_FILE_TAG + "+" in s]
    if len(matching) < 1:
        return ["", ""]

    MoM_adate = matching[0]

    # generate string from the previous day
    # turn the datestr into a real date
    datestr = adate[:-2]
    hh = adate[-2:]
    da = datetime.strptime(datestr, "%Y%m%d")
    pda = da - timedelta(days=1)
    pdatestr = pda.strftime("%Y%m%d")
    # pdate
    pdate = pdatestr + hh
    matching = [s for s in hwrfh_list if pdate + settings.HWRF_FILE_TAG + "+" in s]
    # no previous date
    if len(matching) < 1:
        return [MoM_adate, ""]

    MoM_1daybefore = matching[0]

    return [MoM_adate, MoM_1daybefore]


def final_alert_pdc(adate):
    """generate final alert"""

    fAlert = (
        f"Final_Attributes_{adate}{settings.HWRF_FILE_TAG}+MOM+DFO+VIIRSUpdated_PDC.csv"
    )
    fAlert = os.path.join(settings.FINAL_MOM_DIR, fAlert)
    # check if final alert is already generatated
    if os.path.exists(fAlert):
        logging.info(f"mathing HWRF output already exists: {adate}")
        return

    [aAlert, pAlert] = find_pair_HWRFoutput(adate)
    if aAlert == "" or pAlert == "":
        logging.warning(f"mathing HWRF output is not found: {adate}")
        return

    mapping = {"Information": 1, "Advisory": 2, "Watch": 3, "Warning": 4}
    # read data
    pa_df = read_data(pAlert)
    # for PA, the only two columns needed
    pa_df = pa_df[["pfaf_id", "Alert"]]
    ca_df = read_data(aAlert)
    pa_df = pa_df.replace({"Alert": mapping})
    ca_df = ca_df.replace({"Alert": mapping})

    # rename Alert in the previous day as Alert_0
    pa_df.rename(columns={"Alert": "Alert_0"}, inplace=True)
    # join two df by pfaf_id
    joined_df = ca_df.set_index("pfaf_id").join(pa_df.set_index("pfaf_id"))

    # check the value of Alert_0
    # expected value: [ 1.  2. nan  3.  4.]
    # print(joined_df["Alert_0"].unique())
    # replace nan value as 5
    joined_df["Alert_0"] = joined_df["Alert_0"].fillna(5)
    # force it int
    joined_df = joined_df.astype({"Alert_0": int})
    # expected value Alert_0: [1 2 3 4 5]
    # print(joined_df["Alert_0"].unique())
    # expected value Alert: [1 2 3 4]
    # print(joined_df["Alert"].unique())

    # a new Status column based on Alert and Alert_0
    # Alert_0 = 5: "New"
    # Alert = Alert_0: "Continued"
    # Alert > Alert_0: "Upgraded"
    # Alert < Alert_0: "Downgraded"
    conditions = [
        (joined_df["Alert_0"] == 5),
        (joined_df["Alert"] == joined_df["Alert_0"]),
        (joined_df["Alert"] > joined_df["Alert_0"]),
        (joined_df["Alert"] < joined_df["Alert_0"]),
    ]
    actions = ["New", "Continued", "Upgraded", "Downgraded"]
    joined_df["Status"] = np.select(conditions, actions, default="Other")
    # print(joined_df["Status"].unique())

    mapping = {1: "Information", 2: "Advisory", 3: "Watch", 4: "Warning"}
    joined_df = joined_df.replace({"Alert": mapping})

    # delete columns
    joined_df = joined_df.drop(
        [
            "Admin0",
            "Admin1",
            "ISO",
            "Resilience_Index",
            " NormalizedLackofResilience ",
            "Alert_0",
        ],
        axis=1,
    )

    # drop FID if it has
    if "FID" in joined_df.columns:
        print("drop FID column")
        joined_df = joined_df.drop(["FID"], axis=1)

    # load admin data
    Union_Attributes = pd.read_csv(
        os.path.join(settings.BASE_DATA_DIR, "Admin0_1_union_centroid.csv"),
        encoding="Windows-1252",
    )

    # reset index
    joined_df = joined_df.reset_index(level=0)
    PDC_Alert = pd.merge(Union_Attributes, joined_df, on="pfaf_id", how="inner")
    # print(PDC_Alert)
    # Dead code: these are numeric columns, so == "" never matches.
    PDC_Alert.drop(
        PDC_Alert.index[
            (PDC_Alert["DFOTotal_Score"] == "")
            & (PDC_Alert["MOM_Score"] == "")
            & (PDC_Alert["CentroidY"] > 50)
        ],
        inplace=True,
    )

    # drop FID if it has
    FIDcolumns = [x for x in PDC_Alert.columns if "FID" in x]
    # print(FIDcolumns)
    if len(FIDcolumns) > 0:
        print("drop FIDs column")
        PDC_Alert = PDC_Alert.drop(FIDcolumns, axis=1)

    # The chain's only cull: a watershed is published when some source scored
    # it, but it keeps every column it collected on the way here.
    PDC_Alert = PDC_Alert[PDC_Alert["Hazard_Score"].fillna(0) != 0]

    PDC_Alert.to_csv(fAlert, encoding="Windows-1252")
    logging.info(f"generated final alert: {fAlert}")

    return


def hwrf_workflow(adate):
    """the hwrf workflow on a date
    to simplify the call from the other scripts
    """
    update_HWRF_MoM(adate)
    update_HWRFMoM_DFO_VIIRS(adate)
    final_alert_pdc(adate)


def batchrun_HWRF_MoM():
    """run hwrf in batch mode"""

    # collect all dates
    # first scan hwrf_summary folder
    datelist = []
    now = datetime.now(timezone.utc)
    for entry in get_latestitems(settings.HWRF_SUM_DIR):
        if "rainfall.csv" in entry:
            testdate = entry.split(".")[1].replace("rainfall", "")
            datelist.append(testdate)
            # the next cycle's MoM uses this summary (previous-cycle HWRF), so
            # it can run as soon as that cycle has started
            next_cycle = datetime.strptime(testdate, "%Y%m%d%H").replace(
                tzinfo=timezone.utc
            ) + timedelta(hours=6)
            if next_cycle <= now:
                datelist.append(next_cycle.strftime("%Y%m%d%H"))

    # scan raw data folder
    for entry in get_latestitems(settings.HWRF_PROC_DIR):
        # hwrf.2021092112rainfall.zip
        if ".zip" in entry:
            testdate = entry.split(".")[1].replace("rainfall", "")
            datelist.append(testdate)

    # also scan mom folder
    for entry in get_latestitems(settings.HWRF_MOM_DIR):
        if "Final" in entry and f"{settings.HWRF_FILE_TAG}Updated" in entry:
            testdate = entry.split("_")[2].replace(
                f"{settings.HWRF_FILE_TAG}Updated.csv", ""
            )
            datelist.append(testdate)

    # get current processing hour
    # this code is also in HWRF_cron(), no harm to keep it here
    curdatestr = get_current_processing_datehour(time_delay=settings.HWRF_TIME_DELAY)
    # check if there is the hwrf data for this hour
    if not hwrf_today(adate=curdatestr[:8], ahour=curdatestr[-2:]):
        datelist.append(curdatestr)

    list_set = set(datelist)
    unique_dates = list(list_set)
    unique_dates.sort()
    logging.info(f"HWRF MoM batch, dates found: {unique_dates}")

    for testdate in unique_dates:
        logging.info(f"HWRF MoM batch, running workflow for: {testdate}")
        hwrf_workflow(testdate)

    return


def main():
    # run batch mode
    batchrun_HWRF_MoM()


if __name__ == "__main__":
    main()
