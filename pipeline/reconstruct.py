"""Phase 3: camera poses (COLMAP via Nerfstudio) + Gaussian splat training (splatfacto/gsplat).

Docs-verified CLI (Nerfstudio):
  ns-process-data images --data D --output-dir O --matching-method {exhaustive,sequential,vocab_tree}
  ns-train splatfacto --data O --max-num-iterations N
  ns-export gaussian-splat --load-config config.yml --output-dir X
Nerfstudio's COLMAP wrapper uses ONE shared camera model for all images (right for one phone).
Flags change between releases, so we also check `--help` output at runtime and warn on mismatch.
"""
from __future__ import annotations
import json, re, shutil, subprocess, time
from pathlib import Path
from utils import PipelineError, get_logger

log = get_logger()
TOOLS = {"ns-process-data": "pip install nerfstudio  (see https://docs.nerf.studio/quickstart/installation.html)",
         "ns-train": "pip install nerfstudio", "ns-export": "pip install nerfstudio",
         "colmap": "conda install -c conda-forge colmap", "ffmpeg": "conda install -c conda-forge ffmpeg"}

def preflight() -> None:
    missing = [f"{t}  ->  {fix}" for t, fix in TOOLS.items() if not shutil.which(t)]
    if missing:
        raise PipelineError("Missing required tools:\n  " + "\n  ".join(missing),
                            "Run scripts/check_gpu.py, or use notebooks/colab_reconstruct.ipynb if you have no local setup.")
    if not shutil.which("nvidia-smi"):
        log.warning("nvidia-smi not found: splat training needs an NVIDIA GPU (or use the Colab notebook).")

def check_flags(cmd: list[str], needed: list[str]) -> None:
    """Warn (not fail) if expected flags are absent from `<cmd> --help`: the CLI may have changed."""
    try:
        txt = subprocess.run(cmd + ["--help"], capture_output=True, text=True, timeout=120)
        txt = txt.stdout + txt.stderr
    except Exception as e:  # noqa: BLE001
        log.warning("Could not read help for %s (%s)", " ".join(cmd), e); return
    for f in needed:
        if f not in txt:
            log.warning("Flag %s not found in `%s --help`; Nerfstudio CLI may have changed. Check docs.nerf.studio.", f, " ".join(cmd))

def run_cmd(cmd: list[str], logfile: Path, fix: str) -> None:
    """Run a subprocess, stream its output to our logger + a file, and raise on non-zero exit."""
    log.info("$ %s", " ".join(cmd))
    logfile.parent.mkdir(parents=True, exist_ok=True)
    tail: list[str] = []
    with open(logfile, "a") as lf:
        try:
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        except FileNotFoundError as e:
            raise PipelineError(f"Command not found: {cmd[0]}", fix) from e
        assert p.stdout is not None
        for line in p.stdout:
            line = line.rstrip()
            lf.write(line + "\n"); tail.append(line); tail[:] = tail[-15:]
            log.info("  | %s", line)
        rc = p.wait()
    if rc != 0:
        raise PipelineError(f"`{cmd[0]}` failed (exit {rc}). Last output:\n" + "\n".join(tail), fix)

def registration_stats(data_dir: Path, n_input: int) -> dict:
    """Registered images = frames present in transforms.json (images COLMAP could place)."""
    tj = data_dir / "transforms.json"
    if not tj.exists():
        raise PipelineError("COLMAP produced no transforms.json.", "Capture with more overlap and texture; see docs/SOP.md.")
    n_reg = len(json.loads(tj.read_text()).get("frames", []))
    return {"images_input": n_input, "images_registered": n_reg,
            "registration_rate": round(n_reg / max(n_input, 1), 4)}

def check_registration(st: dict, min_rate: float) -> None:
    if st["images_registered"] < 20:
        raise PipelineError(f"Only {st['images_registered']} images registered: reconstruction not viable.",
                            "Re-capture: walk slower, keep 60-80% overlap, add light, avoid blank walls and spinning in place.")
    if st["registration_rate"] < min_rate:
        log.warning("Only %.0f%% of images registered (< %.0f%%). SOP fixes: walk slower, increase overlap, "
                    "improve lighting, lock exposure/focus, avoid motion blur, add loop closure. "
                    "Quality mode (exhaustive matcher) may also help.", st["registration_rate"] * 100, min_rate * 100)

def ply_vertex_count(ply: Path) -> int:
    """Gaussian count = `element vertex N` in the PLY header."""
    with open(ply, "rb") as f:
        for raw in f:
            line = raw.decode("ascii", "ignore").strip()
            m = re.match(r"element vertex (\d+)", line)
            if m: return int(m.group(1))
            if line == "end_header": break
    raise PipelineError(f"Cannot read Gaussian count from {ply}", "The PLY header looks invalid; re-run export.")

def latest_config(train_dir: Path) -> Path:
    cfgs = sorted(train_dir.rglob("config.yml"), key=lambda p: p.stat().st_mtime)
    if not cfgs:
        raise PipelineError("Training finished but no config.yml was found.", f"Look inside {train_dir} and re-run with --resume.")
    return cfgs[-1]

def eval_metrics(cfg_path: Path, out: Path) -> dict:
    """Best-effort PSNR/SSIM via ns-eval; returns {} if unavailable (never fails the pipeline)."""
    if not shutil.which("ns-eval"): return {}
    res = out / "eval.json"
    try:
        run_cmd(["ns-eval", "--load-config", str(cfg_path), "--output-path", str(res)], out / "logs" / "eval.log", "")
        r = json.loads(res.read_text()).get("results", {})
        return {k: round(float(r[k]), 4) for k in ("psnr", "ssim", "lpips") if k in r}
    except Exception as e:  # noqa: BLE001
        log.warning("Metric evaluation skipped: %s", str(e).splitlines()[0]); return {}

def reconstruct(cfg: dict, out: Path) -> dict:
    preflight()
    frames = out / "frames"
    n_in = len(list(frames.glob("*.jpg")))
    if n_in == 0:
        raise PipelineError(f"No frames in {frames}", "Run the extract_frames stage first.")
    c, t, logs = cfg["colmap"], cfg["train"], out / "logs"
    resume = bool(cfg.get("_resume"))
    data, train, splat = out / "ns_data", out / "train", out / "splat"
    if not c.get("single_camera", True):
        log.warning("single_camera=false is not supported by Nerfstudio's COLMAP wrapper; one shared camera is used.")

    t0 = time.perf_counter()
    if resume and (data / "transforms.json").exists():
        log.info("Reusing existing COLMAP result in %s", data)
    else:
        check_flags(["ns-process-data", "images"], ["--matching-method", "--output-dir"])
        run_cmd(["ns-process-data", "images", "--data", str(frames), "--output-dir", str(data),
                 "--matching-method", c["matcher"]], logs / "colmap.log",
                "Check COLMAP installs (`colmap -h`). Try matcher=exhaustive in config.yaml, or capture per docs/SOP.md.")
    t_colmap = time.perf_counter() - t0
    reg = registration_stats(data, n_in)
    check_registration(reg, c["min_registration_rate"])

    t0 = time.perf_counter()
    if resume and list(train.rglob("config.yml")):
        log.info("Reusing existing training run in %s", train)
    else:
        check_flags(["ns-train", "splatfacto"], ["--max-num-iterations", "--data"])
        run_cmd(["ns-train", t["method"], "--data", str(data), "--max-num-iterations", str(t["iterations"]),
                 "--output-dir", str(train), "--viewer.quit-on-train-completion", "True"],
                logs / "train.log", "CUDA out of memory? Use fast mode, fewer frames, or the Colab notebook. See logs/train.log.")
    t_train = time.perf_counter() - t0
    cfg_path = latest_config(train)

    run_cmd(["ns-export", "gaussian-splat", "--load-config", str(cfg_path), "--output-dir", str(splat)],
            logs / "export.log", "Re-run `ns-export gaussian-splat --help` to check flags.")
    plys = sorted(splat.glob("*.ply"))
    if not plys:
        raise PipelineError(f"No .ply exported to {splat}", "See logs/export.log.")
    ply = out / "splat.ply"; shutil.copy(plys[0], ply)

    rep = {**reg, "iterations": t["iterations"], "matcher": c["matcher"], "gaussian_count": ply_vertex_count(ply),
           "colmap_seconds": round(t_colmap, 1), "train_seconds": round(t_train, 1),
           "ply_mb": round(ply.stat().st_size / 1e6, 2), "metrics": eval_metrics(cfg_path, out)}
    (out / "reconstruct_report.json").write_text(json.dumps(rep, indent=2))
    log.info("Registered %d/%d (%.0f%%), %d Gaussians", reg["images_registered"], n_in,
             reg["registration_rate"] * 100, rep["gaussian_count"])
    return rep

def run(cfg: dict, out: Path, inputs: list[Path]) -> dict:
    """Stage entry point."""
    r = reconstruct(cfg, out)
    return {k: r[k] for k in ("registration_rate", "images_registered", "gaussian_count", "colmap_seconds", "train_seconds", "ply_mb")}
