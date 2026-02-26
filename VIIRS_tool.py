"""
VIIRS_tool.py
    -- process VIIRS data
    -- https://www.ssec.wisc.edu/flood-map-demo/ftp-link

    output:
    -- VIIRS_Flood_yyyymmdd.csv at VIIRS_summary
    -- VIIRS_1day_compositeyyyymmdd_flood.tiff at VIIRS_image
    -- VIIRS_5day_compositeyyyymmdd_flood.tiff at VIIRS_image
"""

import argparse
import csv
from datetime import datetime, timezone, timedelta
import glob
import json
import logging
import os
import shutil
import sys
import zipfile

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import requests
from multiprocessing import Pool
from osgeo import gdal
from rasterio.mask import mask

import settings
from utilities import read_data, watersheds_gdb_reader
from VIIRS_MoM import update_VIIRS_MoM

import xml.etree.ElementTree as ET


def generate_adate(delay=1):
    """generate 1 day delay date"""

    previous_date = datetime.now(timezone.utc) - timedelta(days=delay)

    adate_str = previous_date.strftime("%Y%m%d")

    return adate_str


def check_status(adate):
    """check if a give date is processed"""

    summaryfile = os.path.join(
        settings.VIIRS_SUM_DIR, "VIIRS_Flood_{}.csv".format(adate)
    )
    if os.path.exists(summaryfile):
        processed = True
    else:
        processed = False

    return processed


def check_data_online(adate):
    """check data is online for a given date"""
    # total 136 AOIs
    # 5-day composite
    # https://floodlight.ssec.wisc.edu/composite/RIVER-FLDglobal-composite_*_000900.part*.tif
    # 1-day composite
    # https://floodlight.ssec.wisc.edu/composite/RIVER-FLDglobal-composite1_*_000000.part*.tif

    baseurl = settings.config.get("viirs", "HOST")
    testurl_t = "RIVER-FLDglobal-composite_{}_000000.part00{}.tif"
    for i in [1, 2, 3, 4, 5]:
        testurl = f"{baseurl.rstrip('/')}/{testurl_t.format(adate, str(i))}"
        r = requests.head(testurl)
        if r.status_code == 404:
            online = False
        else:
            online = True
            break

    return online


def list_tif_files(*, bucket_url: str, prefix: str) -> list[str]:
    """
    Docstring for list_tif_files

    :param bucket_url: Base S3 bucket URL, e.g. "https://noaa-jpss.s3.amazonaws.com"
    :type bucket_url: str
    :param prefix: Folder path inside bucket, e.g. "JPSS_Blended_Products/VFM_1day_GLB/TIF/2026/02/02/"
    :type prefix: str
    :return: Description
    :rtype: list[str]

    Returns a list of full downloadable .tif URLs from a public S3 bucket using ListObjectsV2.

    """

    namespace = "{http://s3.amazonaws.com/doc/2006-03-01/}"
    continuation_token = None
    tif_links = []

    while True:
        params = {
            "list-type": "2",
            "prefix": prefix,
        }

        if continuation_token:
            params["continuation-token"] = continuation_token

        response = requests.get(bucket_url, params=params, timeout=60)
        response.raise_for_status()

        root = ET.fromstring(response.text)

        # Extract file entries
        for content in root.findall(f".//{namespace}Contents"):
            key_elem = content.find(f"{namespace}Key")
            if key_elem is not None:
                key = key_elem.text
                if key.endswith(".tif"):
                    tif_links.append(f"{bucket_url}/{key}")

        # Check if there are more pages
        is_truncated = root.find(f"{namespace}IsTruncated")
        if is_truncated is not None and is_truncated.text == "true":
            continuation_token = root.find(f"{namespace}NextContinuationToken").text
        else:
            break

    return tif_links


def pop_matching_string_from_list(urls: list[str], str_to_match: str):

    for idx, url in enumerate(urls):
        if str_to_match in url:
            return urls.pop(idx)  # removes and returns

    return None  # if not found


def build_tiff(adate):
    """download and build geotiff"""

    use_aws = False

    if not use_aws:
        # FTP server:
        baseurl = settings.config.get("viirs", "HOST")
        day1url = (
            f"{baseurl.rstrip('/')}/"
            + "RIVER-FLDglobal-composite1_{}_000000.part{}.tif"
        )
        day5url = (
            f"{baseurl.rstrip('/')}/" + "RIVER-FLDglobal-composite_{}_000000.part{}.tif"
        )
        joblist = [
            {"product": "1day", "url": day1url},
            {"product": "5day", "url": day5url},
        ]
    else:
        baseurl = "https://noaa-jpss.s3.amazonaws.com"
        filename1 = "RIVER-FLDglobal-composite1_{}_000000.part{}.tif"
        filename5 = "RIVER-FLDglobal-composite_{}_000000.part{}.tif"
        date_obj = datetime.strptime(adate, "%Y%m%d")
        formatted_date1 = date_obj.strftime("%Y/%m/%d/")
        date_obj_minus_4 = date_obj - timedelta(days=4)
        formatted_date5 = date_obj_minus_4.strftime("%Y/%m/%d/")
        joblist = [
            {
                "product": "1day",
                "url": baseurl,
                "prefix": f"JPSS_Blended_Products/VFM_1day_GLB/TIF/{formatted_date1}",
                "filename": filename1,
            },
            {
                "product": "5day",
                "url": baseurl,
                "prefix": f"JPSS_Blended_Products/VFM_5day_GLB/TIF/{formatted_date5}",
                "filename": filename5,
            },
        ]

    final_2_tiffs = []

    for job_entry in joblist:
        tiff_file = "VIIRS_{}_composite{}_flood.tiff".format(
            job_entry["product"], adate
        )

        # skip download if composite .tif already exists
        if os.path.exists(tiff_file):
            final_2_tiffs.append(tiff_file)
            continue

        if use_aws:
            all_available_aws_files = list_tif_files(
                bucket_url=job_entry["url"], prefix=job_entry["prefix"]
            )

        session = requests.Session()
        tiff_list_per_job = []
        for i in range(1, 137):

            if not use_aws:
                # FTP server:
                dataurl = job_entry["url"].format(adate, str(i).zfill(3))
                filename = dataurl.split("/")[-1]
            else:
                dataurl = pop_matching_string_from_list(
                    all_available_aws_files, f"GLB{str(i).zfill(3)}"
                )
                filename = job_entry["filename"].format(adate, str(i).zfill(3))

            # try download file
            try:
                r = session.get(dataurl, allow_redirects=True)
            except requests.RequestException as e:
                logging.warning(f"no download: {dataurl}")
                logging.warning(f"error: {e}")
                continue

            # may not have files for some aio
            if r.status_code == 404:
                continue

            # store .tifs in memory buffer and build vrt from there, to avoid writing many files to disk
            mem_path = f"/vsimem/{filename}"
            gdal.FileFromMemBuffer(mem_path, r.content)
            tiff_list_per_job.append(mem_path)

        vrt = None
        vrt_file = None
        tiff_creation_options = [
            "COMPRESS=LZW",
            "TILED=YES",
            "BIGTIFF=YES",
            "BLOCKXSIZE=512",
            "BLOCKYSIZE=512",
        ]

        if os.name == "nt":  # windows

            # create compressed tiff using gdal.Warp
            # slower than VRT + Translate, but gdal.BuildVRT on Windows doesn't read memory buffers properly
            options = gdal.WarpOptions(
                format="GTiff", creationOptions=tiff_creation_options
            )
            gdal.Warp(tiff_file, tiff_list_per_job, format="GTiff", options=options)

        else:  # better way, but on windows "/vsimem/" path for memory buffer fails

            # build vrt (4GB in size)
            vrt_file = tiff_file.replace("tiff", "vrt")
            vrt = gdal.BuildVRT(vrt_file, tiff_list_per_job)

            # translate to compressed TIFF
            translate_options = gdal.TranslateOptions(
                format="GTiff", creationOptions=tiff_creation_options
            )
            gdal.Translate(tiff_file, vrt, options=translate_options)

        # copy to the Product folder
        dest_file = os.path.join(settings.VIIRS_IMG_DIR, tiff_file)
        shutil.copy(tiff_file, dest_file)

        logging.info("generated: " + tiff_file)

        if settings.config["storage"].getboolean("viirs_save"):
            print("zip downloaded file")
            zipped = os.path.join(settings.VIIRS_PROC_DIR, "VIIRS_{}.zip".format(adate))

            # os-agnostic process
            with zipfile.ZipFile(
                zipped, "a"
            ) as z:  # append to existig archive (e.g. with 1-day products)
                for f in glob.glob("*.tif"):
                    z.write(f, arcname=os.path.basename(f))  # match shell zip behavior

            logging.info("generated: " + zipped)

        # remove vrt from file and from memory
        if vrt and vrt_file:
            vrt = None
            os.remove(vrt_file)

        final_2_tiffs.append(tiff_file)

    return final_2_tiffs


def VIIRS_extract_by_mask(mask_json, tiff):
    with rasterio.open(tiff) as src:
        try:
            out_image, out_transform = mask(
                src, [mask_json["features"][0]["geometry"]], crop=True
            )
        except ValueError as e:
            #'Input shapes do not overlap raster.'
            src = None
            area = 0
            # return empty dataframe
            return area
    data = out_image[0]
    point_count = np.count_nonzero((data > 140) & (data < 201))
    src = None
    # total area
    # resolution is 375m
    area = point_count * 0.375 * 0.375
    return area


def VIIRS_extract_by_watershed(adate, tiffs):
    """extract data by wastershed"""

    watersheds = watersheds_gdb_reader()
    pfafid_list = watersheds.index.tolist()

    # two tiffs
    # VIIRS_1day_composite20210825_flood.tiff
    # VIIRS_5day_composite20210825_flood.tiff

    csv_dict = {}
    for tiff in tiffs:
        if "1day" in tiff:
            field_prefix = "oneday"
        if "5day" in tiff:
            field_prefix = "fiveday"
        csv_file = tiff.replace(".tiff", ".csv")
        headers_list = [
            "pfaf_id",
            field_prefix + "Flood_Area_km",
            field_prefix + "perc_Area",
        ]
        # write header
        with open(csv_file, "w") as f:
            writer = csv.writer(f)
            writer.writerow(headers_list)
        with open(csv_file, "a") as f:
            writer = csv.writer(f)
            for the_pfafid in pfafid_list:
                test_json = json.loads(
                    gpd.GeoSeries([watersheds.loc[the_pfafid, "geometry"]]).to_json()
                )
                area = VIIRS_extract_by_mask(test_json, tiff)
                perc_Area = area / watersheds.loc[the_pfafid]["area_km2"] * 100
                results_list = [the_pfafid, area, perc_Area]
                writer.writerow(results_list)
        csv_dict[field_prefix] = csv_file

    join = read_data(csv_dict["oneday"])
    join = join[join.onedayFlood_Area_km != 0]

    join1 = read_data(csv_dict["fiveday"])
    join1 = join1[join1.fivedayFlood_Area_km != 0]

    # TODO: check if "pfaf_id" is an index or a column, fix syntax
    merge = pd.merge(
        join.set_index("pfaf_id"), join1.set_index("pfaf_id"), on="pfaf_id", how="outer"
    )
    merge.fillna(0, inplace=True)

    # VIIRS_Flood_yyyymmdd.csv
    merged_csv = os.path.join(
        settings.VIIRS_SUM_DIR, "VIIRS_Flood_{}.csv".format(adate)
    )
    merge.to_csv(merged_csv)
    logging.info("generated: " + merged_csv)

    # need clean up
    os.remove(csv_dict["oneday"])
    os.remove(csv_dict["fiveday"])

    # remove tiff
    os.remove(tiffs[0])
    os.remove(tiffs[1])

    return


def VIIRS_run_adate(adate):
    """try to process VIIRS on a cerntain date
    -- this part of code is moved from VIIRS_cron"""

    if check_status(adate):
        logging.info("already processed: " + adate)
        return

    if not check_data_online(adate):
        logging.info("no data online: " + adate)
        return

    logging.info("Processing: " + adate)
    # change dir to VIIRSraw
    os.chdir(settings.VIIRS_PROC_DIR)

    # get two tiffs
    tiffs = build_tiff(adate)

    # extract data from tiffs
    VIIRS_extract_by_watershed(adate, tiffs)

    # update VIIRS MoM
    update_VIIRS_MoM(adate)

    os.chdir(settings.BASE_DIR)


def run_job(delay):
    print("PID:", os.getpid())

    adate = generate_adate(delay=delay)
    VIIRS_run_adate(adate)


def VIIRS_cron(adate=""):
    """main cron script"""

    # global basepath
    # basepath = os.path.dirname(os.path.abspath(__file__))
    # load_config()

    print("PID:", os.getpid())
    processes = 2
    gdal.SetConfigOption("GDAL_NUM_THREADS", str(os.cpu_count() / processes))

    if adate == "":
        # check two days
        with Pool(processes=2) as p:
            # p.map(run_job, [2, 1])
            jobs = [p.apply_async(run_job, (i,)) for i in [2, 1]]
            # wait for all to finish
            [job.get() for job in jobs]

        # adate = generate_adate(delay=0)
        # VIIRS_run_adate(adate)
    else:
        VIIRS_run_adate(adate)

    return


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "-fd",
        "--fixdate",
        dest="fixdate",
        type=str,
        help="rerun a cron job on a certian day",
    )
    args = parser.parse_args()

    if args.fixdate:
        VIIRS_cron(adate=args.fixdate)
    else:
        VIIRS_cron()


if __name__ == "__main__":
    main()
