"""
    VIIRS_MoM.py
        -- update Mom with VIIRS
        -- Read  Final_Attributes_yyyymmddhh_MOM+DFOUpdated.csv as MOM+DFO File as MOM File and VIIRS_Flood_yyyymmdd.csv as VIIRS File. 
        -- Write the output Final_Attributes_yyyymmddhhMOM+DFO+VIIRSUpdated.csv and Attributes_clean_yyyymmddhhMOM+DFO+VIIRSUpdated.csv file.
"""

import csv
import logging
import os
import sys

import pandas as pd

import settings
from processing.utilities import read_data, severity_from_hazard_and_risk_scores


def mofunc_viirs(row):
    if row["Severity"] >= 0.8 or row["Hazard_Score"] >= 80:
        return "Warning"
    elif row["Severity"] >= 0.6 or row["Hazard_Score"] >= 60:
        return "Watch"
    elif row["Severity"] >= 0.35 or row["Hazard_Score"] >= 35:
        return "Advisory"
    elif row["Severity"] > 0 or row["Hazard_Score"] > 0:
        return "Information"


def update_VIIRS_MoM(adate):
    """update VIIRS_MoM for a given date"""

    hh = "18"
    DFO_MOMOutput = "Final_Attributes_{}{}MOM+DFOUpdated.csv".format(adate, hh)
    DFO_MOMOutput = os.path.join(settings.DFO_MOM_DIR, DFO_MOMOutput)
    if not os.path.exists(DFO_MOMOutput):
        logging.info(f"DFO MoM not available yet: {DFO_MOMOutput}")
        return

    VIIRS_summary_csv = "VIIRS_Flood_{}.csv".format(adate)
    VIIRS_summary_csv = os.path.join(settings.VIIRS_SUM_DIR, VIIRS_summary_csv)
    if not os.path.exists(VIIRS_summary_csv):
        logging.info(f"VIIRS summary not available yet: {VIIRS_summary_csv}")
        return

    # output files
    Final_Attributes_csv = "Final_Attributes_{}{}MOM+DFO+VIIRSUpdated.csv".format(
        adate, hh
    )
    Final_Attributes_csv = os.path.join(settings.VIIRS_MOM_DIR, Final_Attributes_csv)
    Attributes_Clean_csv = "Attributes_clean_{}{}MOM+DFO+VIIRSUpdated.csv".format(
        adate, hh
    )
    Attributes_Clean_csv = os.path.join(settings.VIIRS_MOM_DIR, Attributes_Clean_csv)

    # already processed
    if os.path.exists(Final_Attributes_csv) and os.path.exists(Attributes_Clean_csv):
        logging.info(f"VIIRS MoM already processed: {adate}")
        return

    logging.info(
        f"VIIRS MoM inputs for {adate}: "
        f"dfo_mom={os.path.basename(DFO_MOMOutput)}, "
        f"viirs={os.path.basename(VIIRS_summary_csv)}"
    )

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
        VIIRS_w_score_csv = "VIIRS_w_score_{}.csv".format(adate)
        VIIRS_w_score_csv = os.path.join(settings.VIIRS_PROC_DIR, VIIRS_w_score_csv)
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
    # Kept: dropping these also lost the GloFAS/GFMS columns of watersheds
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
    os.remove(VIIRS_w_score_csv)

    return


def batchrun_VIIRS_MoM():
    """run VIIRS in batchmode"""

    alist = os.listdir(settings.VIIRS_SUM_DIR)
    alist.sort()
    for item in alist:
        if not ".csv" in item:
            continue
        datestr = item[:-4].split("_")[-1]
        logging.info(f"VIIRS MoM batch: {datestr}")
        update_VIIRS_MoM(datestr)


def main():
    # testdate = '20211203'
    # update_VIIRS_MoM(testdate)
    batchrun_VIIRS_MoM()


if __name__ == "__main__":
    main()
