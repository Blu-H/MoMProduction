"""
Settings for MoM Production
    -- production.cfg
    -- define folder structure
        -- folders for data processing
        -- folders for data products

"""

import configparser
import logging
import os
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DATA_DIR = os.path.join(BASE_DIR, "data")

config = configparser.ConfigParser(allow_no_value=True)
config.read(os.path.join(BASE_DIR, "production.cfg"))

# config directory
# base directory for downloading and processing data
WORKING_DIR = os.path.expanduser(
    config.get("general", "WORKING_DIR").replace("/", os.sep)
)
# base directory for the data products
PRODUCT_DIR = os.path.expanduser(
    config.get("general", "PRODUCT_DIR").replace("/", os.sep)
)

# config GLOFAS directory
GLOFAS_PROC_DIR = os.path.join(WORKING_DIR, config.get("processing_dir", "glofas"))
GLOFAS_DIR = os.path.join(PRODUCT_DIR, config.get("products_dir", "GLOFAS"))
GLOFAS_SUM_DIR = os.path.join(PRODUCT_DIR, config.get("products_dir", "GLOFAS"))

# config GFMS directory
GFMS_PROC_DIR = os.path.join(WORKING_DIR, config.get("processing_dir", "gfms"))
GFMS_DIR = os.path.join(PRODUCT_DIR, config.get("products_dir", "GFMS"))
GFMS_SUM_DIR = os.path.join(GFMS_DIR, "GFMS_summary")
GFMS_IMG_DIR = os.path.join(GFMS_DIR, "GFMS_image")
# stored images replaced by a newer, different one
GFMS_IMG_EXPIRED_DIR = os.path.join(GFMS_DIR, "GFMS_images_expired")
GFMS_MOM_DIR = os.path.join(GFMS_DIR, "GFMS_MoM")

# config DFO directory
DFO_PROC_DIR = os.path.join(WORKING_DIR, config.get("processing_dir", "dfo"))
DFO_DIR = os.path.join(PRODUCT_DIR, config.get("products_dir", "DFO"))
DFO_SUM_DIR = os.path.join(DFO_DIR, "DFO_summary")
DFO_IMG_DIR = os.path.join(DFO_DIR, "DFO_image")
DFO_MOM_DIR = os.path.join(DFO_DIR, "DFO_MoM")

# config VIIRS directory
VIIRS_PROC_DIR = os.path.join(WORKING_DIR, config.get("processing_dir", "VIIRS"))
VIIRS_DIR = os.path.join(PRODUCT_DIR, config.get("products_dir", "VIIRS"))
VIIRS_SUM_DIR = os.path.join(VIIRS_DIR, "VIIRS_summary")
VIIRS_IMG_DIR = os.path.join(VIIRS_DIR, "VIIRS_image")
VIIRS_MOM_DIR = os.path.join(VIIRS_DIR, "VIIRS_MoM")

# config HWRF directory
HWRF_PROC_DIR = os.path.join(WORKING_DIR, config.get("processing_dir", "hwrf"))
HWRF_DIR = os.path.join(PRODUCT_DIR, config.get("products_dir", "HWRF"))
HWRF_SUM_DIR = os.path.join(HWRF_DIR, "HWRF_summary")
# summary file names in HWRF_SUM_DIR: <prefix>.YYYYMMDDHHrainfall.csv (the
# HAFS chain runs the HWRF MoM with "hafs" on the HAFS summaries)
HWRF_SUM_PREFIX = "hwrf"
# model tag in the HWRF MoM, DFO MoM and final alert file names, e.g.
# Final_Attributes_YYYYMMDDHH<tag>Updated.csv (the HAFS chain uses "HAFS")
HWRF_FILE_TAG = "HWRF"
HWRF_IMG_DIR = os.path.join(HWRF_DIR, "HWRF_image")
HWRF_MOM_DIR = os.path.join(HWRF_DIR, "HWRF_MoM")
HWRF_BACKUP_DIR = os.path.join(HWRF_DIR, "HWRF_host_data_backups")
# HWRF time_delay: 6 hours
HWRF_TIME_DELAY = 6

# final product
FINAL_MOM_DIR = os.path.join(PRODUCT_DIR, config.get("products_dir", "FINAL"))
# publish the final alert csv files (run_mom_job.sh runs publish_alerts only when on)
PUBLISH_CSV = config.getboolean("general", "PUBLISH_CSV", fallback=False)
# publish the tiles (run_mom_job.sh runs publish_tiles only when on)
PUBLISH_TILES = config.getboolean("general", "PUBLISH_TILES", fallback=False)

# config HAFS (optional, independent of the HWRF workflow; off unless the
# [hafs] section of production.cfg turns it on)
HAFS_ENABLED = config.getboolean("hafs", "ENABLED", fallback=False)
HAFS_HOST = config.get(
    "hafs", "HOST", fallback="https://noaa-nws-hafs-pds.s3.amazonaws.com/"
)
HAFS_MODEL = config.get("hafs", "MODEL", fallback="hfsa")
HAFS_LOOKBACK_DAYS = config.getint("hafs", "LOOKBACK_DAYS", fallback=2)
HAFS_PROC_DIR = os.path.join(WORKING_DIR, "hafs")
HAFS_DIR = os.path.join(PRODUCT_DIR, "HAFS")
HAFS_SUM_DIR = os.path.join(HAFS_DIR, "HAFS_summary")
HAFS_IMG_DIR = os.path.join(HAFS_DIR, "HAFS_image")
HAFS_MOM_DIR = os.path.join(HAFS_DIR, "HAFS_MoM")
HAFS_TRACK_DIR = os.path.join(HAFS_DIR, "HAFS_track")
HAFS_BACKUP_DIR = os.path.expanduser(
    config.get(
        "hafs",
        "BACKUP_DIR",
        fallback=os.path.join(HAFS_DIR, "HAFS_host_data_backups"),
    )
)
DFO_HAFS_DIR = os.path.join(DFO_DIR, "DFO_HAFS_MoM")
VIIRS_HAFS_DIR = os.path.join(VIIRS_DIR, "VIIRS_HAFS_MoM")
FINAL_HAFS_DIR = os.path.join(PRODUCT_DIR, "Final_Alerts_hafs")

# config watershed shp file
WATERSHED_DIR = os.path.join(BASE_DIR, "data", "watershed_shp")
WATERSHED_SHP = os.path.join(WATERSHED_DIR, "Watershed_pfaf_id.shp")

# setup logging
# a new log for each month, and a separate file per job when the job is known
LOG_DIR = os.path.join(WORKING_DIR, config.get("processing_dir", "logs"))
LOG_FORMAT = "%(asctime)s - %(module)s - %(levelname)s : %(message)s"


def logfile_path(job=None):
    """monthly log file path, suffixed with the job name when one is given"""
    todays_date = datetime.now(timezone.utc)
    name = "{year}_{month}".format(year=todays_date.year, month=todays_date.month)
    if job:
        name = "{}_{}".format(name, str(job).upper())
    return os.path.join(LOG_DIR, "{}.log".format(name))


def configure_logging(job=None):
    """(re)point the root logger at this job's log file"""
    try:
        logging.basicConfig(
            filename=logfile_path(job),
            format=LOG_FORMAT,
            level=logging.INFO,
            force=True,
        )
    except Exception:
        pass


# default target until the job name is known: MoM_run calls this again with it
logfile = logfile_path()
configure_logging()
