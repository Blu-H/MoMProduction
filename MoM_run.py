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
import sys

# needed to add gdal tp PATH, so that "gdal" console commands are accessible through os.system or subprocess
# even in the modules that don't import Python gdal bindings (especially for Windows .venv)
from osgeo import gdal

# append "wget" path for Windows
if os.name == "nt":
    current_dir = os.path.dirname(os.path.abspath(__file__))
    installers_path = os.path.join(current_dir, "first_setup")
    os.environ["PATH"] = installers_path + os.pathsep + os.environ["PATH"]

from DFO_MoM import batchrun_DFO_MoM
from DFO_tool import DFO_cron
from GFMS_tool import GFMS_cron, GFMS_fixdate
from HWRF_MoM import batchrun_HWRF_MoM
from HWRF_tool import HWRF_cron
from VIIRS_MoM import batchrun_VIIRS_MoM
from VIIRS_tool import VIIRS_cron


current_dir = os.path.dirname(os.path.abspath(__file__))
installers_path = os.path.join(current_dir, "first_setup")
sys.path.insert(0, installers_path)


def _getParser():
    parser = argparse.ArgumentParser(
        description=prolog,
        epilog=epilog,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    joblist = ["GFMS", "HWRF", "HWRF_MOM", "DFO", "DFO_MOM", "VIIRS", "VIIRS_MOM"]
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


def run_job(cronjob):
    """run various cron job"""
    logging.info("run " + cronjob)
    print("Main PID:", os.getpid())
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
    else:
        return


def run_fixdate(cronjob, adate):
    """run fixdate funtion"""
    logging.info("run fixdate {} {}".format(cronjob, adate))
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
    if results.adate:
        run_fixdate(results.job, results.adate)
    else:
        run_job(results.job)


if __name__ == "__main__":
    main()
