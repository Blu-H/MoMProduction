#!/bin/bash
# Container start-up: check the configuration, create the folder tree, install
# the cron schedule, then hand over to cron in the foreground.
set -euo pipefail

cd /root/MoMProduction

if [ ! -f production.cfg ]; then
    echo "docker-entrypoint.sh: production.cfg is missing. Mount it at" >&2
    echo "  /root/MoMProduction/production.cfg (see sample_production.cfg)" >&2
    exit 1
fi

source /opt/conda/etc/profile.d/conda.sh
conda activate momenv

# folder tree and the watershed shapefile
python initialize.py

# the five jobs, through run_mom_job.sh
./setup_crontab.sh

# any argument is run instead of cron, e.g. docker run ... momproduction \
#   ./run_mom_job.sh -j GFMS
if [ "$#" -gt 0 ]; then
    exec "$@"
fi

echo "cron started; job output goes to logs/<job>.log"
exec cron -f
