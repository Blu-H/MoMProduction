"""
proj_env.py
point PROJ at the right proj.db; import it before any PROJ-dependent module
(rasterio, osgeo, pyproj, geopandas):

    import processing.proj_env  # noqa: F401  (before rasterio etc.)
"""

import os
from pathlib import Path

# gdal.VectorTranslate needs GDAL's own bundled proj.db, not pyproj's copy
# (which setup.ps1's PROJ_LIB points to) — always override before importing PROJ-dependent modules. No-op on CI (conda sets its own).
_venv_site_packages = Path(__file__).resolve().parents[1] / ".venv" / "Lib" / "site-packages"
for _proj_dir in (
    _venv_site_packages / "osgeo" / "data" / "proj",  # GDAL's own copy
    _venv_site_packages / "pyproj" / "proj_dir" / "share" / "proj",  # pyproj's copy, fallback
):
    if _proj_dir.exists():
        os.environ["PROJ_LIB"] = str(_proj_dir)
        os.environ["PROJ_DATA"] = str(_proj_dir)
        break
