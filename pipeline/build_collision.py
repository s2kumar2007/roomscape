"""Phase 5: collision proxy. Top-down occupancy grid from aligned Gaussians (Y up, floor Y=0).

Cell values: 0 UNKNOWN, 1 FLOOR (walkable), 2 BLOCKED. Two grids are exported:
  grid      raw cleaned occupancy
  inflated  BLOCKED dilated by the agent radius (use this for walking / A*; walkable iff value == 1)
Index of a world point (x, z):  ix = floor((x-origin_x)/cell),  iz = floor((z-origin_z)/cell),  idx = iz*nx + ix.
Grids are run-length encoded row-major: [[value, run_length], ...].
"""
from __future__ import annotations
import json
from pathlib import Path
import cv2
import numpy as np
from gsplat_io import read_gs_ply, sigmoid
from utils import PipelineError, get_logger

log = get_logger()
UNKNOWN, FLOOR, BLOCKED = 0, 1, 2

def rle_encode(a: np.ndarray) -> list[list[int]]:
    f = a.ravel()
    idx = np.flatnonzero(np.diff(f)) + 1
    starts = np.r_[0, idx]; lens = np.diff(np.r_[starts, len(f)])
    return [[int(f[s]), int(l)] for s, l in zip(starts, lens)]

def rle_decode(runs: list[list[int]], shape: tuple[int, int]) -> np.ndarray:
    return np.concatenate([np.full(l, v, np.uint8) for v, l in runs]).reshape(shape)

def remove_floaters(xyz: np.ndarray, voxel: float, min_pts: int) -> np.ndarray:
    key = np.floor(xyz / voxel).astype(np.int64)
    _, inv, cnt = np.unique(key, axis=0, return_inverse=True, return_counts=True)
    return cnt[inv.ravel()] >= min_pts

def build_grid(xyz: np.ndarray, c: dict) -> dict:
    cell = c["cell_size_m"]
    lo = np.percentile(xyz, 0.5, 0); hi = np.percentile(xyz, 99.5, 0)
    xyz = xyz[np.all((xyz >= lo) & (xyz <= hi), 1)]
    ox, oz = float(lo[0]), float(lo[2])
    nx, nz = int(np.ceil((hi[0] - ox) / cell)) + 1, int(np.ceil((hi[2] - oz) / cell)) + 1
    ix = np.clip(((xyz[:, 0] - ox) / cell).astype(int), 0, nx - 1); iz = np.clip(((xyz[:, 2] - oz) / cell).astype(int), 0, nz - 1)
    flat = iz * nx + ix; y = xyz[:, 1]
    band = (y >= c["blocked_min_h"]) & (y <= c["blocked_max_h"])
    fl = y < c["blocked_min_h"]
    cb = np.bincount(flat[band], minlength=nx * nz).reshape(nz, nx)
    cf = np.bincount(flat[fl], minlength=nx * nz).reshape(nz, nx)
    blocked = (cb >= c["blocked_min_points"]).astype(np.uint8)
    # despeckle: drop tiny connected components, then close 1-cell gaps in walls
    n, lab, st, _ = cv2.connectedComponentsWithStats(blocked, connectivity=8)
    for i in range(1, n):
        if st[i, cv2.CC_STAT_AREA] < c["min_blocked_component_cells"]: blocked[lab == i] = 0
    k3 = np.ones((3, 3), np.uint8)
    blocked = cv2.morphologyEx(blocked, cv2.MORPH_CLOSE, k3)
    floor = (cf >= c["floor_min_points"]).astype(np.uint8)
    floor = cv2.morphologyEx(floor, cv2.MORPH_CLOSE, k3)          # fill pinholes in the floor
    grid = np.full((nz, nx), UNKNOWN, np.uint8)
    grid[floor > 0] = FLOOR
    grid[blocked > 0] = BLOCKED
    r = max(1, int(np.ceil(c["agent_radius_m"] / cell)))
    disk = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))
    infl = grid.copy(); infl[cv2.dilate(blocked, disk) > 0] = BLOCKED
    return {"grid": grid, "inflated": infl, "origin": [ox, oz], "cell": cell, "size": [nx, nz], "lo": lo, "hi": hi, "inflate_cells": r}

def export_json(g: dict, c: dict, path: Path) -> dict:
    doc = {"version": 1, "origin": g["origin"], "cell_size": g["cell"], "size": g["size"],
           "axes": {"x": "world X -> columns", "z": "world Z -> rows"}, "values": {"unknown": 0, "floor": 1, "blocked": 2},
           "encoding": "rle_row_major", "grid": rle_encode(g["grid"]), "inflated": rle_encode(g["inflated"]),
           "agent_radius_m": c["agent_radius_m"], "floor_height": 0.0,
           "bounds": {"min": [round(float(v), 3) for v in g["lo"]], "max": [round(float(v), 3) for v in g["hi"]]},
           "blocked_band_m": [c["blocked_min_h"], c["blocked_max_h"]]}
    path.write_text(json.dumps(doc, separators=(",", ":")))
    return doc

def draw_occupancy(g: dict, cams: np.ndarray | None, path: Path) -> None:
    nz, nx = g["grid"].shape
    s = max(1, min(8, 1000 // max(nx, nz)))
    pal = np.array([[60, 60, 60], [225, 225, 225], [40, 40, 200]], np.uint8)
    img = pal[g["grid"]]
    near = (g["inflated"] == BLOCKED) & (g["grid"] != BLOCKED); img[near] = [120, 120, 235]
    img = cv2.resize(img, (nx * s, nz * s), interpolation=cv2.INTER_NEAREST)
    if cams is not None and len(cams) > 1:
        pts = np.c_[(cams[:, 0] - g["origin"][0]) / g["cell"] * s, (cams[:, 2] - g["origin"][1]) / g["cell"] * s].astype(np.int32)
        cv2.polylines(img, [pts.reshape(-1, 1, 2)], False, (0, 200, 0), max(1, s // 2))
        cv2.circle(img, tuple(int(v) for v in pts[0]), 3 * s, (255, 120, 0), -1)
    cv2.imwrite(str(path), img)

def build(cfg: dict, out: Path) -> dict:
    c = cfg["collision"]
    d = read_gs_ply(out / "aligned.ply")
    xyz = d["xyz"][sigmoid(d["opacity"]) >= c["min_opacity"]]
    if len(xyz) < 1000: raise PipelineError("Too few opaque Gaussians for a collision map.", "Lower collision.min_opacity or check the reconstruction.")
    xyz = xyz[remove_floaters(xyz, c["outlier_voxel_m"], c["min_voxel_points"])]
    g = build_grid(xyz, c)
    doc = export_json(g, c, out / "collision.json")
    cams = None
    cj = out / "cameras_aligned.json"
    if cj.exists(): cams = np.array(json.loads(cj.read_text())["positions"])
    draw_occupancy(g, cams, out / "occupancy.png")
    walk = int((g["inflated"] == FLOOR).sum()); area = walk * c["cell_size_m"] ** 2
    log.info("Collision grid %dx%d @ %.2fm: %d walkable cells (~%.1f m2 after inflation)", *g["size"], c["cell_size_m"], walk, area)
    if walk == 0: raise PipelineError("No walkable cells after inflation.", "Reduce collision.agent_radius_m or check floor alignment (out/debug/floor_alignment.png).")
    return {"size": g["size"], "walkable_cells": walk, "walkable_area_m2": round(area, 1), "json_kb": round((out / "collision.json").stat().st_size / 1024, 1)}

def run(cfg: dict, out: Path, inputs: list[Path]) -> dict:
    """Stage entry point."""
    return build(cfg, out)
