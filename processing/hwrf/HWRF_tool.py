"""
HWRF_tool.py
    -- cron job script for HWRF data
"""

import csv
import logging
import os
import shutil
import subprocess
import zipfile
from datetime import datetime, timezone

import pandas as pd
import requests
from bs4 import BeautifulSoup
from osgeo import gdal

import settings
from processing.hwrf.HWRF_MoM import hwrf_workflow
from processing.utilities import (
    RAIN_SUMMARY_HEADERS,
    get_current_processing_datehour,
    hwrf_today,
    read_data,
    watersheds_gdb_reader,
)
from processing.watershed_cells import raster_summary


def check_status(adate):
    """check if a give date is processed"""

    processed_list = os.listdir(settings.HWRF_SUM_DIR)
    processed = any(adate in x for x in processed_list)

    if processed:
        return processed

    # extra check
    processed_list = os.listdir(settings.HWRF_PROC_DIR)
    zipped_list = [x for x in processed_list if "zip" in x]
    processed = any(adate in x for x in zipped_list)

    return processed


def check_hours(adate):
    """check if it is too early to process"""
    # adate in YYYYMMDDHH

    ct = datetime.now(timezone.utc)
    da = datetime.strptime(adate, "%Y%m%d%H").replace(tzinfo=timezone.utc)
    delta = ct - da
    dhours = delta.total_seconds() / 3600.0
    if dhours > settings.HWRF_TIME_DELAY:
        return False
    else:
        return True


def generate_procesing_list():
    """generate the processing list"""

    hosturl = settings.config.get("hwrf", "HOST")

    try:
        # one request both checks the host and lists the dates
        reqs = requests.get(hosturl, timeout=60)
        if reqs.status_code != 200:
            logging.info(f"Host URL {hosturl} is not accessible")
            return {}  # Return an empty dictionary if URL isn't reachable
        soup = BeautifulSoup(reqs.text, "html.parser")

        datelist = {}
        for link in soup.find_all("a"):
            fstr = link.string
            if not fstr:
                continue
            if fstr[:5] == "hwrf.":
                a_entry = fstr.split(".")[1]
                a_entry = a_entry.replace("/", "")
                datelist[a_entry] = hosturl + fstr

        # first level output
        # {'20220712': 'https://ftpprd.ncep.noaa.gov/data/nccf/com/hwrf/prod/hwrf.20220712/', '20220713': 'https://ftpprd.ncep.noaa.gov/data/nccf/com/hwrf/prod/hwrf.20220713/'}
        # extract second level

        dataurllist = {}
        for key in datelist.keys():
            hosturl = datelist[key]
            reqs = requests.get(hosturl)
            soup = BeautifulSoup(reqs.text, "html.parser")
            for link in soup.find_all("a"):
                fstr = link.string
                if not fstr:
                    continue
                hhstr = fstr.replace("/", "")
                if hhstr in ["00", "06", "12", "18"]:
                    a_entry = key + hhstr
                    if check_status(a_entry):
                        continue
                    # check if it is too early to process the data
                    if check_hours(a_entry):
                        continue
                    dataurllist[a_entry] = hosturl + fstr

        return dataurllist

    except requests.exceptions.RequestException as e:
        logging.warning(f"Error accessing host URL {hosturl}: {e}")
        return {}  # Return an empty dictionary


def HWRF_download(hwrfurl):
    """download rainfall data"""
    reqs = requests.get(hwrfurl)
    soup = BeautifulSoup(reqs.text, "html.parser")

    ascii_list = []
    for link in soup.find_all("a"):
        fstr = link.string
        if "rainfall.ascii" in fstr:
            fstr_local = os.path.join(settings.HWRF_PROC_DIR, fstr)
            if not os.path.exists(fstr_local):
                subprocess.run(
                    [
                        "wget",
                        f"{hwrfurl.rstrip('/')}/{fstr}",
                        "-P",
                        settings.HWRF_PROC_DIR,
                    ],
                    check=True,
                )  # Raises CalledProcessError on non-zero exit
            ascii_list.append(fstr)

    return ascii_list


def process_rain(adate, TC_Rain):
    """process rainfall data"""

    ## VRT template to read the csv
    vrt_template = """<OGRVRTDataSource>
        <OGRVRTLayer name='{}'>
            <SrcDataSource>{}</SrcDataSource>
            <GeometryType>wkbPoint</GeometryType>
            <GeometryField encoding="PointFromColumns" x="lon" y="lat" z="Z"/>
        </OGRVRTLayer>
    </OGRVRTDataSource>"""

    ## Read each text file and create the separate tiff file
    for i in TC_Rain:
        with open(i, "r") as f:
            variable = csv.reader(f, delimiter=" ")
            row_count = 1
            for row in variable:
                if row_count == 1:
                    while "" in row:
                        row.remove("")
                    XLC = float(row[0])
                    XRC = float(row[1])
                    YBC = float(row[2])
                    YTC = float(row[3])
                    res = float(row[4])
                    nrows = float(row[5])
                    ncol = float(row[6])
                    row_count = row_count + 1
        df = (
            pd.read_table(
                i, skiprows=1, sep=r"\s+", names=("lat", "lon", "Z")
            )
        ).fillna(-999)
        df.sort_values(by=["lat", "lon"], ascending=[False, True])
        df = df[["lon", "lat", "Z"]]
        df = df[df.lon >= XLC]
        df = df[df.lon <= XRC]
        df = df[df.lat >= YBC]
        df = df[df.lat <= YTC]
        df = df[df.Z > 0]
        df.to_csv(i.replace(".ascii", ".csv"), index=False, sep=" ")
        with open(i.replace(".ascii", ".vrt"), "w") as g:
            g.write(
                vrt_template.format(
                    i.replace(".ascii", ""), i.replace(".ascii", ".csv")
                )
            )
        g.close()
        r = gdal.Rasterize(
            i.replace(".ascii", ".tiff"),
            i.replace(".ascii", ".vrt"),
            outputSRS="EPSG:4326",
            xRes=res,
            yRes=res,
            attribute="Z",
            noData=-999,
        )
        r = None
        os.remove(i.replace(".ascii", ".csv"))

    ##merge all  tiffs file als
    # nd delete the individual tiff, vrt and ascii file

    TC_Rain_tiff = []
    for i in TC_Rain:
        TC_Rain_tiff.append(i.replace(".ascii", ".tiff"))

    filename = "hwrf." + adate + "rainfall.vrt"
    raintiff = filename.replace(".vrt", ".tiff")
    vrt = gdal.BuildVRT(filename, TC_Rain_tiff)
    gdal.Translate(raintiff, vrt, creationOptions=["COMPRESS=LZW", "TILED=YES"])
    vrt = None

    # no need
    # gdalcmd = "gdal_translate -of GTiff " + filename + " " + raintiff
    # subprocess.call(gdalcmd, shell=True)

    # create a zipfile
    zip_file = "hwrf." + adate + "rainfall.zip"
    with zipfile.ZipFile(zip_file, "w", zipfile.ZIP_DEFLATED) as zipObj:
        for i in TC_Rain_tiff:
            asfile = i.replace(".tiff", ".ascii")
            zipObj.write(asfile)

    for i in TC_Rain_tiff:
        os.remove(i)
        os.remove(i.replace(".tiff", ".ascii"))
        os.remove(i.replace(".tiff", ".vrt"))

    return raintiff


def rain_summary_rows(summary):
    """RAIN_SUMMARY_HEADERS rows of a watershed_cells summary (HWRF, HAFS):
    the watersheds with rain only"""
    rain = summary[summary["has_data"]]
    return [
        [pfaf_id, row["area"], row["perc_area"], row["mean"], row["max"]]
        for pfaf_id, row in rain.iterrows()
    ]


def HWRF_extract_by_watershed(raintiff):
    """extract flood info by watershed"""

    ## zonal analysis using merged tiff and watersheds
    watersheds = watersheds_gdb_reader()

    output_csv = raintiff.replace(".tiff", ".csv")
    # rain area (exact cell shares), mean and max per watershed
    # (watershed_cells.py)
    HWRF_weightage = read_data(os.path.join(settings.BASE_DATA_DIR, "HWRF_Weightage.csv"))
    # rain area: only the cells above a quarter of the mean rain minimum
    value_above = float(HWRF_weightage.HWRF_MeanRain_minwt[0]) / 4
    rows = rain_summary_rows(
        raster_summary("hwrf", raintiff, watersheds, value_above=value_above)
    )
    with open(output_csv, "w") as f:
        writer = csv.writer(f)
        writer.writerow(RAIN_SUMMARY_HEADERS)
        writer.writerows(rows)
    has_data = len(rows) > 0
    # has_data, move file to the right locaition
    # no_data: keep the header-only summary (processed, no rain over any
    # watershed; a missing summary means not processed yet), delete the image
    shutil.move(output_csv, os.path.join(settings.HWRF_SUM_DIR, output_csv))
    if has_data:
        shutil.move(raintiff, os.path.join(settings.HWRF_IMG_DIR, raintiff))
        os.remove(raintiff.replace(".tiff", ".vrt"))
    else:
        os.remove(raintiff)
        os.remove(raintiff.replace(".tiff", ".vrt"))
        logging.info(f"no data, empty summary: {output_csv}")

    return [output_csv, has_data]


def HWRF_cron():
    """main cron script"""

    # get date list
    datelist = generate_procesing_list()
    print(datelist)
    # for debug
    # print(datelist)
    # sys.exit()

    if len(datelist) == 0:
        logging.info("no new data to process!")
        # get current processing hour
        curdatestr = get_current_processing_datehour(
            time_delay=settings.HWRF_TIME_DELAY
        )
        print(curdatestr)
        # check if there is the hwrf data for this hour
        if not hwrf_today(adate=curdatestr[:8], ahour=curdatestr[-2:]):
            logging.info(f"no HRWRF data, run {curdatestr}")
            hwrf_workflow(curdatestr)

        return

    # switch to processing folder
    os.chdir(settings.HWRF_PROC_DIR)

    # download - process ascii
    for key in datelist:
        logging.info(f"check: {key}")
        a_list = HWRF_download(datelist[key])
        if len(a_list) == 0:
            logging.info(f"no rainfall data {key}")
            continue
        logging.info(f"processing {key}")
        newtiff = process_rain(key, a_list)
        logging.info(f"processing {newtiff}")
        [hwrfcsv, dataflag] = HWRF_extract_by_watershed(newtiff)
        if not dataflag:
            logging.info(f"no rain over watersheds, empty summary: {hwrfcsv}")
            # if no csv produced, it shall just conitune to produce MoM output
            # continue
        logging.info(f"generated: {hwrfcsv}")

        # run MoM update
        testdate = key
        hwrf_workflow(testdate)

    os.chdir(settings.BASE_DIR)

    return


def main():
    HWRF_cron()


if __name__ == "__main__":
    main()
