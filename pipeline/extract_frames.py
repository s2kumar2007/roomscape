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
import shutil
import cv2
import numpy as np
from utils import PipelineError, get_logger

log = get_logger()

@dataclass
class Cand:
    video: int
    t: float
    n: int
    sharp: float
    thumb: np.ndarray
    cache_path: Path | None = None

def sharpness(gray: np.ndarray) -> float:
    """Variance of the Laplacian; higher = sharper."""
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())

def _resize(img: np.ndarray, max_side: int) -> np.ndarray:
    h, w = img.shape[:2]
    if max_side and max(h, w) > max_side:
        s = max_side / max(h, w)
        return cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
    return img

def sample_candidates(path: Path, vid: int, fps_target: float, max_side: int,
                      trim_start_s: float = 0.0, trim_end_s: float = 0.0,
                      cache_dir: Path | None = None) -> list[Cand]:
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise PipelineError(f"Cannot open video {path}", "Check the file is a valid MP4/MOV and ffmpeg codecs are installed.")
    cap.set(cv2.CAP_PROP_ORIENTATION_AUTO, 1)  # honour phone rotation metadata
    step, next_t, out, idx = 1.0 / fps_target, 0.0, [], 0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    log.info("Scanning %s (total frames ~%d, target sampling %g fps)...", path.name, total_frames, fps_target)

    while cap.grab():
        curr_n = idx
        t = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
        if t < 0 or (t == 0 and idx > 0):  # backend gave no timestamp: fall back on nominal fps
            t = idx / (cap.get(cv2.CAP_PROP_FPS) or 30.0)
        idx += 1
        if trim_start_s > 0 and t + 1e-6 < trim_start_s:
            continue
        if trim_end_s > 0 and t - 1e-6 > trim_end_s:
            break
        if t + 1e-6 < next_t:
            continue
        ok, frame = cap.retrieve()
        if not ok:
            continue
        next_t = t + step
        frame = _resize(frame, max_side)
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        thumb = cv2.resize(gray, (64, 64), interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0
        cache_path = None
        if cache_dir is not None:
            cache_dir.mkdir(parents=True, exist_ok=True)
            cache_path = cache_dir / f"video_{vid:03d}_frame_{curr_n:08d}.jpg"
            if not cv2.imwrite(str(cache_path), frame, [cv2.IMWRITE_JPEG_QUALITY, 95]):
                cap.release()
                raise PipelineError(f"Could not cache sampled frame {curr_n} from {path.name}.",
                                    "Check that the output disk has free space and is writable.")
        out.append(Cand(vid, t, curr_n, sharpness(gray), thumb, cache_path))
        if len(out) % 100 == 0 or idx % 600 == 0:
            pct = f" ({idx * 100 // total_frames}%)" if total_frames > 0 else ""
            log.info("  scanned frame %d%s: %d candidates at t=%.1fs...", idx, pct, len(out), t)
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

def save_selected(video: Path, chosen: list[Cand], out_dir: Path, max_side: int, start_idx: int = 0) -> int:
    """Second pass: re-open video and write only chosen frames to disk."""
    if not chosen:
        return 0
    if all(c.cache_path is not None for c in chosen):
        for pos, cand in enumerate(chosen):
            target = out_dir / f"frame_{start_idx + pos:05d}.jpg"
            if cand.cache_path is None or not cand.cache_path.is_file():
                raise PipelineError(f"Cached sampled frame is missing for {video.name} at {cand.t:.2f}s.",
                                    "Re-run frame extraction; the temporary frame cache may have been removed.")
            shutil.copyfile(cand.cache_path, target)
            if (pos + 1) % 50 == 0 or pos + 1 == len(chosen):
                log.info("  wrote %d / %d frames...", pos + 1, len(chosen))
        return len(chosen)
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise PipelineError(f"Cannot open video {video}", "Check the file is a valid MP4/MOV and ffmpeg codecs are installed.")
    cap.set(cv2.CAP_PROP_ORIENTATION_AUTO, 1)

    chosen_by_n: dict[int, list[int]] = {}
    for pos, c in enumerate(chosen):
        chosen_by_n.setdefault(c.n, []).append(pos)

    saved, idx = 0, 0
    log.info("Saving %d selected frames to %s...", len(chosen), out_dir)
    while cap.grab():
        if idx in chosen_by_n:
            ok, frame = cap.retrieve()
            if not ok:
                raise PipelineError(
                    f"Failed to retrieve frame {idx} from {video.name}",
                    "Video file may be corrupted. Try re-encoding with ffmpeg or re-capturing."
                )
            frame = _resize(frame, max_side)
            for pos in chosen_by_n[idx]:
                cv2.imwrite(str(out_dir / f"frame_{start_idx + pos:05d}.jpg"), frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
                saved += 1
                if saved % 50 == 0 or saved == len(chosen):
                    log.info("  wrote %d / %d frames...", saved, len(chosen))
            if saved == len(chosen):
                break
        idx += 1
    cap.release()

    if saved < len(chosen):
        raise PipelineError(
            f"Second pass extracted {saved} frames, expected {len(chosen)} from {video.name}.",
            "Video file may have been modified or is corrupted. Re-capture or re-encode video."
        )
    return saved

def extract(cfg: dict, out: Path, videos: list[Path]) -> dict:
    fc = cfg["frames"]
    fdir = out / "frames"
    fdir.mkdir(parents=True, exist_ok=True)
    cache_root = out / ".candidate_cache"
    if cache_root.exists():
        shutil.rmtree(cache_root)
    cache_root.mkdir(parents=True, exist_ok=True)
    for old in fdir.glob("*.jpg"):
        old.unlink()
    trim_start = float(fc.get("trim_start_s", 0.0) or 0.0)
    trim_end = float(fc.get("trim_end_s", 0.0) or 0.0)
    per_video, stats = [], {"candidates": 0, "dropped_blur": 0, "dropped_duplicate": 0, "dropped_excess": 0}
    for i, v in enumerate(videos):
        # Keep about twice the requested frame count, spread across the clip.
        cap = cv2.VideoCapture(str(v))
        duration = 0.0
        if cap.isOpened():
            fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
            count = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0
            duration = count / fps if fps > 0 else 0.0
        cap.release()
        if trim_end > 0:
            duration = max(0.0, min(duration, trim_end) - trim_start)
        elif trim_start > 0 and duration > 0:
            duration = max(0.0, duration - trim_start)
        per_video_target = max(1, int(np.ceil(fc["target_count"] / len(videos))))
        target_fps = float(fc["candidate_fps"])
        if duration > 0 and per_video_target > 0:
            target_fps = min(target_fps, max(0.05, 2.0 * per_video_target / duration))
        log.info("Sampling %s at up to %.3g fps (about %d candidates for %d target frames).",
                 v.name, target_fps, 2 * per_video_target, per_video_target)
        cands = sample_candidates(v, i, target_fps, fc["max_side"], trim_start, trim_end,
                                  cache_root / f"video_{i:03d}")
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
        save_selected(v, chosen, fdir, fc["max_side"], start_idx=saved)
        for x in chosen:
            sharp_vals.append(x.sharp)
        saved += len(chosen)
    report = {"videos": [str(v) for v in videos], "kept": saved, **stats,
              "avg_sharpness": round(float(np.mean(sharp_vals)), 2), "target_count": fc["target_count"]}
    (out / "frames_report.json").write_text(json.dumps(report, indent=2))
    shutil.rmtree(cache_root, ignore_errors=True)
    log.info("Frames kept: %d (target %d)", saved, fc["target_count"])
    if saved < 60:
        log.warning("Only %d frames kept; reconstruction usually needs 100+. Capture longer/slower (docs/SOP.md).", saved)
    return report

def run(cfg: dict, out: Path, inputs: list[Path]) -> dict:
    """Stage entry point."""
    r = extract(cfg, out, inputs)
    return {"frames_kept": r["kept"], "dropped_blur": r["dropped_blur"],
            "dropped_duplicate": r["dropped_duplicate"], "avg_sharpness": r["avg_sharpness"]}
