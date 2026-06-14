#!/usr/bin/env python3
"""
convert_to_cog_utils.py
======================
Converts GeoTIFF images from the downloads_img folder tree into Cloud-Optimized
GeoTIFF (COG) format using rasterio/GDAL.

Source layout:
    <SOURCE>/<SOURCE>_image/*.tiff

Output layout:
    <SOURCE>/*.tiff   (COG, tiled, overviews, DEFLATE)

Usage:
    python convert_to_cog_utils.py
    python convert_to_cog_utils.py --folder GFMS
    python convert_to_cog_utils.py --force   # reprocess existing
    python convert_to_cog_utils.py -q max    # larger file, faster online loading
"""

import argparse
import os
import sys
import tempfile
import time
from pathlib import Path
import rasterio
from rasterio.crs import CRS
from rasterio.enums import Resampling
from rasterio.shutil import copy as rio_copy

import settings

# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------

# Raw image downloads — mirrors download_mom_img.py
SRC_FOLDER = settings.PRODUCT_DIR

TOP_FOLDERS = ["DFO", "Final_Alert", "GFMS", "HWRF", "VIIRS"]

# CRS to assign when the source file lacks one (EPSG code or None to leave as-is)
FOLDER_CRS = {
    "GFMS": 4326,
}

# Quality presets:
# "nano" — absolute minimum file size: no overviews, ZSTD max compression, 2048-px tiles (lossless)
# "min"  — small file, some overviews for zoom-out speed
# "max"  — fastest tile loading, largest file
QUALITY_PRESETS = {
    "nano": {
        "block_size": 2048,
        "overview_levels": [],
        "compress": "zstd",
        "zlevel": 22,
    },
    "min": {
        "block_size": 1024,
        "overview_levels": [4, 16],
        "compress": "deflate",
        "zlevel": 9,
    },
    "max": {
        "block_size": 256,
        "overview_levels": [2, 4, 8, 16, 32],
        "compress": "deflate",
        "zlevel": 6,
    },
}

# ---------------------------------------------------------------------------
# COG conversion
# ---------------------------------------------------------------------------


def convert_to_cog(
    src_path: Path, dst_path: Path = None, crs=None, quality: str = "min"
) -> None:
    """Convert a GeoTIFF at *src_path* to a COG written at *dst_path*.

    Strategy:
      1. Read the source into a temporary GeoTIFF with internal tiling.
      2. Build overviews on the temporary file.
      3. Use rasterio.shutil.copy with copy_src_overviews=True to produce the
         final COG where overviews precede the image data — the defining
         property of the cloud-optimised layout.
    """

    if not os.path.exists(src_path):
        print(
            f"  [FAIL] source .tiff file not found: {src_path}, COG could not be generated",
            flush=True,
        )
        sys.exit(1)

    t0 = time.monotonic()

    if not dst_path:
        cog_root = settings.COG_DIR
        folder_name = src_path.parent.parent.name
        dst_path = cog_root / folder_name / src_path.name

    preset = QUALITY_PRESETS[quality]
    block_size = preset["block_size"]
    overview_levels = preset["overview_levels"]
    compress = preset["compress"]
    zlevel = preset["zlevel"]

    dst_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile(suffix=".tif", delete=False) as _tmp:
        tmp_path = Path(_tmp.name)

    try:
        # --- Step 1: write a tiled intermediate copy (windowed to avoid OOM) ---
        with rasterio.open(src_path) as src:
            profile = src.profile.copy()
            profile.update(
                driver="GTiff",
                tiled=True,
                blockxsize=block_size,
                blockysize=block_size,
                compress=compress,
                predictor=2,  # horizontal differencing — improves ratio
                zlevel=zlevel,
                interleave="band",
            )
            if crs is not None:
                profile["crs"] = CRS.from_epsg(crs)

            with rasterio.open(tmp_path, "w", **profile) as tmp:
                for _, window in src.block_windows(1):
                    tmp.write(src.read(window=window), window=window)

        # --- Step 2: build overviews on the intermediate file ---
        with rasterio.open(tmp_path, "r+") as tmp:
            tmp.build_overviews(overview_levels, Resampling.average)
            tmp.update_tags(ns="rio_overview", resampling="average")

        # --- Step 3: copy into true COG layout (overviews before image data) ---
        cog_profile = profile.copy()
        cog_profile.update(copy_src_overviews=True)
        rio_copy(tmp_path, dst_path, **cog_profile)

    finally:
        tmp_path.unlink(missing_ok=True)

    elapsed = time.monotonic() - t0
    print(f"  [COG ] {src_path.name}  ({elapsed:.1f}s)", flush=True)


def _iter_tiffs(root: Path):
    """Yield all .tiff / .tif files under *root*, sorted for reproducibility."""
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix.lower() in (".tiff", ".tif"):
            yield path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert downloaded GeoTIFFs to Cloud-Optimized GeoTIFF (COG)."
    )
    parser.add_argument(
        "--folder",
        choices=TOP_FOLDERS,
        default=None,
        metavar="FOLDER",
        help="Process only one top-level folder (default: all).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-process images that already exist in the COG output folder.",
    )
    parser.add_argument(
        "-q",
        "--quality",
        choices=["nano", "min", "max"],
        default="min",
        help=(
            "Output quality preset. "
            "'nano' (default): smallest file, no overviews, larger tiles, max compression. "
            "'min': smaller file, fewer overviews, large tiles, max compression. "
            "'max': faster tile loading, more overviews, smaller tiles, standard compression."
        ),
    )
    args = parser.parse_args()

    # Force line-buffering so every print() flushes immediately when stdout is
    # redirected to a file (e.g. nohup). Without this, output accumulates in an
    # 8 KB buffer and only appears at program exit.
    sys.stdout.reconfigure(line_buffering=True)

    cog_root = settings.COG_DIR
    print(f"Quality: {args.quality}", flush=True)
    print(f"Source : {SRC_FOLDER}", flush=True)
    print(f"Output : {cog_root}", flush=True)

    folders = [args.folder] if args.folder else TOP_FOLDERS
    total = skipped = errors = 0

    for folder_name in folders:
        src_folder = SRC_FOLDER / folder_name
        if not src_folder.exists():
            print(f"\n[{folder_name}] not found in source, skipping.", flush=True)
            continue

        tiffs = list(_iter_tiffs(src_folder))
        if not tiffs:
            print(f"\n[{folder_name}] no .tiff files found.", flush=True)
            continue

        print(
            f"\n{'='*60}\n[{folder_name}]  {len(tiffs)} image(s) found\n{'='*60}",
            flush=True,
        )

        for src_path in tiffs:
            rel = src_path.relative_to(SRC_FOLDER)
            dst_path = cog_root / folder_name / src_path.name

            if dst_path.exists() and not args.force:
                skipped += 1
                continue

            try:
                convert_to_cog(
                    src_path,
                    dst_path,
                    crs=FOLDER_CRS.get(folder_name),
                    quality=args.quality,
                )
                total += 1
            except Exception as exc:
                print(f"  [FAIL] {rel}: {exc}", flush=True, file=sys.stderr)
                errors += 1

    print(f"\nDone.  converted={total}  skipped={skipped}  errors={errors}", flush=True)
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
