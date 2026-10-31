"""Final run summary -> out/report.json + out/report.md. Every number is read from files the stages wrote; missing -> null/'n/a' (never invented)."""
from __future__ import annotations
import json
from pathlib import Path

def _load(p: Path) -> dict:
    try: return json.loads(p.read_text())
    except (OSError, ValueError): return {}

def build_report(
    out: Path,
    mode: str,
    wall_s: float,
    status: str = "ok",
    failed_stage: str | None = None,
    stages: list[str] | None = None,
    failure_reason: str | None = None,
    mock: bool = False,
) -> dict:
    t, fr, rc = _load(out / "timings.json"), _load(out / "frames_report.json"), _load(out / "reconstruct_report.json")
    tr, ex, col = _load(out / "transform.json"), _load(out / "export_report.json"), _load(out / "collision.json")
    meta = _load(out / "scene" / "meta.json")

    is_mock = bool(
        mock
        or status == "mock"
        or t.get("mock") is True
        or meta.get("mock") is True
        or rc.get("matcher") == "mock"
        or rc.get("mock") is True
    )
    if is_mock and status == "ok":
        status = "mock"

    per = {s: t[s]["seconds"] for s in (stages or t) if s in t and isinstance(t[s], dict) and "seconds" in t[s]}
    grid = None
    if col:
        nx, nz = col["size"]; grid = {"size": [nx, nz], "cell_size_m": col["cell_size"]}
        if "collision_walkable_area_m2" in t.get("build_collision", {}) or "walkable_area_m2" in t.get("build_collision", {}):
            grid["walkable_area_m2"] = t["build_collision"].get("walkable_area_m2")
    rep = {
        "status": status, "failed_stage": failed_stage, "failure_reason": failure_reason, "mode": mode,
        "stage_seconds": per, "total_stage_seconds": round(sum(per.values()), 1), "this_invocation_seconds": round(wall_s, 1),
        "frames": {k: fr.get(k) for k in ("kept", "candidates", "dropped_blur", "dropped_duplicate", "avg_sharpness", "target_count")},
        "reconstruction": {k: rc.get(k) for k in ("images_input", "images_registered", "registration_rate", "matcher", "iterations", "gaussian_count", "colmap_seconds", "train_seconds", "metrics")},
        "alignment": {"scale_method": tr.get("method"), "metres_per_unit": tr.get("scale"), "approximate": tr.get("approximate"), "confidence": tr.get("confidence"),
                      "floor_inlier_ratio": tr.get("floor_inlier_ratio"), "median_camera_height_m": tr.get("median_camera_height_m")},
        "collision": grid,
        "export": {k: ex.get(k) for k in ("format", "gaussians_before", "gaussians_after", "size_mb_before_ply", "size_mb_after")},
        "viewer": {"spawn": meta.get("spawn"), "bounds": meta.get("bounds")},
    }
    if is_mock:
        rep["mock"] = True
    return rep

def _f(v, fmt="{}", none="n/a"):
    return none if v is None else fmt.format(v)

def render_md(r: dict) -> str:
    fr, rc, al, ex = r["frames"], r["reconstruction"], r["alignment"], r["export"]
    is_mock = bool(r.get("mock") or r.get("status") == "mock")
    L = []
    if is_mock:
        L.append("**MOCK RUN - NOT A REAL RECONSTRUCTION**")
        L.append("")
    L.extend([
        f"# Roomscape: run report",
        "",
        f"**Status:** {r['status']}" + (f" (failed at `{r['failed_stage']}`)" if r["failed_stage"] else "") + f"  |  **Mode:** {r['mode']}",
    ])
    if r.get("failure_reason"):
        L.append(f"**Failure reason:** {r['failure_reason']}")
    L += ["", "## Timing", "", "| Stage | Seconds |", "|---|---|"]
    L += [f"| {s} | {v} |" for s, v in r["stage_seconds"].items()]
    L += [f"| **Total (sum of stages)** | **{r['total_stage_seconds']}** |", "",
          "## Results", "", "| Metric | Value |", "|---|---|",
          f"| Frames used | {_f(fr['kept'])} (candidates {_f(fr['candidates'])}, dropped blurry {_f(fr['dropped_blur'])}, duplicates {_f(fr['dropped_duplicate'])}) |",
          f"| Registration rate | {_f(rc['registration_rate'] and round(rc['registration_rate'] * 100, 1), '{}%')} ({_f(rc['images_registered'])}/{_f(rc['images_input'])} images) |",
          f"| Training iterations | {_f(rc['iterations'])} |",
          f"| Gaussians (trained) | {_f(rc['gaussian_count'], '{:,}')} |",
          f"| Quality metrics (PSNR/SSIM/LPIPS) | {_f(rc['metrics'] or None)} |",
          f"| Scale method | {_f(al['scale_method'])}{' (APPROXIMATE)' if al['approximate'] else ''}, confidence {_f(al['confidence'])} |",
          f"| Metres per splat unit | {_f(al['metres_per_unit'] and round(al['metres_per_unit'], 4))} |",
          f"| Exported scene | {_f(ex['format'])}: {_f(ex['gaussians_after'], '{:,}')} Gaussians, {_f(ex['size_mb_after'])} MB (raw PLY {_f(ex['size_mb_before_ply'])} MB) |", ""]
    if r["collision"]: L.append(f"Collision grid: {r['collision']['size'][0]}x{r['collision']['size'][1]} cells @ {r['collision']['cell_size_m']} m.\n")
    if is_mock:
        L.append("Viewer: Mock scene output written to `out/scene/` (not copied to `viewer/public/scene/` in mock mode).")
    else:
        L.append("Viewer: `cd viewer && npm run dev` (scene already copied to `viewer/public/scene/`).")
    return "\n".join(L) + "\n"

def write_report(
    out: Path,
    mode: str,
    wall_s: float,
    status: str = "ok",
    failed_stage: str | None = None,
    stages: list[str] | None = None,
    failure_reason: str | None = None,
    mock: bool = False,
) -> dict:
    r = build_report(out, mode, wall_s, status, failed_stage, stages, failure_reason=failure_reason, mock=mock)
    (out / "report.json").write_text(json.dumps(r, indent=2))
    (out / "report.md").write_text(render_md(r))
    return r
