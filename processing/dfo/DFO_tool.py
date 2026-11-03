"""
DFO_tool.py

Download and process DFO data

Two main function:
    * DFO_cron : run the daily cron job
    * DFO_cron_fix: rerun cron-job for a given date
"""

import csv
import logging
import os
import shutil
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
import zipfile

import pandas as pd
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from osgeo import gdal

from processing.dfo.DFO_MoM import update_DFO_MoM
import settings
from processing.utilities import from_today, watersheds_gdb_reader
from processing.watershed_cells import raster_summary

load_dotenv()

# for command line mode, no need for cron-job
# from progressbar import progress

# total number of hdf files
DFO_TOTAL_TILES = 287
DFO_MINIMUM_TILES = 280

# a date still without DFO data this many days later gets an all-zero
# summary (fill_missing_dates); only dates the host still keeps (about a
# week) are filled
DFO_FILL_AFTER_DAYS = 1
DFO_FILL_LOOKBACK_DAYS = 7
DFO_FILLED_DIR = os.path.join(settings.DFO_PROC_DIR, "filled")

# flood layers of the DFO hdf files, in the order of the summary columns
FLOOD_LAYERS = [
    "Flood 1-Day 250m",
    "Flood 1-Day CS 250m",
    "Flood 2-Day 250m",
    "Flood 3-Day 250m",
]


def get_real_date(year, day_num):
    """get the real date"""

    # allData/61/MCDWD_L3_NRT/2021/021

    # year,day_num = foldername.split("/")[-2:]
    res = datetime.strptime(str(year) + "-" + str(day_num), "%Y-%j").strftime("%Y%m%d")

    return res


def check_status(adate):
    """check if a give date is processed"""

    processed_list = os.listdir(settings.DFO_SUM_DIR)
    processed = any(adate in x for x in processed_list)

    return processed


def get_hosturl():
    """get the host url"""
    baseurl = settings.config.get("dfo", "HOST")
    cur_year = datetime.now(timezone.utc).year
    hosturl = f"{baseurl.rstrip('/')}/{str(cur_year)}"

    return hosturl


def generate_procesing_list():
    """generate list of date to process
    return a dict object
    {'001': '20230101', '002': '20230102'}
    """
    hosturl = get_hosturl()
    reqs = requests.get(hosturl)
    soup = BeautifulSoup(reqs.text, "html.parser")
    cur_year = hosturl[-4:]
    datelist = {}
    # get the today in str
    today_str = datetime.now(timezone.utc).strftime("%Y%m%d")

    days = [link.string for link in soup.find_all("a") if link.string.isdigit()]
    for day_num in days:
        real_date = get_real_date(cur_year, day_num)
        # compare date in iso str
        # skip the later date, there is no data
        if real_date > today_str:
            continue
        # check if the date is already processed
        if check_status(real_date):
            continue
        datelist[day_num] = real_date

    return datelist


def dfo_download(subfolder):
    """download a subfolder"""

    # check if there is unfinished download
    d_dir = os.path.join(settings.DFO_PROC_DIR, subfolder)
    if os.path.exists(d_dir):
        # return
        # is file cases
        if os.path.isfile(d_dir):
            os.remove(d_dir)
        else:
            # remove the subfolder
            shutil.rmtree(d_dir)

    dfokey = (
        settings.config.get("dfo", "TOKEN")
        if "???" not in settings.config.get("dfo", "TOKEN")
        else os.getenv("AUTH_DFO_TOKEN")
    )
    dataurl = f"{get_hosturl().rstrip('/')}/{subfolder}"

    # os-agnostic process
    cmd = [
        "wget",
        "-e",
        "robots=off",
        "-r",
        "--no-parent",
        "-l",
        "1",
        "-R",
        ".html,.tmp",
        "-nH",
        "--cut-dirs=8",
        dataurl,
        "--header",
        f"Authorization: Bearer {dfokey}",
        "-P",
        settings.DFO_PROC_DIR,
    ]

    result = subprocess.run(cmd, check=False)
    if result.returncode != 0:
        # something wrong with downloading
        logging.warning(f"Download failed: {dataurl}, error: {result.returncode}")
        print("Exit code:", result.returncode)
        # sys.exit()
        return False

    return True


def summary_headers(vrt_file):
    """summary columns of a flood layer mosaic (e.g. Flood_1-Day_CS_250m.vrt)"""
    headerprefix = os.path.basename(vrt_file).split("_")[1]
    if "_CS_" in vrt_file:
        headerprefix = "1-Day_CS"

    return [
        "pfaf_id",
        headerprefix + "_TotalArea_km2",
        headerprefix + "_perc_Area",
    ]


def dfo_extract_by_watershed(vtk_file):
    """extract data by all the watersheds"""

    watersheds = watersheds_gdb_reader()
    pfaf_id_list = watersheds.index.tolist()

    headers_list = summary_headers(vtk_file)
    summary_file = os.path.basename(vtk_file)[:-4] + ".csv"
    if not os.path.exists(summary_file):
        with open(summary_file, "w") as f:
            writer = csv.writer(f)
            writer.writerow(headers_list)
    else:
        # already processed,
        return

    # per-watershed flooded area, exact cell shares (watershed_cells.py)
    summary = raster_summary("dfo", vtk_file, watersheds)
    with open(summary_file, "a") as f:
        writer = csv.writer(f)

        for pfaf_id in pfaf_id_list:
            DFO_TotalArea = summary.at[pfaf_id, "area"]
            DFO_Area_percent = summary.at[pfaf_id, "perc_area"]

            results_list = [
                pfaf_id,
                "{:.3f}".format(DFO_TotalArea),
                "{:.3f}".format(DFO_Area_percent),
            ]
            writer.writerow(results_list)

    return


def DFO_process(folder, adate):
    """processing dfo folder

    folder structure
    allData/61/MCDWD_L3_NRT/2021/021
        |-Flood 1-Day 250m
        |-Flood 1-Day CS 250m
        |-Flood 2-Day 250m
        |-Flood 3-Day 250m
        Flood_3-Day_250m.vrt
        Flood_2-Day_250m.vrt
        Flood_1-Day_CS_250m.vrt
        Flood_1-Day_250m.vrt
    """

    hdffolder = os.path.join(settings.DFO_PROC_DIR, folder)
    if os.path.isfile(hdffolder):
        logging.warning(f"Not downloaded properly: {folder}")
        return
    os.makedirs(hdffolder, exist_ok=True)

    # switch to working directory
    os.chdir(hdffolder)

    floodlayer = FLOOD_LAYERS
    # new layer name mapping
    floodsubdataset = {
        "Flood 1-Day 250m": "Flood_1Day_250m",
        "Flood 1-Day CS 250m": "FloodCS_1Day_250m",
        "Flood 2-Day 250m": "Flood_2Day_250m",
        "Flood 3-Day 250m": "Flood_3Day_250m",
    }
    # create sub folder if necessary
    for flood in floodlayer:
        subfolder = flood.replace(" ", "_")
        if not os.path.exists(subfolder):
            os.mkdir(subfolder)

    # MCDWD_L3_NRT.A2021022.h06v04.061.hdf
    # HDF4_EOS:EOS_GRID:"MCDWD_L3_NRT.A2021022.h06v04.061.hdf":Grid_Water_Composite:"Flood 1-Day 250m"
    # HDF4_EOS:EOS_GRID:"MCDWD_L3_NRT.A2021022.h06v04.061.hdf":Grid_Water_Composite:"Flood 1-Day CS 250m"
    # HDF4_EOS:EOS_GRID:"MCDWD_L3_NRT.A2021022.h06v04.061.hdf":Grid_Water_Composite:"Flood 2-Day 250m"
    # HDF4_EOS:EOS_GRID:"MCDWD_L3_NRT.A2021022.h06v04.061.hdf":Grid_Water_Composite:"Flood 3-Day 250m"
    # HDF4_EOS:EOS_GRID:"{HDF}":Grid_Water_Composite:"{floodLAYER}"

    # scan hdf files
    hdffiles = []
    for entry in os.listdir():
        if entry[-4:] != ".hdf":
            continue
        HDF = entry
        hdffiles.append(HDF)

    # check the number of files
    # need check the date first
    ddays = from_today(adate)
    # for the previous day, just process what ever it has
    if ddays >= 0:
        if len(hdffiles) < DFO_TOTAL_TILES:
            logging.warning(f"Not enough files: {folder}")
            return

    # one step one image operation
    vrt_list = []
    for flood in floodlayer:
        subfolder = flood.replace(" ", "_")
        
        vrt = f"{subfolder}.vrt"
        # skip existing VRT except 3-days (needs tiff generation)
        if os.path.exists(vrt) and "3-Day" not in vrt:
            vrt_list.append(vrt)
            continue

        subdataset = floodsubdataset[flood]
        tiff_list = []
        # geotiff convert
        for HDF in hdffiles:
            nameprefix = "_".join(HDF.split(".")[1:3])
            inputlayer = f'HDF4_EOS:EOS_GRID:"{HDF}":Grid_Water_Composite:{subdataset}'
            tiff = nameprefix + "_" + subfolder
            outputtiff = os.path.join(subfolder, tiff + ".tiff")
            tiff_list.append(outputtiff)
            if not os.path.exists(outputtiff):
                # gdal cmd
                gdalcmd = f"gdal_translate -of GTiff -co Tiled=Yes {inputlayer} {outputtiff}"
                # convert geotiff
                os.system(gdalcmd)
        # build vrt
        # gdalcmd = f"gdalbuildvrt {subfolder}.vrt {subfolder}/*.tiff"
        # print(gdalcmd)
        # os.system(gdalcmd)

        gdal.BuildVRT(vrt, tiff_list)
        vrt_list.append(vrt)
        # extract flood data
        dfo_extract_by_watershed(vrt)

        # build geotiff
        if "3-Day" in vrt:
            # tiff =  outputfolder + os.path.sep + "DFO_image/DFO_" + datestr + "_" + vrt.replace(".vrt",".tiff")
            # DFO_20210603_Flood_3-Day_250m.tiff
            tiff = f"DFO_{adate}_{subfolder}.tiff"
            tiff = os.path.join(settings.DFO_IMG_DIR, tiff)
            # gdal_translate -co TILED=YES -co COMPRESS=PACKBITS -of GTiff Flood_1-Day_250m.vrt Flood_1-Day_250m.tiff
            # gdaladdo -r average Flood_1-Day_250m.tiff 2 4 8 16 32
            gdalcmd = f"gdal_translate -co TILED=YES -co COMPRESS=LZW -of GTiff {vrt} {tiff}"
            os.system(gdalcmd)
            # build overview
            # gdalcmd = f'gdaladdo -r average {tiff} 2 4 8 16 32'
            # os.system(gdalcmd)

        # delete tiff folder
        if os.path.exists(subfolder):
            shutil.rmtree(subfolder)

    # merge flood data into one file
    csv_list = []
    for vrt in vrt_list:
        csvfile = vrt.replace(".vrt", ".csv")
        pdc = pd.read_csv(csvfile)
        csv_list.append(pdc)

    merged = csv_list[0].merge(csv_list[1], on="pfaf_id")
    merged = merged.merge(csv_list[2], on="pfaf_id")
    merged = merged.merge(csv_list[3], on="pfaf_id")

    # save output
    summary_csv = os.path.join(settings.DFO_SUM_DIR, "DFO_{}.csv".format(adate))
    merged.to_csv(summary_csv)
    logging.info(f"generated: {summary_csv}")

    # zip the original folder
    if settings.config["storage"].getboolean("dfo_save"):
        zipped = os.path.join(settings.DFO_PROC_DIR, "DFO_{}.zip".format(adate))

        # os-agnostic process
        with zipfile.ZipFile(zipped, "w", compression=zipfile.ZIP_STORED) as z:
            for root, _, files in os.walk("."):

                for name in files:
                    path = os.path.join(root, name)
                    # prevent self-inclusion in a zip folder
                    if os.path.abspath(path) == os.path.abspath(zipped):
                        continue
                    arcname = os.path.relpath(path, ".")
                    z.write(path, arcname)

        logging.info(f"generated: {zipped}")

    # remove all hdf file in the folder
    for entry in os.listdir():
        if ".hdf" in entry:
            os.remove(entry)

    # switch back script folder
    os.chdir(settings.BASE_DIR)

    return


def fill_missing_dates():
    """write an all-zero DFO summary (no image) for each recent date that
    still has no DFO data DFO_FILL_AFTER_DAYS days later, so DFO adds nothing
    that day instead of blocking the DFO/VIIRS MoM and leaving the alerts on
    old DFO data"""
    today = datetime.now(timezone.utc).date()
    pfaf_ids = None
    columns = [
        col
        for flood in FLOOD_LAYERS
        for col in summary_headers(flood.replace(" ", "_") + ".vrt")[1:]
    ]
    for back in range(DFO_FILL_LOOKBACK_DAYS, DFO_FILL_AFTER_DAYS - 1, -1):
        adate = (today - timedelta(days=back)).strftime("%Y%m%d")
        summary_csv = os.path.join(settings.DFO_SUM_DIR, f"DFO_{adate}.csv")
        if os.path.exists(summary_csv):
            continue
        if pfaf_ids is None:
            pfaf_ids = watersheds_gdb_reader().index
        empty = pd.DataFrame(0.0, index=range(len(pfaf_ids)), columns=columns)
        empty.insert(0, "pfaf_id", pfaf_ids)
        empty.to_csv(summary_csv)
        os.makedirs(DFO_FILLED_DIR, exist_ok=True)
        with open(os.path.join(DFO_FILLED_DIR, f"DFO_{adate}.txt"), "w") as f:
            f.write(f"{datetime.now(timezone.utc).isoformat()} no DFO data {back} days after the date\n")
        logging.warning(
            f"DFO FILLED {adate}: no DFO data {back} days after the date, wrote an "
            f"ALL-ZERO summary (not observed data, no image): {summary_csv}"
        )


def DFO_cron():
    """cron job to process DFO"""

    # DFO reached EOL in September 2026
    try:
        datelist = generate_procesing_list()
    except Exception:
        # host unreachable or gone: the missing dates are still filled below
        logging.exception("DFO host listing failed")
        datelist = {}

    if len(datelist) == 0:
        # return instead of exiting the process: the caller still has to run
        # batchrun_DFO_MoM, which catches up any date whose MoM is missing or
        # was deferred because its cycles had not happened yet
        logging.info("no new data to process!")
        fill_missing_dates()
        return

    logging.info(f"dates to process: {sorted(datelist.values())}")
    for key in datelist:
        # a failed or broken date never stops the run: it stays unprocessed,
        # is retried on the next run and filled by fill_missing_dates below
        try:
            logging.info(f"download: {key} ({datelist[key]})")
            if not dfo_download(key):
                logging.warning(
                    f"download failed for {key} ({datelist[key]}), skipping: the "
                    "date stays unprocessed and is retried on the next run"
                )
                continue

            logging.info(f"download finished: {key}")
            logging.info(f"processing: {key} ({datelist[key]})")
            DFO_process(key, datelist[key])
            # run DFO_MoM
            update_DFO_MoM(datelist[key])
            logging.info(f"processing finished: {key}")
        except Exception:
            logging.exception(
                f"processing failed for {key} ({datelist[key]}), skipping: the "
                "date stays unprocessed and is retried on the next run"
            )
        finally:
            # DFO_process works inside the download folder
            os.chdir(settings.BASE_DIR)

    fill_missing_dates()
    return


def DFO_fixdate(adate):
    """process a specific date (YYYYMMDD) that the host still has and that
    has no DFO summary yet"""
    datelist = generate_procesing_list()
    if adate not in datelist.values():
        logging.info(
            f"DFO fixdate {adate}: not on the host or already processed, "
            f"available: {sorted(datelist.values())}"
        )
        return

    key = [k for k, v in datelist.items() if v == adate][0]
    logging.info(f"try to fix a date: {adate}")
    logging.info(f"download: {key} ({adate})")
    if not dfo_download(key):
        logging.warning(f"download failed for {key} ({adate})")
        return
    logging.info(f"download finished: {key}")
    logging.info(f"processing: {key} ({adate})")
    DFO_process(key, adate)
    update_DFO_MoM(adate)
    logging.info(f"processing finished: {key}")


def main():
    DFO_cron()


if __name__ == "__main__":
    main()
