#!/bin/bash
# setup_crontab.sh — Installs MoMProduction cron jobs for all data-source runs.
# The monitor job is intentionally excluded; add it separately if needed.
#
# Usage:
#   chmod +x setup_crontab.sh   # make executable (only needed once)
#   ./setup_crontab.sh
#   Or just:
#   bash ./setup_crontab.sh
#
# Jobs are launched through run_mom_job.sh, which activates the conda
# environment before calling MoM_run.py. Calling the env's python by absolute
# path is NOT sufficient: without activation the env's bin/ is missing from
# PATH and the GDAL/PROJ activate.d hooks never run, so console tools such as
# gdal_translate cannot be resolved and image products are silently skipped.
#
# Safe to re-run — strips existing MoM entries (both the current
# run_mom_job.sh form and the legacy direct MoM_run.py form) before appending
# the definitions below fresh. All other cron jobs are untouched.

set -euo pipefail

# default: the folder of this script (the repository root)
PROJECT_DIR="${PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
RUNNER="$PROJECT_DIR/run_mom_job.sh"
LOG_DIR="$PROJECT_DIR/logs"

if [ ! -f "$RUNNER" ]; then
    echo "setup_crontab.sh: runner not found at $RUNNER" >&2
    exit 1
fi

chmod +x "$RUNNER"
mkdir -p "$LOG_DIR"

CRON_JOBS=(
    "0 4,11,14,21 * * * $RUNNER -j GFMS >> $LOG_DIR/gfms.log 2>&1"
    "0 2,7,13,19 * * * $RUNNER -j HWRF >> $LOG_DIR/hwrf.log 2>&1"
    "0 3,10,23 * * * $RUNNER -j DFO >> $LOG_DIR/dfo.log 2>&1"
    "0 5,12,17 * * * $RUNNER -j VIIRS >> $LOG_DIR/viirs.log 2>&1"
    "30 2,7,13,19 * * * $RUNNER -j HAFS >> $LOG_DIR/hafs.log 2>&1"
)

# Remove existing MoM entries (current and legacy forms), then append fresh.
(crontab -l 2>/dev/null | grep -vE "MoM_run\.py|run_mom_job\.sh" || true; \
 printf '%s\n' "${CRON_JOBS[@]}") | crontab -

echo "Done. MoM cron jobs installed:"
printf '  %s\n' "${CRON_JOBS[@]}"
