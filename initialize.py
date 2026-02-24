"""
Inititlize the setup
    -- create the folder structures defined in production.cfg
    -- check username/password, token in production.cfg
    -- unzip watershed.shp
"""

import os
import shutil
import sys
import time
import settings
from zipfile import ZipFile

# firt check production.cfg
if not os.path.exists("production.cfg"):
    shutil.copyfile("sample_production.cfg", "production.cfg")
    time.sleep(2)
    # print("please check the production.cfg, run initilize again.")
    # sys.exit()


def create_dir(apath):
    """create dir with a path"""
    if not os.path.exists(apath):
        print("create " + apath)
        os.makedirs(apath, exist_ok=True)


print("task: check folder stucture")

# create working dir
create_dir(settings.WORKING_DIR)
# task: create the sub folders inside working_dir
for key in settings.config["processing_dir"]:
    subfolder = os.path.join(settings.WORKING_DIR, settings.config.get("processing_dir", key))
    create_dir(subfolder)

# create product dir
create_dir(settings.PRODUCT_DIR)
# task: create the sub folders inside product_dir
product_sub_folders = ["summary", "image", "MoM"]
product_with_subfolder = ["GFMS", "HWRF", "DFO", "VIIRS"]
for key in settings.config["products_dir"]:
    subfolder = os.path.join(settings.PRODUCT_DIR, settings.config.get("products_dir", key))
    create_dir(subfolder)
    if key.upper() in product_with_subfolder:
        for product_sub in product_sub_folders:
            create_dir(os.path.join(subfolder, key.upper() + "_" + product_sub))

# task: check ftp user/password, key
user = settings.config.get("glofas", "USER")
passwd = settings.config.get("glofas", "PASSWD")

dfo_token = settings.config.get("dfo", "TOKEN")

# task: check if shp file is unzipped
if not os.path.exists(settings.WATERSHED_SHP):
    print("Task: unzip watershed.shp.zip")
    with ZipFile(settings.WATERSHED_SHP + ".zip", "r") as zipObj:
        zipObj.extractall(settings.WATERSHED_DIR)
else:
    print("Task: watershed shp is already unzipped")

# check for credentials
if "?" in user or "?" in passwd:
    print("Action required: production.cfg")
    print("Please fill in USER/PASSED in glofas section")
    sys.exit()

if "?" in dfo_token:
    print("Action required: production.cfg")
    print("Please fill in TOKEN in dfo section")
    sys.exit()

print("System initilization is completed!")
