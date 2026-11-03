"""
watershed_cells.py
    -- per-watershed summaries of the GFMS, VIIRS, DFO and HWRF / HAFS rasters
       from a precomputed lookup of the grid cells each watershed covers

    Masking: every cell a watershed overlaps counts with the exact share of
    the cell inside it (1 for inner cells). Inner cells are found by their
    centres, the cells along the boundary (and one cell around it) get their
    share from the polygon intersection.

    Lookup: the cells of every watershed are saved as row runs, cells
    [c0, c1) of one grid row: runs of inner cells (share 1) and runs of
    boundary cells with a share per cell. One file per source,
    data/watershed_runs_<source>.npz, rebuilt when the watershed shapefile,
    the grid or MASK_METHOD changes; when it cannot be saved it is built in
    memory for the run. The file is generated, not kept in git.

    Cell area: the grids are latitude/longitude, so a cell's area is
    111.111^2 * cos(lat at the cell centre) * dlon * dlat (degrees, 111.111 km
    per degree), times its share.

    Grids: GFMS and VIIRS files are on one grid per source, the file's own.
    HWRF / HAFS images and DFO mosaics cover a different extent each time, so
    they are windows of one global grid of their cell size (global_grid),
    and one lookup serves them all.

    Reading: a raster is read in strips of rows, sized from the grid width so
    a strip stays under STRIP_BYTES, and summed per run with cumulative sums
    along each row. Rasters must be on a latitude/longitude grid.

    Per source only the grid and which cells count differ (SOURCES); every
    summary gives, per watershed, the area of the counted cells, its percent
    of the watershed, the area-weighted mean and the max of their values.

**EXAMPLE** (from the repository root)
    python -m processing.watershed_cells gfms <a GFMS .vrt>    # build a lookup by hand
    python -m processing.watershed_cells viirs <a VIIRS .tiff>
    python -m processing.watershed_cells dfo <a DFO mosaic .vrt>
    python -m processing.watershed_cells hwrf
"""

import logging
import math
import time

import numpy as np
import pandas as pd
import rasterio
import rasterio.features
import shapely
import shapely.affinity
from rasterio import Affine
from rasterio.transform import from_origin
from rasterio.windows import Window

from processing.utilities import watersheds_gdb_reader

# km per degree of latitude (and of longitude at the equator)
KM_PER_DEGREE = 111.111
# decimals kept of a boundary cell's share of a cell
SHARE_DECIMALS = 4
# cell size of the HWRF and HAFS rain images
HWRF_RES = 0.05



def viirs_flood(values):
    """VIIRS flood classes (141-200)"""
    return (values > 140) & (values < 201)


def dfo_flood(values):
    """DFO (MODIS MCDWD) flood class"""
    return values == 3


# per source: which cells count (values are NaN where the raster has no
# data), and whether the grid wraps around the globe in longitude
SOURCES = {
    "gfms": {"counts": np.isfinite, "wrap": False},
    "viirs": {"counts": viirs_flood, "wrap": False},
    "hwrf": {"counts": np.isfinite, "wrap": True},  # HWRF and HAFS
    "dfo": {"counts": dfo_flood, "wrap": False},
}



def row_cell_area_km2(transform, rows):
    """area of one cell in each of the given grid rows (km2)"""
    centre = np.clip(transform.f + (np.asarray(rows, np.float64) + 0.5) * transform.e, -90, 90)
    return KM_PER_DEGREE**2 * np.cos(np.radians(centre)) * abs(transform.a * transform.e)


def _dilate(mask):
    """mask grown by one cell, also diagonally"""
    grown = mask.copy()
    grown[1:] |= mask[:-1]
    grown[:-1] |= mask[1:]
    wide = grown.copy()
    wide[:, 1:] |= grown[:, :-1]
    wide[:, :-1] |= grown[:, 1:]
    return wide


def mask_summary(source, reader, transform, width, height, watersheds, wrap=False, value_above=-np.inf):
    """per watershed: area (km2) and perc_area of the cells that count, the
    area-weighted mean and the max of their values -- by masking each
    watershed's own window, as the pipeline did before the cell lookup.

    Cells whose centre is inside count whole; a cell on the boundary counts
    with the exact share of it inside the watershed. The shares are computed
    only for boundary cells that actually count, so the cost follows the data
    (sparse for DFO and VIIRS flood classes) instead of the basin perimeter.

    reader(row0, col0, n_rows, n_cols) gives that window of the grid as
    float64, NaN where there is no data.
    """
    counts = SOURCES[source]["counts"]
    ids = watersheds.index.tolist()
    n = len(ids)
    area, weighted, vmax = np.zeros(n), np.zeros(n), np.full(n, -np.inf)
    area_filtered_km2 = np.zeros(n)
    cell_deg2 = abs(transform.a * transform.e)
    t0 = time.monotonic()

    for i, geometry in enumerate(watersheds.geometry):
        if geometry is None or geometry.is_empty:
            continue
        if not geometry.is_valid:
            geometry = shapely.make_valid(geometry)
        pieces = [geometry]
        if wrap:
            pieces += [shapely.affinity.translate(geometry, xoff=x) for x in (-360, 360)]
        for piece in pieces:
            minx, miny, maxx, maxy = piece.bounds
            col0 = max(int(math.floor((minx - transform.c) / transform.a)), 0)
            col1 = min(int(math.ceil((maxx - transform.c) / transform.a)), width)
            row0 = max(int(math.floor((maxy - transform.f) / transform.e)), 0)
            row1 = min(int(math.ceil((miny - transform.f) / transform.e)), height)
            if col0 >= col1 or row0 >= row1:
                continue
            values = reader(row0, col0, row1 - row0, col1 - col0)
            counted = counts(values)
            if not counted.any():
                continue

            shape = values.shape
            window_transform = transform * Affine.translation(col0, row0)
            centre = rasterio.features.geometry_mask(
                [piece], shape, window_transform, invert=True
            )
            # one cell more around the boundary: no partly covered cell is
            # missed where the boundary runs along cell edges
            boundary = _dilate(
                rasterio.features.geometry_mask(
                    [piece.boundary], shape, window_transform, invert=True, all_touched=True
                )
            )
            km2 = row_cell_area_km2(transform, np.arange(row0, row0 + shape[0]))

            whole = (centre & ~boundary) & counted
            if whole.any():
                r, c = np.nonzero(whole)
                a = km2[r]
                v = values[r, c]
                area[i] += a.sum()
                area_filtered_km2[i] += a[v > value_above].sum()
                weighted[i] += (v * a).sum()
                vmax[i] = max(vmax[i], v.max())

            edge = boundary & counted
            if edge.any():
                r, c = np.nonzero(edge)
                left = transform.c + (c + col0) * transform.a
                top = transform.f + (r + row0) * transform.e
                boxes = shapely.box(left, top + transform.e, left + transform.a, top)
                # 0.0001 steps: a share is a fraction of one cell, so four
                # decimals are past anything the raster resolves, and rounding
                # keeps the result stable across shapely/GEOS versions
                share = np.round(
                    np.clip(
                        shapely.area(shapely.intersection(boxes, piece)) / cell_deg2,
                        0.0,
                        1.0,
                    ),
                    SHARE_DECIMALS,
                )
                a = share * km2[r]
                v = values[r, c]
                area[i] += a.sum()
                area_filtered_km2[i] += a[v > value_above].sum()
                weighted[i] += (v * a).sum()
                if (share > 0).any():
                    vmax[i] = max(vmax[i], v[share > 0].max())

        if (i + 1) % 4000 == 0:
            logging.info(f"{source} masking: {i + 1} of {n} watersheds, {time.monotonic() - t0:.0f}s")

    has = area > 0
    return pd.DataFrame(
        {
            "area": area_filtered_km2,
            "perc_area": area_filtered_km2 / watersheds["area_km2"].to_numpy() * 100,
            "mean": np.where(has, weighted / np.where(has, area, 1), np.nan),
            "max": np.where(has, vmax, np.nan),
            "has_data": has,
        },
        index=pd.Index(ids, name="pfaf_id"),
    )


def raster_summary(source, path, watersheds, value_above=-np.inf):
    """summarize a raster file by masking each watershed's own window"""
    with rasterio.open(path) as src:
        if src.crs is not None and not src.crs.is_geographic:
            # the cell areas assume a latitude/longitude grid
            raise ValueError(f"{path} is not on a latitude/longitude grid: {src.crs}")
        width, height, transform, nodata = src.width, src.height, src.transform, src.nodata

        def reader(row0, col0, n_rows, n_cols):
            values = src.read(1, window=Window(col0, row0, n_cols, n_rows)).astype(np.float64)
            if nodata is not None:
                values[values == nodata] = np.nan
            return values

        return mask_summary(
            source, reader, transform, width, height, watersheds,
            wrap=SOURCES[source]["wrap"], value_above=value_above,
        )


def lattice_summary(grid, top, left, watersheds, res=HWRF_RES, value_above=-np.inf):
    """summarize an HAFS rain grid in memory (NaN where there is no rain)
    whose top-left pixel centre is (left, top)"""
    transform = from_origin(left - res / 2, top + res / 2, res, res)
    height, width = grid.shape

    def reader(row0, col0, n_rows, n_cols):
        return np.asarray(grid[row0 : row0 + n_rows, col0 : col0 + n_cols], np.float64)

    return mask_summary(
        "hwrf", reader, transform, width, height, watersheds, wrap=False, value_above=value_above
    )
