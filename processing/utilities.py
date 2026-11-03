"""
utilities.py
routines shared across the modules

"""

import csv
import glob
import hashlib
import os
import re
from datetime import date, datetime, timedelta, timezone

import geopandas
import numpy as np
import pandas as pd
import requests
import scipy.stats

import settings


_WATERSHEDS = None


def watersheds_gdb_reader():
    """reader watersheds gdb into geopandas

    Read once per process and reused: the shapefile is 128 MB and the DFO job
    asked for it again for every flood layer. Callers only read from the
    frame, so they share one."""

    global _WATERSHEDS
    if _WATERSHEDS is not None:
        return _WATERSHEDS

    # pfaf_id, areakm2
    watersheds = geopandas.read_file(settings.WATERSHED_SHP)
    # issue #1
    # some old code use aqid, need to be updated
    # watersheds.rename(columns={"pfaf_id": "aqid"},inplace=True)
    # watersheds.set_index("aqid",inplace=True)
    watersheds.set_index("pfaf_id", inplace=True)
    watersheds.crs = "EPSG:4326"

    _WATERSHEDS = watersheds
    return watersheds


def shapefile_fingerprint():
    """sha256 of the watershed shapefile geometry and attribute files"""
    sha = hashlib.sha256()
    base = os.path.splitext(settings.WATERSHED_SHP)[0]
    for ext in (".shp", ".dbf"):
        with open(base + ext, "rb") as f:
            for block in iter(lambda: f.read(1 << 22), b""):
                sha.update(block)
    return sha.hexdigest()


def read_data(datafile) -> pd.DataFrame:
    df = pd.read_csv(datafile)
    # df = pd.DataFrame(df)
    return df


def severity_from_hazard_and_risk_scores(df):
    """Severity of each row of df, from its Hazard_Score and the larger of its
    Scaled_Riverine_Risk and Scaled_Coastal_Risk"""
    # Hazard 0 means no hazard: Severity 0, the formula only for Hazard > 0
    scored = df["Hazard_Score"] != 0
    result = pd.Series(0.0, index=df.index)
    result[scored] = scipy.stats.norm(
        # Risk 100 (score 5): ln(0) = -inf, numpy warns, and Severity is 1 for any Hazard > 0
        np.log(
            100
            - df.loc[scored, ["Scaled_Riverine_Risk", "Scaled_Coastal_Risk"]].max(axis=1)
        ),
        1,
    ).cdf(np.log(df.loc[scored, "Hazard_Score"]))
    return result


def from_today(adate):
    # conver adate to date object
    # adate may come in as YYYYMMDD
    da = datetime.strptime(adate[:8], "%Y%m%d")
    da = da.replace(tzinfo=timezone.utc)
    today = datetime.now(timezone.utc)
    delta = da - today

    return delta.days


def is_cron_time(schedule, now=None, minutes=5):
    """True if now is at a time of schedule or up to minutes after it (cron
    starts a job at its minute, never before): hours (5) or "HH:MM" ("13:30"),
    in the server's local time as cron reads them"""
    now = now or datetime.now()
    now_min = now.hour * 60 + now.minute
    for t in schedule:
        hour, minute = (int(x) for x in str(t).split(":")) if ":" in str(t) else (int(t), 0)
        # minutes since the scheduled time; across midnight 0:02 is 4 after 23:58
        if (now_min - (hour * 60 + minute)) % (24 * 60) <= minutes:
            return True
    return False


def run_label(schedule, now=None):
    """"cronjob_HHMM_YYYYMMDDTHHMM" (the scheduled time) for a run at a time
    of schedule, otherwise "backfill_YYYYMMDDTHHMM" (the time now)"""
    now = now or datetime.now()
    for t in schedule:
        if is_cron_time([t], now):
            hour, minute = (int(x) for x in str(t).split(":")) if ":" in str(t) else (int(t), 0)
            # the scheduled time at or before now: across midnight, the day before
            scheduled = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if scheduled > now:
                scheduled -= timedelta(days=1)
            return f"cronjob_{scheduled:%H%M}_{scheduled:%Y%m%dT%H%M}"
    return f"backfill_{now:%Y%m%dT%H%M}"


def hour_diff(adate1, adate2):
    """find the hour difference bewteen to date string"""
    # data format YYYYMMDDHH
    da1 = datetime.strptime(adate1, "%Y%m%d%H")
    da2 = datetime.strptime(adate2, "%Y%m%d%H")
    delta = da1 - da2
    dhours = int(delta.total_seconds() / 3600)
    return dhours


def find_latest_glofas(apath, adate, atype):
    """return the latest GloFAS file dated BEFORE adate (YYYYMMDD[HH])"""
    target = f"threspoints_{adate[:8]}00.{atype}"
    candidates = [
        os.path.basename(f)
        for f in glob.glob(os.path.join(apath, f"threspoints_*.{atype}"))
        if os.path.basename(f) < target
    ]
    return max(candidates) if candidates else ""

def find_latest_hwrf(apath, adate, atype):
    """return the latest HWRF rainfall file dated BEFORE adate (YYYYMMDDHH)"""
    target = f"hwrf.{adate[:10]}rainfall.{atype}"
    candidates = [
        os.path.basename(f)
        for f in glob.glob(os.path.join(apath, f"hwrf.*rainfall.{atype}"))
        if os.path.basename(f) < target
    ]
    return max(candidates) if candidates else ""


def find_latest_viirs(apath, adate, hours):
    """return [YYYYMMDD, path] of the latest VIIRS summary for an HWRF/HAFS
    cycle (adate YYYYMMDD, hours its HH): from D-2 back for the 00/06
    cycles, from D-1 back for the 12/18 cycles; ["", ""] if none"""
    # VIIRS of D is published on D+1 (~10:00-11:15 UTC) and written by the
    # 12:00 VIIRS run, at times only at 17:00 or a day later
    da = datetime.strptime(adate[:8], "%Y%m%d")
    startd = 2 if hours in ("00", "06") else 1
    for i in range(startd, 10):
        cdatestr = (da - timedelta(days=i)).strftime("%Y%m%d")
        cfile = os.path.join(apath, f"VIIRS_Flood_{cdatestr}.csv")
        if os.path.exists(cfile):
            return [cdatestr, cfile]
    return ["", ""]


def get_latestitems(afolder, numofitems=7):
    """get the list of the latest items in a folder"""

    items = sorted(os.listdir(afolder))

    if len(items) < numofitems:
        return items
    else:
        return items[-numofitems:]


# columns of the HWRF and HAFS rainfall summaries (hwrf./hafs.YYYYMMDDHHrainfall.csv)
RAIN_SUMMARY_HEADERS = ["pfaf_id", "Rain_TotalArea_km", "perc_Area", "MeanRain", "MaxRain"]


def write_empty_rain_summary(path):
    """header-only rainfall summary: the cycle is processed and has no rain
    over any watershed (a missing summary means not processed yet)"""
    with open(path, "w") as f:
        csv.writer(f).writerow(RAIN_SUMMARY_HEADERS)


def hafs_storms(cycle):
    """storm ids (e.g. 20e, 09l) HAFS has published for a cycle (YYYYMMDDHH);
    raises on a failed request"""
    host = settings.HAFS_HOST.rstrip("/") + "/"
    prefix = f"{settings.HAFS_MODEL}/{cycle[:8]}/{cycle[8:]}/"
    reqs = requests.get(
        host, params={"list-type": "2", "prefix": prefix, "delimiter": "."}, timeout=60
    )
    reqs.raise_for_status()
    found = re.findall(rf"<Prefix>{re.escape(prefix)}(\d\d[a-z])\.</Prefix>", reqs.text)
    return sorted(set(found))


def url_exits(aurl):
    """test if a url exists"""
    try:
        req = requests.get(aurl, timeout=10)  # Add timeout to prevent hanging
        return req.status_code == 200
    except requests.exceptions.RequestException:
        # Catches all requests-related exceptions (ConnectionError, Timeout, etc.)
        return False


def hwrf_today(adate="", ahour=""):
    """check if hwrf has date for today"""
    tstr, hstr = adate, ahour
    if tstr == "":
        today = datetime.now(timezone.utc)
        tstr = datetime.strftime(today, "%Y%m%d")

    if hstr == "":
        hstr = "00"

    hosturl = settings.config.get("hwrf", "HOST")
    turl = f"{hosturl.rstrip('/')}/hwrf.{tstr}/{hstr}"
    has_data = url_exits(turl)
    return has_data


def get_current_processing_datehour(time_delay=6):
    """get the current processing datehour with a time-delay
    -- time_delay(in hours)
    -- return YYYYMMDDHH (hour in 00, 06, 12, 18)
    """
    # get current time
    ct = datetime.now(timezone.utc)
    dt = ct - timedelta(hours=time_delay)
    # integer division
    ahour = (dt.hour // 6) * 6
    adatestr = dt.strftime("%Y%m%d") + str(ahour).zfill(2)
    return adatestr


def main():
    """test routines"""

    print("==> read watershed")
    watershed = watersheds_gdb_reader()
    print(watershed.head)

    # test from today function
    print("==> from tdoay")
    adate = datetime.now(timezone.utc).strftime("%Y%m%d")
    ddays = from_today(adate)
    print("{} => {}".format(adate, ddays))

    yesterday = datetime.now(timezone.utc) - timedelta(days=2)
    adate = yesterday.strftime("%Y%m%d")
    ddays = from_today(adate)
    print("{} => {}".format(adate, ddays))

    adate = adate + "18"
    ddays = from_today(adate)
    print("{} => {}".format(adate, ddays))

    # test hour_diff
    print("==> hour diff")
    da1 = "2022100910"
    da2 = "2022100918"
    dhours = hour_diff(da1, da2)
    print("{} - {} = {} hours".format(da1, da2, dhours))

    da1 = "2022100910"
    da2 = "2022100818"
    dhours = hour_diff(da1, da2)
    print("{} - {} = {} hours".format(da1, da2, dhours))

    print("==> find latest")
    lastest_csv = find_latest_glofas(settings.GLOFAS_SUM_DIR, da2, "csv")
    print(lastest_csv)

    print("==> get lastest items")
    lastest_items = get_latestitems(settings.HWRF_PROC_DIR)
    print(lastest_items)
    lastest_items = get_latestitems(settings.HWRF_SUM_DIR, numofitems=5)
    print(lastest_items)

    print("==> url exist")
    today = datetime.now(timezone.utc)
    tstr = today.strftime("%Y%m%d")
    aurl = f"https://ftpprd.ncep.noaa.gov/data/nccf/com/hwrf/prod/hwrf.{tstr}/00/"
    print("HWRF today: ")
    print(aurl, ":", url_exits(aurl))
    ereyesterday = today - timedelta(days=2)
    tstr = ereyesterday.strftime("%Y%m%d")
    print("HWRF the day before yesterday")
    aurl = f"https://ftpprd.ncep.noaa.gov/data/nccf/com/hwrf/prod/hwrf.{tstr}/00/"
    print(aurl, ":", url_exits(aurl))

    print("==> hwrf today")
    print("hwrf has the data today: ", hwrf_today())
    print("hwrf has the data today: ", hwrf_today(ahour="06"))
    print("hwrf has the data today: ", hwrf_today(adate="20221111", ahour="00"))
    print("hwrf has the data today: ", hwrf_today(adate="20221111", ahour="06"))

    print("==> get current processing datehour")
    print("current time: ", datetime.now(timezone.utc))
    print("current processing datehour: ", get_current_processing_datehour())
    print(
        "current processing datehour with 3 hour delay: ",
        get_current_processing_datehour(time_delay=3),
    )


if __name__ == "__main__":
    main()
