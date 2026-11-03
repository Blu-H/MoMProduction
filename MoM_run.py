"""
main script to run various MoM processing jobs
"""

prolog = """
**PROGRAM**
    MoM_run.py
      
**PURPOSE**
    main script to run various MoM processing jobs

**USAGE**
"""
epilog = """
**EXAMPLE**
    MoM_run.py 
               
"""

import argparse
import logging
import os
import shutil
import sys

# point PROJ at GDAL's own proj.db in a Windows .venv; before any PROJ-dependent import
import processing.proj_env  # noqa: F401

# needed to add gdal tp PATH, so that "gdal" console commands are accessible through os.system or subprocess
# even in the modules that don't import Python gdal bindings (especially for Windows .venv)
from osgeo import gdal

# append "wget" path for Windows
if os.name == "nt":
    current_dir = os.path.dirname(os.path.abspath(__file__))
    installers_path = os.path.join(current_dir, "first_setup")
    os.environ["PATH"] = installers_path + os.pathsep + os.environ["PATH"]

import settings
from processing.dfo.DFO_MoM import batchrun_DFO_MoM
from processing.dfo.DFO_tool import DFO_cron
from processing.gfms.GFMS_tool import GFMS_cron, GFMS_fixdate
from processing.hwrf.HWRF_MoM import batchrun_HWRF_MoM
from processing.hwrf.HWRF_tool import HWRF_cron
from processing.viirs.VIIRS_MoM import batchrun_VIIRS_MoM
from processing.viirs.VIIRS_tool import VIIRS_cron
from processing.utilities import run_label

# the cron schedule of each job, as setup_crontab.sh installs it
CRON_SCHEDULE = {
    "GFMS": [4, 11, 14, 21],
    "HWRF": [2, 7, 13, 19],
    "DFO": [3, 10, 23],
    "VIIRS": [5, 12, 17],
    "HAFS": ["02:30", "07:30", "13:30", "19:30"],
}


current_dir = os.path.dirname(os.path.abspath(__file__))
installers_path = os.path.join(current_dir, "first_setup")
sys.path.insert(0, installers_path)


def _getParser():
    parser = argparse.ArgumentParser(
        description=prolog,
        epilog=epilog,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    joblist = [
        "GFMS",
        "HWRF",
        "HWRF_MOM",
        "DFO",
        "DFO_MOM",
        "VIIRS",
        "VIIRS_MOM",
        "HAFS",
    ]
    parser.add_argument(
        "-j",
        "--job",
        action="store",
        type=str.upper,
        dest="job",
        required=True,
        help="run a job",
        choices=joblist,
    )
    parser.add_argument(
        "-fd",
        "--fixdate",
        action="store",
        dest="adate",
        required=False,
        help="fix a date",
    )

    return parser


# console tools the jobs shell out to by name. Without the conda environment
# activated they are unresolvable: gdal_translate then converts nothing and the
# failure only surfaces much later (a missing mosaic, or a silently partial
# one). Checked once per run, before any job starts.
REQUIRED_TOOLS = ("gdal_translate", "wget")


def require_tools():
    """exit before doing any work if a console tool is not on PATH"""
    missing = [t for t in REQUIRED_TOOLS if shutil.which(t) is None]
    if missing:
        logging.error(
            f"not on PATH: {', '.join(missing)} - activate the conda "
            "environment first (run_mom_job.sh does it)"
        )
        sys.exit(1)


def run_job(cronjob):
    """run various cron job"""
    logging.info(f"run {cronjob} ({run_label(CRON_SCHEDULE.get(cronjob, []))})")
    logging.info(f"main PID: {os.getpid()}")
    if cronjob == "GFMS":
        GFMS_cron()
    elif cronjob == "HWRF":
        HWRF_cron()
        batchrun_HWRF_MoM()
    elif cronjob == "DFO":
        DFO_cron()
        batchrun_DFO_MoM()
    elif cronjob == "VIIRS":
        VIIRS_cron()
        batchrun_VIIRS_MoM()
    elif cronjob == "HAFS":
        # imported here only: the other jobs never load the HAFS code
        from processing.hafs.HAFS_tool import HAFS_cron

        HAFS_cron()
    else:
        logging.warning(f"unknown job: {cronjob}")
        return

    logging.info(f"finished {cronjob}")


def run_fixdate(cronjob, adate):
    """run fixdate funtion"""
    logging.info(f"run fixdate {cronjob} {adate}")
    if cronjob == "GFMS":
        GFMS_fixdate(adate)
    elif cronjob == "VIIRS":
        VIIRS_cron(adate)
    else:
        return


def main():
    """execute momjob"""
    # Read command line arguments
    parser = _getParser()
    results = parser.parse_args()
    # keep each job's log in its own file
    settings.configure_logging(results.job)
    require_tools()
    if results.adate:
        run_fixdate(results.job, results.adate)
    else:
        run_job(results.job)


if __name__ == "__main__":
    main()
