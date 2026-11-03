# ModelofModels Production
The following guide is tested on Ubuntu 18.04 and 20.04 LTS.  
The current testing VM is a m1.small instance on [Jetstream cloud](https://portal.xsede.org/jetstream) with 2 vcpus, 4GB memory, 20GB storage with an extra 100GB volume attached.   

**Note**: A non-administrator user "tester" in Ubuntu is used this guide. Please update the path in cron-job examples with the right user name for your installation. 

## 0. Timezone setup
Upstream data are produced by agencies across the world, UTC time zone is recommended.  
In Ubuntu, set timezone to UTC: 
```
sudo timedatectl set-timezone UTC
```
And run "timedatectl" to check: 
```
                      Local time: Mon 2022-04-04 01:45:14 UTC
                  Universal time: Mon 2022-04-04 01:45:14 UTC
                        RTC time: Mon 2022-04-04 01:45:14
                       Time zone: UTC (UTC, +0000)
       System clock synchronized: yes
systemd-timesyncd.service active: yes
                 RTC in local TZ: no
```
## 1. Setup Python environment
All installation steps are packaged into Linux and Windows Powershell installers:
```
bash ./setup.sh
```
or
```
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\setup.ps1
```
This includes Python installation/update, repo cloning, conda installation and custom venv creation and activation. 

## 2. Initialize the setup
Please copy [sample_production.cfg](https://github.com/Global-Flood-Assessment/MoMProduction/blob/main/sample_production.cfg) to **production.cfg**, or run initialize.py, it will do the copy.  
Check production.cfg: 
- in general section, change WORKING_DIR (base directory for downloading and processing data) and PRODUCT_DIR (base directory for the data products) if necessary;
- in glofas section, fill in user/passwd for ftp site;  
- in dfo section, fill in token for download [more on Automating NRT Downloads](https://nrt4.modaps.eosdis.nasa.gov/archive/allData/61)  
```
[general]
WORKING_DIR: ~/MoM/Processing
PRODUCT_DIR: ~/MoM/Products

[glofas]
HOST: data-portal.ecmwf.int
USER: ???
PASSWD: ???
DIRECTORY: /for_PDC

[dfo]
TOKEN: ???
```
Initialize the production setup: 
```
python initialize.py
```
It performs the following tasks:   
- create the folder structures defined in production.cfg
- check username/password, token in production.cfg
- unzip watershed.shp 

## 3. Test run
All the processing jobs can be tested in the following orders. It may take several hours to finish, it produces data products from the latest several days.
```
python MoM_run.py -j GFMS
python MoM_run.py -j HWRF
python MoM_run.py -j DFO
python MoM_run.py -j VIIRS
```
The outputs to the console are very minimal, the progress can be checked through the log file under processing/logs folder. The log is generated each month, e.g 2021_11.log, 2021_12.log. 
```
sample log output
2021-12-09 10:39:18,174 - MoM_run - INFO : run GFMS
2021-12-09 10:39:33,055 - GFMS_tool - INFO : processing GLoFAS: 2021120200
2021-12-09 10:39:34,705 - GFMS_tool - INFO : generated: Products/GLOFAS/threspoints_2021120200.csv
2021-12-09 10:39:35,313 - GFMS_tool - INFO : processing GLoFAS: 2021120300
2021-12-09 10:39:36,909 - GFMS_tool - INFO : generated: Products/GLOFAS/threspoints_2021120300.csv
2021-12-09 10:39:37,514 - GFMS_tool - INFO : processing GLoFAS: 2021120400
2021-12-09 10:39:39,112 - GFMS_tool - INFO : generated: Products/GLOFAS/threspoints_2021120400.csv
2021-12-09 10:39:39,714 - GFMS_tool - INFO : processing GLoFAS: 2021120500
2021-12-09 10:39:41,349 - GFMS_tool - INFO : generated: Products/GLOFAS/threspoints_2021120500.csv
2021-12-09 10:39:41,952 - GFMS_tool - INFO : processing GLoFAS: 2021120600
2021-12-09 10:39:43,555 - GFMS_tool - INFO : generated: Products/GLOFAS/threspoints_2021120600.csv
2021-12-09 10:39:44,166 - GFMS_tool - INFO : processing GLoFAS: 2021120700
2021-12-09 10:39:45,781 - GFMS_tool - INFO : generated: Products/GLOFAS/threspoints_2021120700.csv
2021-12-09 10:39:46,389 - GFMS_tool - INFO : processing GLoFAS: 2021120800
2021-12-09 10:39:48,042 - GFMS_tool - INFO : generated: Products/GLOFAS/threspoints_2021120800.csv
2021-12-09 10:39:48,677 - GFMS_tool - INFO : processing GLoFAS: 2021120900
2021-12-09 10:39:50,289 - GFMS_tool - INFO : generated: Products/GLOFAS/threspoints_2021120900.csv
2021-12-09 10:39:53,383 - GFMS_tool - INFO : Download: Flood_byStor_2021120200.bin
2021-12-09 10:39:53,385 - GFMS_tool - INFO : processing: Processing/gfms/Flood_byStor_2021120200.vrt
2021-12-09 10:41:43,808 - GFMS_tool - INFO : generated: Processing/gfms/Flood_byStor_2021120200.csv
2021-12-09 10:41:44,154 - GFMS_tool - INFO : generated: Products/GFMS/GFMS_image/Flood_byStor_2021120200.tiff
2021-12-09 10:41:47,233 - GFMS_tool - INFO : Download: Flood_byStor_2021120203.bin
...
```   
## 4. Setup cron jobs
Each datasets are released in difference schedules, GloFAS, DFO, VIIRS are released once a day; GFMS are the predication data in 3-hour interval and available in advance, amd are processed along with GloFAS data. HWRF is updated every 6 six hours under certain weather conditions, there can be no HWRF data released in days. One hour interval between each job are suggested. The script for each job check if there is the new data need to be processed.  
On the production host, install all four jobs with the provided script:
```
chmod +x setup_crontab.sh
./setup_crontab.sh
```
It is safe to re-run; it replaces the existing MoM entries and leaves every other cron job untouched.

To set the jobs up by hand, use the [crontab](https://www.digitalocean.com/community/tutorials/how-to-use-cron-to-automate-tasks-ubuntu-1804) command. Jobs must be launched through `run_mom_job.sh`, **not** by calling the environment's python directly. The wrapper activates the conda environment, which is what puts the environment's `bin/` on `PATH` and runs the GDAL/PROJ `activate.d` hooks; without it `gdal_translate` cannot be resolved and image products are silently skipped. The wrapper reads `CONDA_SH`, `CONDA_ENV` and `PROJECT_DIR` from the environment, so a non-root install only needs those three values changed.

Sample crontab entries, assuming miniconda is installed under /home/tester/miniconda3. Keep at least 1 hour interval between any two jobs:  
```
CONDA_SH=/home/tester/miniconda3/etc/profile.d/conda.sh
CONDA_ENV=mom
PROJECT_DIR=/home/tester/MoMProduction

0 4,11,14,21 * * * /home/tester/MoMProduction/run_mom_job.sh -j GFMS >> /home/tester/MoMProduction/logs/gfms.log 2>&1
0 2,7,13,19 * * * /home/tester/MoMProduction/run_mom_job.sh -j HWRF >> /home/tester/MoMProduction/logs/hwrf.log 2>&1
0 3,10,23 * * * /home/tester/MoMProduction/run_mom_job.sh -j DFO >> /home/tester/MoMProduction/logs/dfo.log 2>&1
0 5,12,17 * * * /home/tester/MoMProduction/run_mom_job.sh -j VIIRS >> /home/tester/MoMProduction/logs/viirs.log 2>&1
```
**Notes:** Please reference [crontab_list.txt](https://github.com/Global-Flood-Assessment/MoMProduction/blob/dev/crontab_list.txt) for the latest cron setup. 
## 4.1 Docker (environment, cron and all jobs in one container)
`Dockerfile` builds an image from the checkout in hand: the `momenv` conda environment from `environment.yml` (plus `libgdal-hdf4`), `cron`, and the repository itself; `docker-entrypoint.sh` then runs `initialize.py`, installs the schedule with `setup_crontab.sh` and hands over to `cron` in the foreground, so a single container runs all five jobs on the production schedule. `production.cfg` is deliberately not baked into the image: mount it, together with a volume for `WORKING_DIR`/`PRODUCT_DIR` (`/root/MoM`), and an `.env` as well if the alert push is used.
```
docker build -t momproduction .
docker run -d --name mom --restart unless-stopped \
    -v /path/to/production.cfg:/root/MoMProduction/production.cfg:ro \
    -v mom_data:/root/MoM \
    momproduction
docker exec mom crontab -l                  # the installed schedule
docker exec mom tail -f logs/gfms.log       # a job's output
docker exec mom ./run_mom_job.sh -j GFMS    # run one job by hand
```
Anything passed after the image name runs instead of cron, which is the way to do a one-off job or a `--fixdate` run in a throwaway container.

## 5. Storage requirements 
The minimum required free disk space for data processing is 20G. 

Daily processing jobs generate less than 3.0Gb data, includes both the downloaded data and products.  

Processing folder holds the downloaded data and intermediate outputs, all the contents under processing can be deleted periodically to save the disk space. The processed data is usually archived daily as a zip, such as gfms_20211202.zip in its corresponding folder. For DFO/VIIRS data, setting storage save flag to False in production.cfg deletes the downloaded data immediately after the processing, it saves a little more than 2.0Gb (DFO: 2Gb, VIIRS: around 200Mb). 
``` 
production.cfg:

[storage]
dfo_save: False 
viirs_save: False 
```
### 5.1 Free up disk space
If the disk space is low, use the following steps to free up disk space:
* Remove the zip files in sub-folders under Processing, the zip files contain the downloaded data that already been processed, it is safe to delete them periodically.
* If more space needed, under Products, all the tiffs images in _image subfolder can be removed, they are only for the archive purpose.  
* A good practice is to delete the older *.zip/*.tiff first, and keep at least the recent data up to two weeks. 

Disk space can be monitored with the optional Monitor Module. 
## 6. Folder structures 
Folder structures is defined in production.cfg, the default one is listed. Modify [general],[processing_dir], [products_dir] to change the locations. 
```
MoM
├── Processing
│   ├── dfo
│   ├── gfms
│   ├── glofas
│   ├── hwrf
│   ├── logs
│   └── viirs
└── Products
    ├── DFO
    │   ├── DFO_image
    │   ├── DFO_MoM
    │   └── DFO_summary
    ├── Final_Alert
    ├── GFMS
    │   ├── GFMS_image
    │   ├── GFMS_MoM
    │   └── GFMS_summary
    ├── GLOFAS
    ├── HWRF
    │   ├── HWRF_image
    │   ├── HWRF_MoM
    │   └── HWRF_summary
    └── VIIRS
        ├── VIIRS_image
        ├── VIIRS_MoM
        └── VIIRS_summary
```

## 7. Processing modules & data

```
MoM_run.py
settings.py
initialize.py
processing
├── utilities.py
├── watershed_cells.py
├── proj_env.py
├── publish
│   ├── publish_utils.py
│   ├── publish_alerts.py
│   └── publish_tiles.py
├── gfms
│   ├── GFMS_tool.py
│   └── GFMS_MoM.py
├── hwrf
│   ├── HWRF_tool.py
│   └── HWRF_MoM.py
├── hafs
│   └── HAFS_tool.py
├── dfo
│   ├── DFO_tool.py
│   └── DFO_MoM.py
└── viirs
    ├── VIIRS_tool.py
    └── VIIRS_MoM.py
```
Run the pipeline modules from the repository root, e.g. `python -m processing.hafs.HAFS_tool`
(running them by file path fails, because they import `settings` from the root and `processing` as a package).
The data required is in data folder:
```
data
├── Admin0_1_union_centroid.csv
├── Attributes.csv
├── DFO_Weightage.csv
├── GFMS_Weightage.csv
├── HWRF_Weightage.csv
├── Resilience_Index.csv
└── VIIRS_Weightage.csv
```

## 8. Profiling scripts

1. Start logging disk usage before running the script (separate shell, linux)
```
while true; do du -sb MoM >> disk_log_GFMS.txt; sleep 1; done
```
```
while true; do du -sb MoM >> disk_log_VIIRS.txt; sleep 1; done
```
```
while true; do du -sb MoM >> disk_log_DFO.txt; sleep 1; done
```
```
while true; do du -sb MoM >> disk_log_HWRF.txt; sleep 1; done
```

2. If parallel processing applied (e.g. in VIIRS), track live RAM usage (separate shell, linux). 
(Need to add 'print("Main PID:", os.getpid())' to the start on the script, if not there yet)
```
PID=YourPID
while true; do
    total_kb=$(ps --no-headers -o rss --ppid $PID | awk '{sum+=$1} END {print sum+0}')
    parent_kb=$(ps -o rss= -p $PID)
    echo $((total_kb + parent_kb)) >> ram_log_VIIRS.txt
    sleep 1
done
```

3. Total time, CPU, RAM, per-function profiling (run from the MoMProduction dir, with activated venv).
For Linux conda setup:
```
pip install py-spy
```
```
/usr/bin/time -v py-spy record -r 50 --subprocesses -o profile_GFMS.json --format speedscope -- python MoM_run.py -j GFMS 2> resources_GFMS.txt
```
```
/usr/bin/time -v py-spy record -r 50 --subprocesses -o profile_VIIRS.json --format speedscope -- python MoM_run.py -j VIIRS 2> resources_VIIRS.txt
```
```
/usr/bin/time -v py-spy record -r 50 --subprocesses -o profile_DFO.json --format speedscope -- python MoM_run.py -j DFO 2> resources_DFO.txt
```
```
/usr/bin/time -v py-spy record -r 50 --subprocesses -o profile_HWRF.json --format speedscope -- python MoM_run.py -j HWRF 2> resources_HWRF.txt
```

For Windows uv setup:
```
uv add py-spy
python MoM_run.py -j VIIRS
```
Run this from Admin Powershell (per-function profiling):
```
py-spy record 50 --subprocesses -o profile_VIIRS.json --format speedscope --pid <PID>
```
Launch this in PowerShell (get Timestamp, RAM, CPU) - does NOT include subprocesses:
```
typeperf "\Process(python)\Working Set" "\Process(python)\% Processor Time" -si 1 -o resources_VIIRS_win.txt
```

4. After it finished, find peak and minimum memory (during and before running the code). The difference is the temp storage needed. 
For Linux:
```
awk 'NR==1{min=$1; max=$1} {if($1<min) min=$1; if($1>max) max=$1} END{print (max-min)/1024/1024/1024 " GB"}' disk_log_VIIRS.txt
```
For RAM live tracking (if applicable) find maximum:
```
sort -n ram_log_VIIRS.txt | tail -1 | awk '{print $1/1024/1024 " Gb"}'
```

For Windows (Powershell), prints max RAM and CPU:
```
"{0} GB" -f [math]::Round(
    (Get-Content resources_VIIRS_win.txt |
     Select-Object -Skip 2 |
     ForEach-Object {
         $cols = $_ -replace '"' -split ','
         [double]$cols[1]
     } |
     Measure-Object -Maximum).Maximum / 1GB,
3)
```


___________________________________________________________________________

## New installation notes

**Linux** (Ubuntu-24.04):
Create setup.sh file at the root folder with
```
nano setup.sh
```
and paste the content of first_setup/setup.sh file from this repo. Ctrl+O (Save), Ctrl+C (Exit). Replace branch name to "main" for stable release. Run the script:
```
. first_setup/setup.sh
```
Create persistent env variables for this machine's User scope (can manually replace in 'production.cfg', but not recommended):
```
echo 'export AUTH_GLOFAS_USER=myvalue' >> ~/.bashrc
echo 'export AUTH_GLOFAS_PASSWD=myvalue' >> ~/.bashrc
echo 'export AUTH_DFO_TOKEN=myvalue' >> ~/.bashrc
```

**Windows** (tested on CI, but not on a new Windows machine):
Create setup.ps1 file at the root folder and paste the content of first_setup/setup.ps1 file from this repo. Replace branch name to "main" for stable release. Run from Admin Powershell:
```
Set-ExecutionPolicy Bypass -Scope Process -Force
```
```
. .\first_setup\setup.ps1
```
Create persistent env variables for this machine's User scope (can manually replace in 'production.cfg', but not recommended):
```
[System.Environment]::SetEnvironmentVariable("AUTH_GLOFAS_USER", "myvalue", "User")
[System.Environment]::SetEnvironmentVariable("AUTH_GLOFAS_PASSWD", "myvalue", "User")
[System.Environment]::SetEnvironmentVariable("AUTH_DFO_TOKEN", "myvalue", "User")
```