"""Phase 2: frame extraction.

Pipeline per video: sample candidates by *timestamp* (robust to variable frame rate)
-> score sharpness (variance of Laplacian) -> drop blurry frames (adaptive threshold)
-> drop near-duplicates (stationary camera) -> select an evenly spread target count.
Phone rotation metadata is applied by OpenCV (CAP_PROP_ORIENTATION_AUTO).
"""
from __future__ import annotations
import json
from dataclasses import dataclass
from pathlib import Path
import cv2
import numpy as np
from utils import PipelineError, get_logger

log = get_logger()

@dataclass
class Cand:
    video: int
    t: float
    img: np.ndarray
    sharp: float
    thumb: np.ndarray

def sharpness(gray: np.ndarray) -> float:
    """Variance of the Laplacian; higher = sharper."""
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())

def _resize(img: np.ndarray, max_side: int) -> np.ndarray:
    h, w = img.shape[:2]
    if max_side and max(h, w) > max_side:
        s = max_side / max(h, w)
        return cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
    return img

def sample_candidates(path: Path, vid: int, fps_target: float, max_side: int) -> list[Cand]:
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise PipelineError(f"Cannot open video {path}", "Check the file is a valid MP4/MOV and ffmpeg codecs are installed.")
    cap.set(cv2.CAP_PROP_ORIENTATION_AUTO, 1)  # honour phone rotation metadata
    step, next_t, out, idx = 1.0 / fps_target, 0.0, [], 0
    while cap.grab():
        t = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
        if t < 0 or (t == 0 and idx > 0):  # backend gave no timestamp: fall back on nominal fps
            t = idx / (cap.get(cv2.CAP_PROP_FPS) or 30.0)
        idx += 1
        if t + 1e-6 < next_t:
            continue
        ok, frame = cap.retrieve()
        if not ok:
            continue
        next_t = t + step
        frame = _resize(frame, max_side)
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        thumb = cv2.resize(gray, (64, 64), interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0
        out.append(Cand(vid, t, frame, sharpness(gray), thumb))
    cap.release()
    return out

def filter_blur(c: list[Cand], percentile: float, min_abs: float) -> tuple[list[Cand], float]:
    if not c:
        return [], 0.0
    thr = max(min_abs, float(np.percentile([x.sharp for x in c], percentile)))
    return [x for x in c if x.sharp >= thr], thr

def filter_duplicates(c: list[Cand], thr: float) -> list[Cand]:
    """Drop a frame if it barely differs from the last kept frame (stationary camera)."""
    kept: list[Cand] = []
    for x in c:
        if kept and float(np.abs(x.thumb - kept[-1].thumb).mean()) < thr:
            continue
        kept.append(x)
    return kept

def select_even(c: list[Cand], n: int) -> list[Cand]:
    if n <= 0 or len(c) <= n:
        return c
    return [c[i] for i in np.linspace(0, len(c) - 1, n).round().astype(int)]

def extract(cfg: dict, out: Path, videos: list[Path]) -> dict:
    fc = cfg["frames"]
    fdir = out / "frames"
    fdir.mkdir(parents=True, exist_ok=True)
    for old in fdir.glob("*.jpg"):
        old.unlink()
    per_video, stats = [], {"candidates": 0, "dropped_blur": 0, "dropped_duplicate": 0, "dropped_excess": 0}
    for i, v in enumerate(videos):
        cands = sample_candidates(v, i, fc["candidate_fps"], fc["max_side"])
        sharp_ok, thr = filter_blur(cands, fc["blur_percentile"], fc["min_blur_abs"])
        deduped = filter_duplicates(sharp_ok, fc["dup_threshold"])
        per_video.append((v, cands, sharp_ok, deduped, thr))
        log.info("%s: %d candidates, blur thr=%.1f, after blur=%d, after dedup=%d",
                 v.name, len(cands), thr, len(sharp_ok), len(deduped))
    total_pool = sum(len(p[3]) for p in per_video)
    if total_pool == 0:
        raise PipelineError("No usable frames after filtering.",
                            "Video may be too dark/blurry. Re-capture per docs/SOP.md or lower frames.min_blur_abs.")
    saved, sharp_vals = 0, []
    for v, cands, sharp_ok, deduped, thr in per_video:
        share = max(1, round(fc["target_count"] * len(deduped) / total_pool))  # proportional per video
        chosen = select_even(deduped, share)
        stats["candidates"] += len(cands)
        stats["dropped_blur"] += len(cands) - len(sharp_ok)
        stats["dropped_duplicate"] += len(sharp_ok) - len(deduped)
        stats["dropped_excess"] += len(deduped) - len(chosen)
        for x in chosen:
            cv2.imwrite(str(fdir / f"frame_{saved:05d}.jpg"), x.img, [cv2.IMWRITE_JPEG_QUALITY, 95])
            sharp_vals.append(x.sharp)
            saved += 1
    report = {"videos": [str(v) for v in videos], "kept": saved, **stats,
              "avg_sharpness": round(float(np.mean(sharp_vals)), 2), "target_count": fc["target_count"]}
    (out / "frames_report.json").write_text(json.dumps(report, indent=2))
    log.info("Frames kept: %d (target %d)", saved, fc["target_count"])
    if saved < 60:
        log.warning("Only %d frames kept; reconstruction usually needs 100+. Capture longer/slower (docs/SOP.md).", saved)
    return report

def run(cfg: dict, out: Path, inputs: list[Path]) -> dict:
    """Stage entry point."""
    r = extract(cfg, out, inputs)
    return {"frames_kept": r["kept"], "dropped_blur": r["dropped_blur"],
            "dropped_duplicate": r["dropped_duplicate"], "avg_sharpness": r["avg_sharpness"]}
