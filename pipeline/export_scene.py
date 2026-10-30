"""Phase 6: prune, crop, reduce SH, write a Spark-loadable scene + meta.json into viewer/public/scene/.

Formats (Spark docs: .ply, .spz, .sog, .splat, .ksplat are supported; .splat is detected by file extension):
  splat  antimatter15 .splat, 32 bytes/Gaussian (pos f32x3, scale f32x3, rgba u8x4, rot u8x4); no SH. DEFAULT / safe fallback.
  ply    standard Gaussian PLY, pruned, SH degree <= export.sh_degree (<=1), float32.
SPZ / SOG would shrink further but need external encoders; not implemented (see roadmap in docs).
"""
from __future__ import annotations
import argparse, json, shutil, sys, time
from pathlib import Path
import numpy as np
from gsplat_io import SH_C0, read_gs_ply, sigmoid, write_gs_ply
from utils import PipelineError, get_logger, load_config

log = get_logger()
FORMATS = ("splat", "ply")

def write_splat(path: Path, d: dict) -> None:
    n = len(d["xyz"])
    imp = sigmoid(d["opacity"]) * np.exp(d["scale"]).prod(1)          # sort big/opaque first (helps progressive display)
    o = np.argsort(-imp)
    rgb = np.clip((0.5 + SH_C0 * d["dc"][o]) * 255, 0, 255).round().astype(np.uint8)
    a = np.clip(sigmoid(d["opacity"][o]) * 255, 0, 255).round().astype(np.uint8)
    q = np.clip(d["rot"][o] * 128 + 128, 0, 255).round().astype(np.uint8)
    rec = np.zeros(n, dtype=[("p", "<f4", 3), ("s", "<f4", 3), ("c", "u1", 4), ("r", "u1", 4)])
    rec["p"], rec["s"] = d["xyz"][o], np.exp(d["scale"][o])
    rec["c"] = np.c_[rgb, a]; rec["r"] = q
    path.write_bytes(rec.tobytes())

def read_splat(path: Path) -> dict:
    rec = np.frombuffer(path.read_bytes(), dtype=[("p", "<f4", 3), ("s", "<f4", 3), ("c", "u1", 4), ("r", "u1", 4)])
    return {"xyz": rec["p"].astype(np.float64), "scale": rec["s"].astype(np.float64), "rgba": rec["c"].copy(), "rot": (rec["r"].astype(np.float64) - 128) / 128}

def subset(d: dict, m: np.ndarray) -> dict:
    return {k: v[m] for k, v in d.items()}

def prune(d: dict, e: dict, lo: np.ndarray, hi: np.ndarray) -> dict:
    ok = np.isfinite(d["xyz"]).all(1) & np.isfinite(d["scale"]).all(1) & np.isfinite(d["opacity"])
    ok &= sigmoid(d["opacity"]) >= e["min_opacity"]
    ok &= np.exp(d["scale"]).max(1) >= e["min_scale_m"]
    m = e["crop_margin_m"]
    ok &= np.all((d["xyz"] >= lo - m) & (d["xyz"] <= hi + m), 1)
    return subset(d, ok)

def export(cfg: dict, out: Path, fmt: str | None = None) -> dict:
    e = cfg["export"]; fmt = fmt or e["format"]
    if fmt not in FORMATS:
        log.warning("Unknown/unsupported export format '%s'; falling back to 'splat'.", fmt); fmt = "splat"
    d = read_gs_ply(out / "aligned.ply"); n0 = len(d["xyz"])
    col = json.loads((out / "collision.json").read_text()); tr = json.loads((out / "transform.json").read_text())
    lo, hi = np.array(col["bounds"]["min"]), np.array(col["bounds"]["max"])
    lo[1], hi[1] = -0.5, max(hi[1], 3.0) + 0.5
    d = prune(d, e, lo, hi)
    bytes_per = 32 if fmt == "splat" else 4 * (3 + 3 + 3 * ((e["sh_degree"] + 1) ** 2 - 1) + 1 + 3 + 4)
    limit = int(e["max_size_mb"] * 1e6 / bytes_per)
    if len(d["xyz"]) > limit:
        log.warning("%d Gaussians exceed the %d MB budget (%d max); dropping the least important.", len(d["xyz"]), e["max_size_mb"], limit)
        imp = sigmoid(d["opacity"]) * np.exp(d["scale"]).prod(1)
        d = subset(d, np.argsort(-imp)[:limit])
    if len(d["xyz"]) == 0: raise PipelineError("Pruning removed every Gaussian.", "Lower export.min_opacity / export.min_scale_m.")
    ext = "splat" if fmt == "splat" else "ply"
    scene = out / "scene"; scene.mkdir(exist_ok=True)
    for old in scene.glob("scene.*"): old.unlink()
    f = scene / f"scene.{ext}"
    (write_splat if fmt == "splat" else (lambda p, x: write_gs_ply(p, x, e["sh_degree"])))(f, d)
    # spawn near the entrance = first camera position, snapped to the nearest walkable (inflated) cell
    from build_collision import FLOOR, rle_decode
    cams = json.loads((out / "cameras_aligned.json").read_text())
    nx, nz = col["size"]; inf = rle_decode(col["inflated"], (nz, nx)); cell = col["cell_size"]; ox, oz = col["origin"]
    p0, f0 = np.array(cams["positions"][0]), np.array(cams["forward"][0])
    cell_of = lambda x, z: (int((z - oz) / cell), int((x - ox) / cell))
    iz, ix = cell_of(p0[0], p0[2]); sx, sz = float(p0[0]), float(p0[2])
    if not (0 <= iz < nz and 0 <= ix < nx and inf[iz, ix] == FLOOR):
        w = np.argwhere(inf == FLOOR)
        if len(w) == 0: raise PipelineError("No walkable cell for spawn.", "See collision stage output.")
        cx, cz = ox + (w[:, 1] + .5) * cell, oz + (w[:, 0] + .5) * cell
        k = int(np.argmin((cx - p0[0]) ** 2 + (cz - p0[2]) ** 2)); sx, sz = float(cx[k]), float(cz[k])
        log.warning("First camera not on a walkable cell; spawn snapped to (%.2f, %.2f).", sx, sz)
    yaw = float(np.arctan2(-f0[0], -f0[2]))   # three.js: forward=(-sin yaw, 0, -cos yaw)
    meta = {"version": 1, "scene_file": f.name, "format": ext, "gaussian_count": int(len(d["xyz"])), "size_mb": round(f.stat().st_size / 1e6, 2),
            "spawn": {"position": [round(sx, 3), cfg["viewer"]["eye_height_m"], round(sz, 3)], "yaw": round(yaw, 4)},
            "eye_height": cfg["viewer"]["eye_height_m"], "walk_speed": cfg["viewer"]["walk_speed"], "run_speed": cfg["viewer"]["run_speed"],
            "bounds": col["bounds"], "scale": {"method": tr["method"], "factor": tr["scale"], "approximate": tr["approximate"], "confidence": tr["confidence"]},
            "collision_file": "collision.json", "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    (scene / "meta.json").write_text(json.dumps(meta, indent=2))
    scene_info = {
        "version": 1,
        "scene_file": f.name,
        "format": ext,
        "spawn_position": [round(sx, 3), cfg["viewer"]["eye_height_m"], round(sz, 3)],
        "spawn_yaw": round(yaw, 4),
        "bounding_box": col["bounds"],
        "floor_height": 0.0,
        "scale_factor": tr["scale"],
        "scale_method": tr["method"],
        "approximate_scale": tr["approximate"],
        "scale_confidence": tr["confidence"],
        "gaussian_count": int(len(d["xyz"])),
        "size_mb": round(f.stat().st_size / 1e6, 2),
    }
    (scene / "scene_info.json").write_text(json.dumps(scene_info, indent=2))
    (out / "scene_info.json").write_text(json.dumps(scene_info, indent=2))
    shutil.copy(out / "collision.json", scene / "collision.json")
    dest = Path(e["viewer_scene_dir"]) if e.get("viewer_scene_dir") else Path(__file__).resolve().parent.parent / "viewer" / "public" / "scene"
    dest.mkdir(parents=True, exist_ok=True)
    for old in dest.glob("scene.*"): old.unlink()
    (dest / "SYNTHETIC_DEMO.txt").unlink(missing_ok=True)   # a real export replaces the synthetic demo scene
    for x in scene.iterdir(): shutil.copy(x, dest / x.name)
    rep = {"format": ext, "gaussians_before": n0, "gaussians_after": meta["gaussian_count"], "size_mb_before_ply": round((out / "aligned.ply").stat().st_size / 1e6, 2),
           "size_mb_after": meta["size_mb"], "viewer_dir": str(dest)}
    if meta["size_mb"] > e["max_size_mb"]: log.warning("Scene is %.1f MB (> %d MB target).", meta["size_mb"], e["max_size_mb"])
    (out / "export_report.json").write_text(json.dumps(rep, indent=2))
    log.info("Exported %s: %d -> %d Gaussians, %.1f -> %.1f MB", ext, n0, rep["gaussians_after"], rep["size_mb_before_ply"], rep["size_mb_after"])
    return rep

def run(cfg: dict, out: Path, inputs: list[Path]) -> dict:
    """Stage entry point."""
    return export(cfg, out, cfg.get("_format"))

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--out", type=Path, required=True); ap.add_argument("--format", choices=FORMATS)
    ap.add_argument("--mode", default="fast"); a = ap.parse_args()
    try: export(load_config(Path(__file__).parent / "config.yaml", a.mode), a.out, a.format)
    except PipelineError as ex: log.error("%s\nFix: %s", ex, ex.fix); sys.exit(2)
