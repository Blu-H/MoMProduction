#!/bin/bash
#
# run_mom_job.sh -- cron entry point for MoM Production jobs.
#
# Activates the conda environment rather than just calling the env's
# interpreter by absolute path. Activation is what puts $CONDA_PREFIX/bin on
# PATH and runs the GDAL/PROJ activate.d hooks (GDAL_DATA, GDAL_DRIVER_PATH,
# PROJ_DATA, CPL_ZIP_ENCODING). Console tools such as gdal_translate are only
# resolvable by name once that has happened.
#
# Usage -- arguments are passed straight through to MoM_run.py:
#   run_mom_job.sh -j GFMS
#   run_mom_job.sh -j DFO --fixdate 20261007
#
# Overridable via the environment: CONDA_SH, CONDA_ENV, PROJECT_DIR. The
# conda base is found as setup.sh finds it (conda info --base, else
# $HOME/miniconda3).

set -euo pipefail

CONDA_SH="${CONDA_SH:-$(conda info --base 2>/dev/null || echo "$HOME/miniconda3")/etc/profile.d/conda.sh}"
CONDA_ENV="${CONDA_ENV:-momenv}"
# default: the folder of this script (the repository root)
PROJECT_DIR="${PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"

if [ ! -f "$CONDA_SH" ]; then
    echo "run_mom_job.sh: conda profile not found at $CONDA_SH" >&2
    exit 1
fi

# conda.sh and the activate.d hooks reference unset variables; relax nounset
# while they run, then restore it for our own code.
set +u
# shellcheck disable=SC1090
source "$CONDA_SH"
conda activate "$CONDA_ENV"
set -u

if ! command -v gdal_translate >/dev/null; then
    echo "run_mom_job.sh: gdal_translate not on PATH after activating '$CONDA_ENV'" >&2
    exit 1
fi

cd "$PROJECT_DIR"
mkdir -p logs

# not exec'd, so the alert push below still runs; the job's exit status is kept.
status=0
# one run per job at a time ($2 is the -j value, so a --fixdate run waits for it)
flock -n "/tmp/mom_job_${2:-all}.lock" python MoM_run.py "$@" || status=$?

# the final alerts folder to publish: HAFS's when HAFS is enabled, else HWRF's;
# none after the HWRF job when HAFS is enabled, or the HAFS job when it is not
alerts_dir=$(python -c "
import sys, settings
job = sys.argv[1]
if not ((job == 'HWRF' and settings.HAFS_ENABLED) or (job == 'HAFS' and not settings.HAFS_ENABLED)):
    print(settings.FINAL_HAFS_DIR if settings.HAFS_ENABLED else settings.FINAL_MOM_DIR)
" "${2:-}")

# push the new final alerts to GitHub, only when PUBLISH_CSV is on in
# production.cfg (skipped when no token is configured);
# a failed push never changes the job's exit status
if [ -n "$alerts_dir" ] && python -c "import sys, settings; sys.exit(not settings.PUBLISH_CSV)"; then
    python -m processing.publish.publish_alerts "$alerts_dir" || echo "run_mom_job.sh: publish_alerts failed" >&2
fi

# publish the tiles, only when PUBLISH_TILES is on in production.cfg;
# a failed publish never changes the job's exit status
if [ -n "$alerts_dir" ] && python -c "import sys, settings; sys.exit(not settings.PUBLISH_TILES)"; then
    python -m processing.publish.publish_tiles "$alerts_dir" || echo "run_mom_job.sh: publish_tiles failed" >&2
fi

exit "$status"
