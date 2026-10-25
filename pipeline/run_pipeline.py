"""One-command pipeline.
Usage: python pipeline/run_pipeline.py --video <file_or_folder> --out <dir> [--mode fast|quality] [--resume]
"""
from __future__ import annotations
import argparse, importlib, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from report import write_report
from utils import PipelineError, get_logger, load_config, run_stage

STAGES = ["extract_frames", "reconstruct", "align_scene", "build_collision", "export_scene"]
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".avi", ".mkv"}

def find_videos(p: Path) -> list[Path]:
    if p.is_file(): return [p]
    if p.is_dir():
        v = sorted(f for f in p.iterdir() if f.suffix.lower() in VIDEO_EXT)
        if v: return v
    raise PipelineError(f"No video found at {p}", "Pass a video file or a folder containing .mp4/.mov files.")

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Roomscape pipeline")
    ap.add_argument("--video", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--mode", default="fast", choices=["fast", "quality"])
    ap.add_argument("--format", choices=["splat", "ply"], help="scene export format (default from config)")
    ap.add_argument("--resume", action="store_true", help="skip stages whose .done marker exists")
    ap.add_argument("--config", type=Path, default=Path(__file__).parent / "config.yaml")
    ap.add_argument("--frames", type=int, help="target frame count (overrides config)")
    ap.add_argument("--trim-start", type=float, help="trim video before this timestamp in seconds")
    ap.add_argument("--trim-end", type=float, help="trim video after this timestamp in seconds")
    ap.add_argument("--no-gpu", action="store_true", help="run COLMAP without GPU")
    a = ap.parse_args(argv)
    log = get_logger()
    t0, current, mode = time.perf_counter(), None, a.mode
    def finish(status: str, failed: str | None = None) -> None:
        if a.out.exists():
            try:
                write_report(a.out, mode, time.perf_counter() - t0, status, failed, STAGES)
                log.info("Report: %s and %s", a.out / "report.md", a.out / "report.json")
            except Exception as e:  # noqa: BLE001  (a report problem must never hide the real result)
                log.warning("Could not write report: %s", e)
    try:
        cfg = load_config(a.config, a.mode)
        cfg["_resume"] = a.resume
        cfg["_format"] = a.format
        if a.frames is not None:
            cfg["frames"]["target_count"] = a.frames
        if a.trim_start is not None:
            cfg["frames"]["trim_start_s"] = a.trim_start
        if a.trim_end is not None:
            cfg["frames"]["trim_end_s"] = a.trim_end
        if a.no_gpu:
            cfg["colmap"]["use_gpu"] = False
        videos = find_videos(a.video)
        a.out.mkdir(parents=True, exist_ok=True)
        log.info("mode=%s videos=%d out=%s", a.mode, len(videos), a.out)
        for current in STAGES:
            mod = importlib.import_module(current)
            run_stage(current, lambda m=mod: m.run(cfg, a.out, videos), a.out, a.resume)
        current = None
        finish("ok")
        log.info("Pipeline finished. Preview: cd viewer && npm run dev")
        return 0
    except PipelineError as e:
        log.error("Stage '%s' failed: %s", current, e)
        if e.fix: log.error("Suggested fix: %s", e.fix)
        if current: log.error("Fix the problem, then re-run the same command with --resume to continue from this stage.")
        finish("failed", current)
        return 2
    except KeyboardInterrupt:
        log.error("Interrupted. Re-run with --resume to continue."); finish("interrupted", current); return 130
    except Exception as e:  # noqa: BLE001
        log.exception("Unexpected error in stage '%s': %s", current, e)
        log.error("This is a bug or an environment problem. Check out/logs/, then retry with --resume.")
        finish("failed", current); return 1

if __name__ == "__main__":
    sys.exit(main())
