"""
Push the tiles of the new final alert csv files (the ones publish_alerts
pushes) to a GitHub repo through the GitHub API, without a local clone.

Every local csv whose cycle sorts after the last tile existing on remote,
is made into a tile (watersheds de-duplicated by pfaf_id) and pushed all in
one commit. With no tile in the repo folder yet, only the newest local csv is
used. The same commit removes the tiles older than the newest MAX_TILES and
rewrites metadata.json in the folder: one snapshot per tile left, newest
first, built from the metadata.json of the same remote commit (kept entries)
plus the new tiles.

Needs GITHUB_REPO and GITHUB_ALERTS_TOKEN (see publish_utils).

"""

import argparse
import base64
import json
import logging
import os
import sys
import tempfile
from datetime import datetime, timezone

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from osgeo import gdal

import settings
from processing.publish.publish_utils import (
    API,
    REPO,
    RETRIES,
    alert_cycle,
    blob_entry,
    commit,
    commit_message,
    github_session,
    local_alerts,
    remote_state,
)

FOLDER = "Alerts/tiles"
METADATA = "metadata.json"
# tiles kept in the repo folder: the newest timestamps
MAX_TILES = 100
# final alert columns kept in the tiles
COLUMNS = [
    "pfaf_id",
    "name",
    "Admin1_names",
    "Alert",
    "Status",
    "Severity",
    "Hazard_Score",
    "area_km2",
    "rfr_score",
    "cfr_score",
]
# columns whose values of a watershed's rows are joined with "; "
JOINED = ["name", "Admin1_names"]


def tile_name(csv_name):
    return f"watersheds_{alert_cycle(csv_name)}.pmtiles"


def new_alerts(remote_names, local):
    """local csv files later than the newest tile in the repo"""
    if not remote_names:
        return local[-1:]
    last = max(remote_names)
    return [f for f in local if tile_name(os.path.basename(f)) > last]


def make_tile(csv, tmpdir):
    """tile of one final alert csv, watersheds de-duplicated by pfaf_id (the
    JOINED values joined with "; "), only the COLUMNS kept"""
    # the final alert csv files are Windows-1252
    df = pd.read_csv(csv, encoding="cp1252", encoding_errors="replace", low_memory=False)
    joined = df.groupby("pfaf_id")[JOINED].agg(
        lambda v: "; ".join(dict.fromkeys(v.dropna().astype(str)))
    )
    df = df.drop_duplicates("pfaf_id")[COLUMNS]
    for c in JOINED:
        df[c] = df["pfaf_id"].map(joined[c])
    gdf = gpd.read_file(settings.WATERSHED_SHP)
    gdf["pfaf_id"] = pd.to_numeric(gdf["pfaf_id"], errors="coerce")
    # columns in both (area_km2, rfr_score, cfr_score): the csv values win,
    # else the merge would keep both as _x / _y
    gdf = gdf.drop(
        columns=[c for c in gdf.columns if c in df.columns and c != "pfaf_id"]
    )
    merged = gdf.merge(df, on="pfaf_id", how="left")
    # a few watersheds (353011, 353013, 552000) have vertices a hair past
    # 180 degrees longitude, and GDAL then drops or trims them in the tiles:
    # clamp to the world bounds, then fix any invalid geometries
    clamped = shapely.transform(
        np.asarray(merged.geometry.values),
        lambda xy: np.clip(xy, [-180.0, -90.0], [180.0, 90.0]),
    )
    merged.geometry = gpd.GeoSeries(clamped, index=merged.index, crs=merged.crs).buffer(0)
    geojson = os.path.join(tmpdir, "watersheds.geojson")
    merged.to_file(geojson, driver="GeoJSON")
    tile = os.path.join(tmpdir, tile_name(os.path.basename(csv)))
    options = gdal.VectorTranslateOptions(
        format="PMTiles",
        layerName="watersheds",
        datasetCreationOptions=[
            "MINZOOM=2",
            "MAXZOOM=6",
            "SIMPLIFICATION=10",
            "SIMPLIFICATION_MAX_ZOOM=2",
        ],
    )
    if gdal.VectorTranslate(tile, geojson, options=options) is None:
        raise RuntimeError(f"gdal.VectorTranslate failed: {csv}")
    os.remove(geojson)
    return tile


def old_tiles(remote_names, files):
    """remote tiles older than the newest MAX_TILES, with the new ones counted"""
    names = sorted(set(remote_names) | {tile_name(os.path.basename(f)) for f in files})
    return [n for n in names[:-MAX_TILES] if n in remote_names]


def snapshot(csv, generated):
    """metadata.json entry of the tile of a final alert csv"""
    c = alert_cycle(os.path.basename(csv))
    return {
        "updated_at": f"{c[:4]}-{c[4:6]}-{c[6:8]} {c[8:]}:00 UTC",
        "csv": os.path.basename(csv),
        "file": tile_name(os.path.basename(csv)),
        "generated": generated,
    }


def remote_snapshots(session, head):
    """the snapshots in metadata.json at the head commit, [] if there is none"""
    r = session.get(
        f"{API}/repos/{REPO}/contents/{FOLDER}/{METADATA}",
        params={"ref": head},
        timeout=60,
    )
    if r.status_code == 404:
        return []
    r.raise_for_status()
    return json.loads(base64.b64decode(r.json()["content"])).get("snapshots", [])


def metadata(session, head, remote_names, files, removed, local):
    """metadata.json after the commit: a snapshot per tile left, newest first"""
    left = (set(remote_names) - set(removed)) | {
        tile_name(os.path.basename(f)) for f in files
    }
    snaps = {
        s["file"]: s for s in remote_snapshots(session, head) if s.get("file") in left
    }
    now = datetime.now(timezone.utc).isoformat()
    for f in files:
        snaps[tile_name(os.path.basename(f))] = snapshot(f, now)
    # a remote tile with no snapshot yet: from its local csv, build time unknown
    for f in local:
        name = tile_name(os.path.basename(f))
        if name in left and name not in snaps:
            snaps[name] = snapshot(f, None)
    ordered = sorted(snaps.values(), key=lambda s: s["file"], reverse=True)
    for i, snap in enumerate(ordered):
        snap["index"] = i
    return {"snapshots": ordered}


def commit_files(session, head, tree, remote_names, files, removed, local, tmpdir):
    """one commit adding the tiles of files to the repo folder, removing the
    removed ones and rewriting metadata.json; False if the branch moved"""
    entries = [
        blob_entry(
            session, f"{FOLDER}/{tile_name(os.path.basename(f))}", make_tile(f, tmpdir)
        )
        for f in files
    ]
    meta = os.path.join(tmpdir, METADATA)
    with open(meta, "w") as fh:
        json.dump(
            metadata(session, head, remote_names, files, removed, local), fh, indent=2
        )
    entries.append(blob_entry(session, f"{FOLDER}/{METADATA}", meta))
    entries += [
        {"path": f"{FOLDER}/{n}", "mode": "100644", "type": "blob", "sha": None}
        for n in removed
    ]
    return commit(session, head, tree, entries, commit_message("tiles", files))


def publish_tiles(alerts_dir, dry_run=False):
    """push the tiles of the final alerts newer than the newest tile in the repo"""
    local = local_alerts(alerts_dir)
    session = github_session("publish tiles", dry_run)
    if session is None:
        return

    for _ in range(RETRIES):
        head, tree, remote_names = remote_state(
            session, FOLDER, ".pmtiles", "publish tiles"
        )
        # older ones would be removed again right away
        files = new_alerts(remote_names, local)[-MAX_TILES:]
        if not files:
            logging.info(f"publish tiles: {REPO}/{FOLDER} is up to date")
            return
        removed = old_tiles(remote_names, files)
        if dry_run:
            logging.info(
                f"publish tiles (dry run): newest in repo: {max(remote_names, default='none')}"
            )
            for f in files:
                logging.info(
                    f"publish tiles (dry run): would push {tile_name(os.path.basename(f))}"
                )
            for n in removed:
                logging.info(f"publish tiles (dry run): would remove {n}")
            snaps = metadata(session, head, remote_names, files, removed, local)[
                "snapshots"
            ]
            logging.info(
                f"publish tiles (dry run): would write {METADATA} with {len(snaps)} snapshot(s)"
            )
            return
        with tempfile.TemporaryDirectory() as tmpdir:
            pushed = commit_files(
                session, head, tree, remote_names, files, removed, local, tmpdir
            )
        if pushed:
            logging.info(
                f"publish tiles: pushed {len(files)} tile(s) to {REPO}/{FOLDER}, "
                f"last {tile_name(os.path.basename(files[-1]))}, removed {len(removed)}"
            )
            return
        logging.info("publish tiles: branch moved during the push, retrying")
    logging.warning(f"publish tiles: gave up after {RETRIES} attempts")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="push tiles of new final alerts to GitHub"
    )
    parser.add_argument("alerts_dir", help="the final alerts folder to publish")
    parser.add_argument(
        "--dry-run", action="store_true", help="only list what would be pushed"
    )
    # stdout: run_mom_job.sh's cron entry appends it to the job's cron log
    logging.basicConfig(
        stream=sys.stdout, level=logging.INFO, format=settings.LOG_FORMAT, force=True
    )
    args = parser.parse_args()
    publish_tiles(args.alerts_dir, args.dry_run)
