# Architecture and data formats

## Stages (`python pipeline/run_pipeline.py --video V --out O [--mode fast|quality] [--format splat|ply] [--resume]`)
| # | Stage | Input -> Output | Notes |
|---|---|---|---|
| 1 | extract_frames | videos -> `O/frames/*.jpg`, `frames_report.json` | timestamp sampling, variance-of-Laplacian blur filter (adaptive), duplicate filter, even selection, honours phone rotation |
| 2 | reconstruct | frames -> `O/ns_data/` (COLMAP via Nerfstudio), `O/train/`, `O/splat.ply`, `reconstruct_report.json` | needs GPU + Nerfstudio + COLMAP (or the Colab notebook) |
| 3 | align_scene | splat.ply -> `aligned.ply`, `transform.json`, `cameras_aligned.json`, `debug/floor_alignment.png` | RANSAC floor, Y-up, floor Y=0, metric scale (marker or camera-height fallback) |
| 4 | build_collision | aligned.ply -> `collision.json`, `occupancy.png` | 2D grid + agent-radius inflation |
| 5 | export_scene | aligned.ply -> `scene/scene.{splat,ply}`, `meta.json`, copy to `viewer/public/scene/` | prune, crop, size budget |
Every stage logs, records seconds in `O/timings.json`, and writes `O/.markers/<stage>.done` (`--resume` skips finished stages).

## Coordinate system
Right-handed, **Y up, floor at Y=0, metres**. Same as three.js, so no flips are needed in the viewer.
Yaw convention: forward = (-sin yaw, 0, -cos yaw); yaw 0 looks along -Z.

## `collision.json` (Round 2 runs A* on this)
```json
{ "version": 1, "origin": [ox, oz], "cell_size": 0.1, "size": [nx, nz], "encoding": "rle_row_major",
  "values": {"unknown": 0, "floor": 1, "blocked": 2},
  "grid": [[value, run], ...], "inflated": [[value, run], ...],
  "agent_radius_m": 0.25, "floor_height": 0.0, "bounds": {"min": [x,y,z], "max": [x,y,z]}, "blocked_band_m": [0.15, 1.8] }
```
* Cell of world point (x, z): `ix = floor((x-ox)/cell)`, `iz = floor((z-oz)/cell)`, flat index `iz*nx + ix`.
* `grid`: cleaned occupancy. BLOCKED = >= `blocked_min_points` Gaussians between 0.15 m and 1.8 m height; FLOOR = floor points with nothing blocking; else UNKNOWN.
* `inflated`: BLOCKED dilated by the agent radius. **Walkable iff value == 1.** UNKNOWN is never walkable (A* should avoid it).
* RLE: row-major runs `[value, length]`; decode by concatenating runs (see `viewer/src/collision.ts`, `pipeline/build_collision.py`).

## `meta.json`
`scene_file`, `format` (splat|ply), `gaussian_count`, `size_mb`, `spawn {position[x,y,z], yaw}` (first camera = entrance, snapped to a walkable cell), `eye_height`, `walk_speed`, `run_speed`, `bounds`, `scale {method, factor, approximate, confidence}`, `collision_file`, `generated_at`.

## `transform.json`
`matrix` (4x4 similarity applied to the trained splat), `rotation`, `scale` (metres per splat unit), `method` (`apriltag` | `camera_height_fallback`), `approximate`, `confidence` (0-1 heuristic from tag-side consistency, reprojection residual and view count; 0.3 for the fallback), `tag` details, `floor_inlier_ratio`, `camera_up_deviation_deg`, `bounds`.

## Design decisions
* **Gaussian splatting + a separate collision proxy.** Splats look photoreal but have no surface for collision; the proxy gives Rounds 2-3 (A*, AR) a cheap, exact navigation structure.
* **Nerfstudio splatfacto (gsplat, Apache-2.0)** instead of the original Inria code (non-commercial licence).
* **Own PLY I/O**: `plyfile` is GPL-3.0, so a small numpy reader/writer is used instead.
* **Scale from camera rays, not from the splat:** the marker is triangulated from camera poses (no dependence on splat quality); fallback is flagged "approximate".
* **SH:** degree-1 SH is rotated exactly; higher bands are dropped at alignment (rotating them needs Wigner matrices). `.splat` export carries no SH at all (view-dependent shading lost, 32 B/Gaussian).
* **Camera frame:** Nerfstudio trains in a dataparser-transformed frame; poses are mapped with `dataparser_transforms.json` before use.
* **Formats:** Spark also loads SPZ/SOG/KSPLAT; they would shrink files further but need external encoders (roadmap).
