"""
GFMS_tool.py

Download and process GFMS and GloFAS data

Two main function:
    * GFMS_cron : run the daily cron job
    * GFMS_cron_fix: rerun cron-job for a given date

The summary of a 3-hourly GFMS time is taken from the per-pixel maximum of
the grids at that time and the following 3-hourly times up to
GFMS_WINDOW_HOURS ahead (the host publishes ~4 days of forecast), as far as
the host has them. Only the times that have come are summarized; a later
run makes the others. The following grids are downloaded again on every run
(the host rewrites its files); their .bin files go to a temporary folder that
is removed afterwards.

Every grid downloaded, of a summarized time or a following one, is saved as
an image. An image is only replaced when the new grid differs from the
stored one; the stored one is then moved to GFMS_images_expired.
"""

import csv
import glob
import logging
import os
import shutil
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

import geopandas
import numpy as np
import pandas as pd
import rasterio
import requests
import zipfile

from processing.gfms.GFMS_MoM import flood_severity
from processing.watershed_cells import raster_summary

# from HWRF_MoM import update_HWRF_MoM, update_HWRFMoM_DFO_VIIRS, final_alert_pdc
from processing.hwrf.HWRF_MoM import hwrf_workflow
import settings
from processing.utilities import find_latest_glofas, hwrf_today, watersheds_gdb_reader

load_dotenv()
WATERSHEDS = None

# summary = per-pixel maximum over the time and the following hours
GFMS_WINDOW_HOURS = 96

# no need for cron-job
# from progressbar import progress


def _glofas_station_lines(txt_file):
    """the number of lines of a GloFAS text file that are stations (18 or
    more fields ending in the alert level); 0 for a missing file"""
    if not os.path.exists(txt_file):
        return 0
    count = 0
    with open(txt_file, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            p = line.strip().split(",")
            if len(p) >= 18 and p[-1].strip().isdigit():
                count += 1
    return count


def GloFAS_download():
    """download glofas data from ftp"""
    ftpsite = {}
    ftpsite["host"] = settings.config.get("glofas", "HOST")
    ftpsite["user"] = (
        settings.config.get("glofas", "USER")
        if "???" not in settings.config.get("glofas", "USER")
        else os.getenv("AUTH_GLOFAS_USER")
    )
    ftpsite["passwd"] = (
        settings.config.get("glofas", "PASSWD")
        if "???" not in settings.config.get("glofas", "PASSWD")
        else os.getenv("AUTH_GLOFAS_PASSWD")
    )
    ftpsite["directory"] = settings.config.get("glofas", "DIRECTORY")
    from ftplib import FTP

    last_exc: Exception = Exception("FTP connection failed")
    for attempt in range(3):
        try:
            ftp = FTP(
                host=ftpsite["host"], user=ftpsite["user"], passwd=ftpsite["passwd"]
            )
            break
        except Exception as e:
            logging.warning(f"FTP connect attempt {attempt + 1} failed: {e}")
            last_exc = e
            time.sleep(2)
    else:
        raise last_exc

    ftp.cwd(ftpsite["directory"])
    file_list = ftp.nlst()
    job_list = []
    for txt in file_list:
        save_txt = os.path.join(settings.GLOFAS_PROC_DIR, txt)

        # add date to job list. Even if GloFAS file already exists, it's not a guarantee it was processed
        if "threspoints_" in txt:
            job_list.append((txt.split(".")[0]).replace("threspoints_", ""))

        # downloaded next to it first: a file without station lines (empty,
        # blank, an error page) never replaces a local copy that has some;
        # a file with any station line always replaces it
        tmp_txt = save_txt + ".part"
        with open(tmp_txt, "wb") as fp:
            ftp.retrbinary("RETR " + txt, fp.write)
        if _glofas_station_lines(tmp_txt) == 0 and _glofas_station_lines(save_txt) > 0:
            logging.warning(
                f"GloFAS host sent {txt} without stations, keeping the local copy"
            )
            os.remove(tmp_txt)
        else:
            os.replace(tmp_txt, save_txt)

    ftp.quit()
    return job_list


# station text fields, in file order before the country: fixed and dynamic
# files order them differently
GLOFAS_TEXT_FIELDS = {
    False: ["Basin", "Location", "Station"],
    True: ["Station", "Basin", "Location"],
}


def _is_number(value):
    try:
        float(value)
        return True
    except ValueError:
        return False


def GloFAS_read_points(txt_file, dynamic=False):
    """GloFAS stations of a threspoints (dynamic=False) or threspointsDyn
    (dynamic=True) text file

    The files are unquoted csv whose station and country names can hold
    commas ("Moldova, Republic of", "Al Furat, Euphrates, Firat"), and the
    position of lon/lat among the "-" placeholders varies from line to line,
    so a line is read from its end: Alert_level, 20/5/2 yr EPS,
    Days_until_peak, one unused number, then lon and lat as the two numbers
    among the three fields before it, then upstream area, country code and
    continent (a few dynamic lines have the country code one field later,
    without the upstream area). The names are what lies between the station
    ID and the continent. An empty or missing file has no stations."""
    columns = (
        ["Point No", "ID"]
        + GLOFAS_TEXT_FIELDS[dynamic]
        + ["Country", "Continent", "Country_code", "Upstream area", "Lon", "Lat"]
        + ["Days_until_peak", "GloFAS_2yr", "GloFAS_5yr", "GloFAS_20yr", "Alert_level"]
    )
    rows = []
    if os.path.exists(txt_file):
        with open(txt_file, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                raw = line.rstrip("\r\n").split(",")
                p = [x.strip() for x in raw]
                if len(p) < 18:
                    if line.strip():
                        logging.warning(
                            f"GloFAS line skipped in {txt_file}: {line.strip()}"
                        )
                    continue
                lon, lat = [x for x in p[-9:-6] if _is_number(x)][:2]
                if p[-10] in ("-", "NA") or _is_number(p[-10]):
                    country_code, upstream = p[-11], p[-10]
                else:
                    country_code, upstream = p[-10], "-"
                # a comma inside a name: the piece after it starts with a space
                names = []
                for piece, raw_piece in zip(p[2:-12], raw[2:-12]):
                    if names and raw_piece.startswith(" "):
                        names[-1] = names[-1] + ", " + piece
                    else:
                        names.append(piece)
                country = names[-1]
                text = names[:-1]
                if len(text) > 3:
                    text = [text[0], ", ".join(text[1:-1]), text[-1]]
                text = text + ["-"] * (3 - len(text))
                rows.append(
                    [p[0], p[1]]
                    + text
                    + [country, p[-12], country_code, upstream, lon, lat]
                    + p[-5:]
                )
    df = pd.DataFrame(rows, columns=columns)
    numeric = [
        "Point No",
        "Lon",
        "Lat",
        "Days_until_peak",
        "GloFAS_2yr",
        "GloFAS_5yr",
        "GloFAS_20yr",
        "Alert_level",
    ]
    df[numeric] = df[numeric].apply(pd.to_numeric)
    # "NA" and "-" when not known
    df["Upstream area"] = pd.to_numeric(df["Upstream area"], errors="coerce")
    df = df.astype({"Point No": int, "Days_until_peak": int, "Alert_level": int})
    return df


def GloFAS_stations(fixed_sites, dyn_sites, data_date):
    """the fixed and dynamic GloFAS stations of data_date with the pfaf_id of
    the watershed they are in"""
    global WATERSHEDS
    if WATERSHEDS is None:
        WATERSHEDS = watersheds_gdb_reader()

    fixed_data = GloFAS_read_points(fixed_sites, dynamic=False)
    dyn_data = GloFAS_read_points(dyn_sites, dynamic=True)
    logging.info(
        f"GloFAS {data_date}: {len(fixed_data)} fixed, {len(dyn_data)} dynamic stations"
    )
    total_data = pd.concat([fixed_data, dyn_data], ignore_index=True)

    # create a geopanda dataset
    gdf = geopandas.GeoDataFrame(
        total_data,
        geometry=geopandas.points_from_xy(total_data.Lon, total_data.Lat),
    )
    gdf.crs = "EPSG:4326"
    # generate sindex
    gdf.sindex

    # sjoin
    gdf_watersheds = geopandas.sjoin(gdf, WATERSHEDS, predicate="within")
    gdf_watersheds.rename(columns={"index_right": "pfaf_id"}, inplace=True)

    forcast_time = datetime.strptime(data_date[:8], "%Y%m%d")
    # add column "Forecast Date"
    gdf_watersheds["Forecast Date"] = forcast_time.isoformat()

    # convert "GloFAS_2yr","GloFAS_5yr","GloFAS_20y" to 0~100
    if gdf_watersheds["GloFAS_2yr"].max() <= 1.0:
        gdf_watersheds["GloFAS_2yr"] = gdf_watersheds["GloFAS_2yr"] * 100
        gdf_watersheds["GloFAS_5yr"] = gdf_watersheds["GloFAS_5yr"] * 100
        gdf_watersheds["GloFAS_20yr"] = gdf_watersheds["GloFAS_20yr"] * 100
    gdf_watersheds = gdf_watersheds.astype(
        {"GloFAS_2yr": int, "GloFAS_5yr": int, "GloFAS_20yr": int}
    )

    # fill max_EPS
    gdf_watersheds["max_EPS"] = gdf_watersheds.apply(
        lambda row: str(row["GloFAS_2yr"])
        + "/"
        + str(row["GloFAS_5yr"])
        + "/"
        + str(row["GloFAS_20yr"]),
        axis=1,
    )
    return gdf_watersheds


def GloFAS_write(data_date):
    """the GloFAS csv and geojson of data_date from its downloaded fixed and
    dynamic station files, written over any existing ones"""
    out_csv = os.path.join(settings.GLOFAS_DIR, "threspoints_" + data_date + ".csv")
    out_geojson = os.path.join(
        settings.GLOFAS_DIR, "threspoints_" + data_date + ".geojson"
    )
    logging.info(f"processing GLoFAS: {data_date}")
    fixed_sites = os.path.join(
        settings.GLOFAS_PROC_DIR, "threspoints_" + data_date + ".txt"
    )
    dyn_sites = os.path.join(
        settings.GLOFAS_PROC_DIR, "threspointsDyn_" + data_date + ".txt"
    )
    gdf_watersheds = GloFAS_stations(fixed_sites, dyn_sites, data_date)

    # write out csv file
    out_columns = [
        "Point No",
        "Station",
        "Basin",
        "Country",
        "Lat",
        "Lon",
        "Upstream area",
        "Forecast Date",
        "max_EPS",
        "GloFAS_2yr",
        "GloFAS_5yr",
        "GloFAS_20yr",
        "Alert_level",
        "Days_until_peak",
        "pfaf_id",
    ]
    gdf_watersheds.to_csv(
        out_csv, index=False, columns=out_columns, float_format="%.3f"
    )
    logging.info(f"generated: {out_csv}")

    # write to excel
    # out_excel = glofasdata + "threspoints_" + data_date + ".xlsx"
    # gdf_watersheds.to_excel(out_excel,index=False,columns=out_columns,sheet_name='Sheet_name_1')

    # to geojson
    gdf_watersheds.to_file(out_geojson, driver="GeoJSON")
    logging.info(f"generated: {out_geojson}")


def GloFAS_process():
    """process glofas data"""

    processing_dates = GloFAS_download()

    if len(processing_dates) == 0:
        logging.info("no new glofas file to process!")
        sys.exit()

    for data_date in processing_dates:

        # final file names
        out_csv = os.path.join(settings.GLOFAS_DIR, "threspoints_" + data_date + ".csv")
        out_geojson = os.path.join(
            settings.GLOFAS_DIR, "threspoints_" + data_date + ".geojson"
        )
        if os.path.exists(out_csv) and os.path.exists(out_geojson):
            continue

        GloFAS_write(data_date)

    # return a list date to be processed with GFMS
    return processing_dates


def GFMS_url(bin_file):
    """host url of a given bin file"""
    datestr = bin_file.split("_")[2]
    baseurl = settings.config.get("gfms", "HOST")
    return f"{baseurl.rstrip('/')}/{datestr[:4]}/{datestr[:6]}/{bin_file}"


def GFMS_download(bin_file):
    """download a given bin file"""

    # find download url
    download_data_url = GFMS_url(bin_file)

    # check if .bin is already downloaded
    binfile_local = os.path.join(settings.GFMS_PROC_DIR, bin_file)
    vrt_file = binfile_local.replace(".bin", ".vrt")

    # check if the size is ok
    if os.path.exists(binfile_local):
        binsize = os.path.getsize(binfile_local)
        if binsize < 7000000:
            os.remove(binfile_local)

    if not os.path.exists(binfile_local):
        # download the data
        try:
            r = requests.get(download_data_url, allow_redirects=True)
            r.raise_for_status()

        except requests.exceptions.RequestException as e:
            logging.error(f"Download failed: {e.strerror}")
            print(f"Download failed: {e.strerror}")
            # sys.exit()
            return vrt_file

        open(binfile_local, "wb").write(r.content)
        logging.info(f"Download: {bin_file}")
        print(f"Download: {bin_file}")

    return GFMS_write_vrt(binfile_local)


def GFMS_write_vrt(binfile_local):
    """write the .hdr and .vrt of a downloaded bin file, return the vrt"""
    vrt_file = binfile_local.replace(".bin", ".vrt")

    # generate header file
    hdr_header = """NCOLS 2458
    NROWS 800
    XLLCORNER -127.25
    YLLCORNER -50

    CELLSIZE 0.125
    PIXELTYPE FLOAT
    BYTEORDER LSBFIRST
    NODATA_VALUE -9999
    """
    header_file = binfile_local.replace(".bin", ".hdr")
    with open(header_file, "w") as f:
        f.write(hdr_header)

    # generate vrt file: the bin's own 0.125 degree grid, not resampled, in
    # WGS 84 (EPSG:4326, as WKT so reading it needs no proj.db lookup)
    vrt_template = """<VRTDataset rasterXSize="2458" rasterYSize="800">
  <SRS dataAxisToSRSAxisMapping="2,1">GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563,AUTHORITY["EPSG","7030"]],AUTHORITY["EPSG","6326"]],PRIMEM["Greenwich",0,AUTHORITY["EPSG","8901"]],UNIT["degree",0.0174532925199433,AUTHORITY["EPSG","9122"]],AXIS["Latitude",NORTH],AXIS["Longitude",EAST],AUTHORITY["EPSG","4326"]]</SRS>
  <GeoTransform>-127.25, 0.125, 0, 50, 0, -0.125</GeoTransform>
  <VRTRasterBand dataType="Float32" band="1">
    <NoDataValue>-9999</NoDataValue>
    <SimpleSource>
      <SourceFilename relativeToVRT="1">{}</SourceFilename>
      <SourceBand>1</SourceBand>
    </SimpleSource>
  </VRTRasterBand>
</VRTDataset>"""

    # generate VRT file
    with open(vrt_file, "w") as f:
        f.write(vrt_template.format(os.path.basename(binfile_local)))

    return vrt_file


def GFMS_window_vrt(bin_file, window_dir):
    """download a bin file of the window into window_dir (once per run),
    return its vrt, or None if the host does not have it"""
    binfile_local = os.path.join(window_dir, bin_file)
    vrt_file = binfile_local.replace(".bin", ".vrt")
    if os.path.exists(vrt_file):
        return vrt_file
    if os.path.exists(binfile_local + ".missing"):
        return None
    try:
        r = requests.get(GFMS_url(bin_file), timeout=300)
        r.raise_for_status()
        if len(r.content) < 7000000:
            raise ValueError(f"only {len(r.content)} bytes")
    except Exception as e:
        # past the end of the forecast the host answers 404
        if not (isinstance(e, requests.HTTPError) and e.response.status_code == 404):
            logging.warning(f"GFMS window file not used: {bin_file}: {e}")
        open(binfile_local + ".missing", "w").close()
        return None
    with open(binfile_local, "wb") as f:
        f.write(r.content)
    vrt_file = GFMS_write_vrt(binfile_local)
    GFMS_save_image(vrt_file)
    return vrt_file


def GFMS_max_grid(paths):
    """per-pixel maximum of GFMS grids, with the profile of the first; dry
    cells are nodata (-9999), below every depth, so a plain maximum"""
    with rasterio.open(paths[0]) as src:
        grid = src.read(1)
        profile = {
            "driver": "GTiff",
            "width": src.width,
            "height": src.height,
            "count": 1,
            "dtype": "float32",
            "crs": src.crs,
            "transform": src.transform,
            "nodata": src.nodata,
        }
    for path in paths[1:]:
        with rasterio.open(path) as src:
            np.maximum(grid, src.read(1), out=grid)
    return grid, profile


def GFMS_window_max(vrt_file, window_dir):
    """per-pixel maximum of the grid of vrt_file and of the grids of the
    following 3-hourly times up to GFMS_WINDOW_HOURS, those the host has;
    written to a tiff in window_dir, whose path is returned"""
    stamp = os.path.basename(vrt_file)[len("Flood_byStor_") : -len(".vrt")]
    start = datetime.strptime(stamp, "%Y%m%d%H")
    paths, used = [vrt_file], []
    for hours in range(3, GFMS_WINDOW_HOURS + 1, 3):
        stamp_h = (start + timedelta(hours=hours)).strftime("%Y%m%d%H")
        window_vrt = GFMS_window_vrt(f"Flood_byStor_{stamp_h}.bin", window_dir)
        if window_vrt is not None:
            paths.append(window_vrt)
            used.append(hours)
    grid, profile = GFMS_max_grid(paths)
    logging.info(
        f"GFMS {stamp}: maximum of {len(used) + 1} grids, "
        f"up to +{used[-1] if used else 0} h of {GFMS_WINDOW_HOURS} h"
    )
    max_tiff = os.path.join(window_dir, f"Flood_byStor_{stamp}_max.tiff")
    with rasterio.open(max_tiff, "w", **profile) as dst:
        dst.write(grid, 1)
    return max_tiff


def GFMS_extract_by_watershed(vrt_file, window_dir=None):
    """extract and summary; with window_dir, of the maximum over the window
    (GFMS_window_max) instead of vrt_file alone"""

    # load watersheds data
    global WATERSHEDS  # declare global before potential Write
    if WATERSHEDS is None:
        WATERSHEDS = watersheds_gdb_reader()

    pfaf_id_list = WATERSHEDS.index.tolist()

    # setup output file
    headers_list = [
        "pfaf_id",
        "GFMS_TotalArea_km",
        "GFMS_perc_Area",
        "GFMS_MeanDepth",
        "GFMS_MaxDepth",
        "GFMS_Duration",
    ]
    # put summary file into proc folder before fix-duration
    summary_file = os.path.join(
        settings.GFMS_PROC_DIR, os.path.basename(vrt_file)[:-4] + ".csv"
    )
    if (
        not os.path.exists(summary_file) or os.path.getsize(summary_file) == 0
    ):  # ignores corrupted files
        with open(summary_file, "w") as f:
            writer = csv.writer(f)
            writer.writerow(headers_list)
    else:
        # already processed,
        return

    if window_dir and os.path.exists(vrt_file):
        vrt_file = GFMS_window_max(vrt_file, window_dir)

    # per-watershed flooded area (exact cell shares), depth mean and max
    # (watershed_cells.py); without the file every watershed gets 0s
    summary = None
    if os.path.exists(vrt_file):
        summary = raster_summary("gfms", vrt_file, WATERSHEDS)

    with open(summary_file, "a") as f:
        writer = csv.writer(f)

        for pfaf_id in pfaf_id_list:
            # a watershed without flooded cells gets 0s
            GFMS_TotalArea = 0.0
            GFMS_Area_percent = 0.0
            GFMS_MeanDepth = 0.0
            GFMS_MaxDepth = 0.0
            GFMS_Duration = 0
            if summary is not None and summary.at[pfaf_id, "has_data"]:
                GFMS_TotalArea = summary.at[pfaf_id, "area"]
                if GFMS_TotalArea > 100.0:
                    GFMS_Duration = 3
                GFMS_Area_percent = summary.at[pfaf_id, "perc_area"]
                GFMS_MeanDepth = summary.at[pfaf_id, "mean"]
                GFMS_MaxDepth = summary.at[pfaf_id, "max"]

            results_list = [
                pfaf_id,
                GFMS_TotalArea,
                GFMS_Area_percent,
                GFMS_MeanDepth,
                GFMS_MaxDepth,
                GFMS_Duration,
            ]
            writer.writerow(results_list)

    logging.info(f"generated: {summary_file}")

    return


def GFMS_data_extractor(bin_file, window_dir=None):
    """extract data from a given binfile (see GFMS_extract_by_watershed
    for window_dir); returns the image status of GFMS_store_image, or None
    without an image"""

    # download GFMS binfile, generate vrt file
    vrt_file = GFMS_download(bin_file)

    # extract data by watershed
    logging.info(f"processing: {vrt_file}")
    GFMS_extract_by_watershed(vrt_file, window_dir)

    if not os.path.exists(vrt_file):
        print(f"VRT not found: {bin_file}")
        return None

    return GFMS_save_image(vrt_file)


def GFMS_save_image(vrt_file):
    """save the grid of vrt_file as GFMS_IMG_DIR/<name>.tiff (see
    GFMS_store_image); returns its status, or None if it failed"""
    # generate tiff from bin file
    tiff_name = os.path.basename(vrt_file).replace(".vrt", ".tiff")
    tiff_file = os.path.join(settings.GFMS_IMG_DIR, tiff_name)
    # made in the processing folder (same disk: putting it in place is a
    # rename), the image folder is public
    new_tiff = os.path.join(settings.GFMS_PROC_DIR, "new_" + tiff_name)

    gdalcmd = f'gdal_translate -co TILED=YES -co COMPRESS=LZW -of GTiff "{vrt_file}" "{new_tiff}"'
    if os.system(gdalcmd) != 0:
        logging.error(f"gdal_translate failed: {tiff_file}")
        if os.path.exists(new_tiff):
            os.remove(new_tiff)
        return None

    return GFMS_store_image(new_tiff, tiff_file)


def GFMS_same_image(tiff_a, tiff_b):
    """same grid, position, nodata and values"""
    try:
        with rasterio.open(tiff_a) as a, rasterio.open(tiff_b) as b:
            if (a.shape, a.transform, a.crs, a.nodata) != (
                b.shape,
                b.transform,
                b.crs,
                b.nodata,
            ):
                return False
            return np.array_equal(a.read(1), b.read(1), equal_nan=True)
    except rasterio.errors.RasterioIOError:
        # an unreadable stored image is replaced
        return False


def GFMS_store_image(new_tiff, tiff_file):
    """put new_tiff in place of tiff_file, unless the stored image is the
    same (then new_tiff is dropped); a stored image that differs is moved to
    GFMS_IMG_EXPIRED_DIR, never deleted. Returns "new", "unchanged" or
    "replaced"."""
    status = "new"
    if os.path.exists(tiff_file):
        if GFMS_same_image(new_tiff, tiff_file):
            os.remove(new_tiff)
            logging.info(f"unchanged, kept: {tiff_file}")
            return "unchanged"
        os.makedirs(settings.GFMS_IMG_EXPIRED_DIR, exist_ok=True)
        # named after the time the stored one was made
        made = datetime.fromtimestamp(os.path.getmtime(tiff_file), timezone.utc)
        expired = os.path.join(
            settings.GFMS_IMG_EXPIRED_DIR,
            os.path.basename(tiff_file).replace(
                ".tiff", made.strftime("_%Y%m%dT%H%M%S.tiff")
            ),
        )
        shutil.move(tiff_file, expired)
        logging.info(f"expired: {tiff_file} -> {expired}")
        status = "replaced"
    shutil.move(new_tiff, tiff_file)
    logging.info(f"generated: {tiff_file}")
    return status


def GFMS_fix_duration(csv0, csvlist):
    """fix duration"""
    # notice the folder issue
    # base0 shall be in GFMS_SUM_DIR
    # unfixed are in GFMS_PROC_DIR

    # first check if csv0 exists
    basecsv = os.path.join(settings.GFMS_SUM_DIR, csv0)
    if os.path.exists(basecsv):
        df0 = pd.read_csv(basecsv)
        start_in = 0
    else:
        df0 = pd.read_csv(os.path.join(settings.GFMS_PROC_DIR, csvlist[0]))
        start_in = 1
        # also write out to SUM folder
        df0.to_csv(os.path.join(settings.GFMS_SUM_DIR, csvlist[0]), index=False)

    for name in csvlist[start_in:]:
        csv_file = os.path.join(settings.GFMS_PROC_DIR, name)
        df = pd.read_csv(csv_file)

        df["GFMS_Duration0"] = df["pfaf_id"].map(
            df0.set_index("pfaf_id")["GFMS_Duration"]
        )
        df["GFMS_Duration"] = df.apply(
            lambda row: (
                3 + int(row.GFMS_Duration0) if (row.GFMS_TotalArea_km > 100.0) else 0
            ),
            axis=1,
        )
        del df["GFMS_Duration0"]
        fix_csv = os.path.join(settings.GFMS_SUM_DIR, name)
        df.to_csv(fix_csv, index=False)
        logging.info(f"generated: {fix_csv}")
        df0 = None
        df0 = df
        df = None


def GFMS_processing(proc_dates_list):
    """process GFMS data with a given list of dates"""

    # the window files are downloaded again on every run: the host rewrites them
    window_dir = tempfile.mkdtemp(prefix="window_", dir=settings.GFMS_PROC_DIR)
    try:
        _GFMS_processing(proc_dates_list, window_dir)
    finally:
        shutil.rmtree(window_dir, ignore_errors=True)


def _GFMS_processing(proc_dates_list, window_dir):
    binhours = ["00", "03", "06", "09", "12", "15", "18", "21"]
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for data_date in proc_dates_list:
        real_date = data_date[:-2]

        fix_list = []
        for binhour in binhours:
            # only the times that have come: a later run makes the others
            if datetime.strptime(real_date + binhour, "%Y%m%d%H") > now:
                break
            bin_file = "Flood_byStor_" + real_date + binhour + ".bin"
            new_csv = "Flood_byStor_" + real_date + binhour + ".csv"
            # print(os.path.join(settings.GFMS_SUM_DIR, new_csv))
            if not os.path.exists(os.path.join(settings.GFMS_SUM_DIR, new_csv)):
                fix_list.append(new_csv)
                # process bin file, generate .csv - some might be missing
                GFMS_data_extractor(bin_file, window_dir)

        # run duration caculation
        # durations continue from the summary 3 h before the first new one
        # (a run may make only part of the day); if that one does not exist,
        # GFMS_fix_duration starts from the first new one
        if fix_list:
            first = datetime.strptime(fix_list[0][13:23], "%Y%m%d%H")
            base0 = (
                "Flood_byStor_"
                + (first - timedelta(hours=3)).strftime("%Y%m%d%H")
                + ".csv"
            )
            GFMS_fix_duration(base0, fix_list)
        else:
            logging.info(f"GFMS summary already exists for: {real_date}")

        # flood severity calculation
        # take the first file of each day ("00" hour bin)
        gfmscsv = os.path.join(
            settings.GFMS_SUM_DIR, "Flood_byStor_" + data_date + ".csv"
        )
        glofascsv = os.path.join(
            settings.GLOFAS_DIR, "threspoints_" + data_date + ".csv"
        )

        # in case of glofascsv data is missing, use the latest
        if not os.path.exists(glofascsv):
            glofas_latest = find_latest_glofas(settings.GLOFAS_DIR, data_date, "csv")
            glofascsv = os.path.join(settings.GLOFAS_DIR, glofas_latest)
            logging.warning(
                f"GloFAS threspoints_{data_date}.csv not published yet, falling "
                f"back to the latest available: {glofas_latest}"
            )

        # set directory for adding/removing files
        curdir = os.getcwd()
        os.chdir(settings.GFMS_PROC_DIR)

        # TODO: handle missing file
        # if os.path.exists(glofascsv) and os.path.exists(gfmscsv):
        # only proceed if valid data is present
        try:
            flood_severity(gfmscsv, glofascsv, real_date)  # if exists checked inside
        except Exception as e:
            logging.error(
                f"Flood severity calculation (GFMS_MoM) failed for {real_date}: {e}"
            )
            sys.exit(1)

        # zip GFMS data after processing
        zipped = os.path.join(settings.GFMS_PROC_DIR, f"gfms_{real_date}.zip")

        # Only touch the archive when there is something to add. Opening it in
        # "w" mode unconditionally truncated a good archive to an empty 22-byte
        # one on every rerun, because the source files had already been deleted
        # by the first run of the day. "a" is not an option either: it appends
        # without checking names, so reruns stacked duplicate entries.
        files = glob.glob(
            os.path.join(settings.GFMS_PROC_DIR, f"Flood_byStor_{real_date}*.*")
        )
        if not files:
            logging.info(f"nothing to archive for {real_date}")
        else:
            # Rebuild into a temp archive carrying over anything already stored
            # (a run may only cover part of the day), then swap it in
            # atomically so the archive is never left truncated.
            tmp_zip = f"{zipped}.tmp"
            names = {os.path.basename(f) for f in files}
            carried = 0
            with zipfile.ZipFile(tmp_zip, "w", zipfile.ZIP_DEFLATED) as z:
                if os.path.exists(zipped):
                    try:
                        with zipfile.ZipFile(zipped) as old_z:
                            for item in old_z.infolist():
                                if item.filename not in names:
                                    z.writestr(item, old_z.read(item.filename))
                                    carried += 1
                    except zipfile.BadZipFile:
                        logging.warning(f"ignoring corrupt archive: {zipped}")
                for f in files:
                    z.write(f, arcname=os.path.basename(f))
            os.replace(tmp_zip, zipped)
            logging.info(f"archived {len(files)} new + {carried} existing: {zipped}")

            # remove only the files that were just archived
            for filePath in files:
                try:
                    os.remove(filePath)
                except OSError:
                    logging.warning(f"Error while deleting file : {filePath}")

        os.chdir(curdir)

    return


def GFMS_cron():
    """run GFMS cron job"""

    # process GloFAS data
    processing_dates = GloFAS_process()
    # process GFMS data
    # processing_dates = ['2021120200']
    GFMS_processing(processing_dates)

    # check if today's date are generated
    # if now hwrf data, then generate the output for 00 hour
    hwrf_flag = hwrf_today()
    if hwrf_flag:
        return
    # otherwise
    today = datetime.now(timezone.utc)
    tstr = datetime.strftime(today, "%Y%m%d")
    tstr = tstr + "00"
    gfmscsv = os.path.join(settings.GFMS_SUM_DIR, "Flood_byStor_" + tstr + ".csv")
    glofascsv = os.path.join(settings.GLOFAS_DIR, "threspoints_" + tstr + ".csv")
    if os.path.exists(gfmscsv) and os.path.exists(glofascsv):
        logging.info(f"no hwrf: {tstr}, generating ...")
        # update_HWRF_MoM(tstr)
        # update_HWRFMoM_DFO_VIIRS(tstr)
        # final_alert_pdc(tstr)
        hwrf_workflow(tstr)


def GFMS_fixdate(adate):
    """run cron job"""
    # cron steup cd ~/ModelofModels/data && python datatool.py --cron
    # run every three hours
    # edit: crontab -e
    # 5 0,3,6,9,12,15,18,21 * * * commnad

    # it is likly only one date: 2020051600
    # processing_dates = GloFAS_process()
    # check if GMS data is available
    # processing_dates = ['2020061800','2020061900','2020062000']
    if len(adate) == 8:
        adate = adate + "00"
    processing_dates = [adate]
    binhours = ["00", "03", "06", "09", "12", "15", "18", "21"]
    for data_date in processing_dates:
        real_date = data_date[:-2]
        for binhour in binhours:
            # bin_file = "Flood_byStor_" + real_date + binhour + ".bin"
            summary_file = "Flood_byStor_{}.csv".format(real_date + binhour)
            summary_file = os.path.join(settings.GFMS_SUM_DIR, summary_file)
            # remove partial processed summary file
            if os.path.exists(summary_file):
                os.remove(summary_file)
            # also need remove the file processing folder
            csv_in_proc = "Flood_byStor_{}.csv".format(real_date + binhour)
            csv_in_proc = os.path.join(settings.GFMS_PROC_DIR, csv_in_proc)
            if os.path.exists(csv_in_proc):
                os.remove(csv_in_proc)
    # reprocessing file
    GFMS_processing(processing_dates)


def debug():
    """debug the function"""
    # issue 38: gfms broken bin file
    binfile = "Flood_byStor_2022103103.bin"
    GFMS_data_extractor(binfile)


def main():
    """run the cron job"""
    GFMS_cron()


if __name__ == "__main__":
    main()
