# MoMProduction in a container: the conda environment, the five cron jobs and
# cron itself, so the container runs the production schedule unattended.
#
# The repository is copied from the build context, not cloned, so the image is
# built from the checkout in hand. setup.sh is not used: it installs system
# packages with sudo, sets the timezone with timedatectl and resets the
# checkout to its own remote, none of which apply to an image build.
FROM continuumio/miniconda3:latest

# a container takes its timezone from TZ (on a server setup.sh sets it with
# timedatectl); all job schedules and file dates are UTC
ENV TZ=UTC
ENV DEBIAN_FRONTEND=noninteractive

RUN ln -snf "/usr/share/zoneinfo/$TZ" /etc/localtime && echo "$TZ" > /etc/timezone \
    && apt-get update \
    && apt-get install -y --no-install-recommends cron wget \
    && rm -rf /var/lib/apt/lists/*

# run_mom_job.sh looks for the conda base with "conda info --base" and falls
# back to $HOME/miniconda3; cron runs with a minimal PATH, so conda is not on
# it and the fallback is what resolves
RUN ln -s /opt/conda /root/miniconda3

WORKDIR /root/MoMProduction

# the environment first, so it is only rebuilt when environment.yml changes
COPY environment.yml ./
RUN conda config --add channels conda-forge \
    && conda config --set channel_priority strict \
    && conda env create -n momenv -f environment.yml \
    && conda install -n momenv --override-channels -c conda-forge libgdal-hdf4=3.12.2 --no-update-deps -y \
    && conda clean -afy

COPY . ./
RUN chmod +x run_mom_job.sh setup_crontab.sh docker-entrypoint.sh

# products and processing workspace (WORKING_DIR / PRODUCT_DIR of
# production.cfg); keep them in a volume so they outlive the container
VOLUME ["/root/MoM"]

ENTRYPOINT ["./docker-entrypoint.sh"]
