"""Phase 3: camera poses (COLMAP via Nerfstudio) + Gaussian splat training (splatfacto/gsplat).

Docs-verified CLI (Nerfstudio):
  ns-process-data images --data D --output-dir O --matching-method {exhaustive,sequential,vocab_tree}
  ns-train splatfacto --data O --max-num-iterations N
  ns-export gaussian-splat --load-config config.yml --output-dir X
Nerfstudio's COLMAP wrapper uses ONE shared camera model for all images (right for one phone).
Flags change between releases, so we also check `--help` output at runtime and warn on mismatch.
"""
from __future__ import annotations
import json, os, re, shutil, subprocess, sys, time
from pathlib import Path
import numpy as np
from gsplat_io import write_gs_ply, SH_C0
from utils import PipelineError, get_logger

# Ensure Qt platform is offscreen for headless environments (prevents COLMAP Qt crashes)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

log = get_logger()
TOOLS = {
    "ns-process-data": "pip install nerfstudio  (see https://docs.nerf.studio/quickstart/installation.html)",
    "ns-train": "pip install nerfstudio",
    "ns-export": "pip install nerfstudio",
    "colmap": "conda install -c conda-forge colmap (or apt-get install colmap)",
    "ffmpeg": "conda install -c conda-forge ffmpeg (or apt-get install ffmpeg)",
}

def check_gpu() -> dict:
    """Validate GPU availability, device name, and VRAM via PyTorch and nvidia-smi."""
    gpu_info = {
        "cuda_available": False,
        "device_name": None,
        "vram_total_gb": None,
        "vram_free_gb": None,
        "diagnostic": None,
    }
    try:
        import torch
        if torch.cuda.is_available():
            gpu_info["cuda_available"] = True
            gpu_info["device_name"] = torch.cuda.get_device_name(0)
            props = torch.cuda.get_device_properties(0)
            gpu_info["vram_total_gb"] = round(props.total_memory / (1024**3), 2)
            try:
                free_b, _ = torch.cuda.mem_get_info(0)
                gpu_info["vram_free_gb"] = round(free_b / (1024**3), 2)
            except Exception:
                gpu_info["vram_free_gb"] = gpu_info["vram_total_gb"]
            log.info("GPU detected: %s (VRAM: %.2f GB total, %.2f GB free)",
                     gpu_info["device_name"], gpu_info["vram_total_gb"], gpu_info["vram_free_gb"])
        else:
            log.warning("torch.cuda.is_available() is False: splat training requires an NVIDIA GPU with CUDA.")
    except Exception as e:  # noqa: BLE001
        gpu_info["diagnostic"] = f"PyTorch GPU check failed: {type(e).__name__}: {e}"
        log.warning("%s", gpu_info["diagnostic"])

    if not shutil.which("nvidia-smi"):
        log.warning("nvidia-smi not found in PATH: splat training requires an NVIDIA GPU (or use the Colab notebook).")
    return gpu_info

def _is_headless_linux() -> bool:
    """Return whether Linux lacks a display server for COLMAP's OpenGL SIFT path."""
    return sys.platform.startswith("linux") and not (
        os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
    )

def validate_environment(mock: bool = False) -> dict:
    """Validate that required binaries and GPU environment are ready.
    
    If mock=True, skips tool existence checks to allow running on CPU-only test environments.
    """
    gpu_info = check_gpu()
    if mock:
        log.info("Mock/dry-run mode enabled: skipping binary preflight checks.")
        return {"tools_ok": True, "gpu": gpu_info, "mock": True}

    missing = [f"{t}  ->  {fix}" for t, fix in TOOLS.items() if not shutil.which(t)]
    if missing:
        raise PipelineError(
            "Missing required tools in PATH:\n  " + "\n  ".join(missing),
            "Install missing tools (e.g., conda install -c conda-forge colmap ffmpeg; pip install nerfstudio), or use notebooks/colab_reconstruct.ipynb, or run with --mock / --dry-run."
        )
    return {"tools_ok": True, "gpu": gpu_info, "mock": False}

def require_training_gpu(gpu_info: dict) -> None:
    """Fail before COLMAP/training work if a real splat training run cannot use CUDA."""
    if gpu_info.get("cuda_available"):
        return
    detail = gpu_info.get("diagnostic") or "torch.cuda.is_available() returned False"
    name = gpu_info.get("device_name") or "no CUDA device detected"
    vram = gpu_info.get("vram_total_gb")
    suffix = f"; detected VRAM: {vram} GB" if vram is not None else ""
    raise PipelineError(
        f"Cannot start Nerfstudio training: {detail} ({name}{suffix}).",
        "Install a CUDA-enabled PyTorch/Nerfstudio build and NVIDIA drivers, or use --mock/--dry-run for a CPU pipeline check.",
    )

def preflight(mock: bool = False) -> dict:
    """Pre-flight check alias for backward compatibility."""
    return validate_environment(mock=mock)

def check_flags(cmd: list[str], needed: list[str]) -> None:
    """Warn (not fail) if expected flags are absent from `<cmd> --help`: the CLI may have changed."""
    resolved = shutil.which(cmd[0])
    if not resolved:
        log.warning("Could not find executable for %s", cmd[0])
        return
    exec_cmd = cmd
    if sys.platform == "win32" and resolved.lower().endswith((".bat", ".cmd")):
        exec_cmd = [os.environ.get("COMSPEC", "cmd.exe"), "/c", resolved] + cmd[1:]
    try:
        txt = subprocess.run(exec_cmd + ["--help"], capture_output=True, text=True, timeout=120)
        txt = txt.stdout + txt.stderr
    except Exception as e:  # noqa: BLE001
        log.warning("Could not read help for %s (%s)", " ".join(cmd), e); return
    for f in needed:
        if f not in txt:
            log.warning("Flag %s not found in `%s --help`; Nerfstudio CLI may have changed. Check docs.nerf.studio.", f, " ".join(cmd))

def run_cmd(cmd: list[str], logfile: Path, fix: str) -> subprocess.CompletedProcess:
    """Run a subprocess, stream output and stderr to console + logfile, and raise on failure."""
    log.info("$ %s", " ".join(cmd))
    logfile.parent.mkdir(parents=True, exist_ok=True)
    resolved = shutil.which(cmd[0])
    if not resolved:
        raise PipelineError(f"Command not found: {cmd[0]}", fix)
    exec_cmd = cmd
    if sys.platform == "win32" and resolved.lower().endswith((".bat", ".cmd")):
        exec_cmd = [os.environ.get("COMSPEC", "cmd.exe"), "/c", resolved] + cmd[1:]

    try:
        res = subprocess.run(exec_cmd, capture_output=True, text=True, check=True)
        if res.stdout:
            for line in res.stdout.splitlines():
                log.info("  | %s", line)
        if res.stderr:
            for line in res.stderr.splitlines():
                log.warning("  stderr: %s", line)
        with open(logfile, "a", encoding="utf-8") as lf:
            if res.stdout: lf.write(res.stdout + "\n")
            if res.stderr: lf.write(res.stderr + "\n")
        return res
    except subprocess.CalledProcessError as e:
        # Log stderr directly to console and logfile
        if e.stdout:
            for line in e.stdout.splitlines():
                log.info("  | %s", line)
        if e.stderr:
            log.error("Command '%s' stderr:\n%s", cmd[0], e.stderr)
            for line in e.stderr.splitlines():
                log.error("  ! %s", line)
        with open(logfile, "a", encoding="utf-8") as lf:
            if e.stdout: lf.write(e.stdout + "\n")
            if e.stderr: lf.write(e.stderr + "\n")
        err_detail = e.stderr.strip() or e.stdout.strip() or f"Exit code {e.returncode}"
        raise PipelineError(f"`{cmd[0]}` failed (exit {e.returncode}). Last output:\n{err_detail}", fix) from e
    except FileNotFoundError as e:
        raise PipelineError(f"Command not found: {cmd[0]}", fix) from e

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

def _generate_mock_splat(ply_path: Path, n_points: int = 12000) -> int:
    """Generate a valid 3D Gaussian Splatting PLY room for mock / dry-run testing."""
    rng = np.random.default_rng(42)
    W, D, H = 6.0, 4.0, 2.6
    nf = n_points // 3
    pts = [np.c_[rng.uniform(0, W, nf), np.zeros(nf), rng.uniform(0, D, nf)]]  # floor y=0
    nc = n_points // 6
    pts.append(np.c_[rng.uniform(0, W, nc), np.full(nc, H), rng.uniform(0, D, nc)])  # ceiling
    nw = n_points // 8
    pts.append(np.c_[rng.uniform(0, W, nw), rng.uniform(0, H, nw), np.zeros(nw)])
    pts.append(np.c_[rng.uniform(0, W, nw), rng.uniform(0, H, nw), np.full(nw, D)])
    pts.append(np.c_[np.zeros(nw), rng.uniform(0, H, nw), rng.uniform(0, D, nw)])
    pts.append(np.c_[np.full(nw, W), rng.uniform(0, H, nw), rng.uniform(0, D, nw)])
    nt = n_points // 10
    pts.append(np.c_[rng.uniform(2, 3.2, nt), np.full(nt, 0.75), rng.uniform(1.5, 2.3, nt)])  # table
    xyz = np.vstack(pts)
    n = len(xyz)
    col = rng.uniform(0.3, 0.8, (n, 3))
    d = {
        "xyz": xyz,
        "dc": (col - 0.5) / SH_C0,
        "rest": np.zeros((n, 3, 3)),
        "opacity": np.full(n, 3.0),
        "scale": np.full((n, 3), np.log(0.02)),
        "rot": np.tile([1.0, 0.0, 0.0, 0.0], (n, 1)),
    }
    write_gs_ply(ply_path, d, sh_degree=1)
    return n

def mock_reconstruct(cfg: dict, out: Path) -> dict:
    """Execute mock reconstruction on CPU without GPU for pipeline testing and verification."""
    frames = out / "frames"
    frame_files = sorted({p.resolve() for ext in ("*.jpg", "*.jpeg", "*.png") for p in frames.glob(ext)})
    n_in = len(frame_files)
    if n_in == 0:
        raise PipelineError(f"No frames in {frames}", "Run the extract_frames stage first.")

    log.info("[MOCK] Running mock reconstruction for %d input frames on CPU...", n_in)
    data, train, splat = out / "ns_data", out / "train", out / "splat"
    data.mkdir(parents=True, exist_ok=True)
    train.mkdir(parents=True, exist_ok=True)
    splat.mkdir(parents=True, exist_ok=True)
    (out / "logs").mkdir(parents=True, exist_ok=True)

    # 1. Mock transforms.json with cameras walking at height y=1.4m
    cam_frames = []
    for i, f in enumerate(frame_files):
        a = i / max(len(frame_files) - 1, 1)
        pos = np.array([1.0 + 4.0 * a, 1.4, 2.0])
        R = np.eye(3)
        c2w = np.vstack([np.c_[R, pos], [0, 0, 0, 1]])
        cam_frames.append({
            "file_path": f"../frames/{f.name}",
            "transform_matrix": c2w.tolist(),
        })
    tj = {
        "fl_x": 1000.0, "fl_y": 1000.0, "cx": 640.0, "cy": 360.0, "w": 1280, "h": 720,
        "frames": cam_frames,
    }
    (data / "transforms.json").write_text(json.dumps(tj, indent=2))
    (out / "logs" / "colmap.log").write_text("Mock COLMAP completed successfully (CPU dry-run).\n")

    # 2. Mock train output
    cfg_dir = train / "scene" / "splatfacto" / "run"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.yml").write_text("# Mock splatfacto config\n")
    (out / "logs" / "train.log").write_text("Mock splatfacto training completed (CPU dry-run).\n")

    # 3. Mock Gaussian splat PLY
    ply = out / "splat.ply"
    n_pts = _generate_mock_splat(ply)
    shutil.copy(ply, splat / "splat.ply")
    (out / "logs" / "export.log").write_text(f"Mock export completed: {n_pts} Gaussians.\n")

    t_cfg = cfg.get("train", {})
    iterations = t_cfg.get("iterations", 7000)
    rep = {
        "images_input": n_in,
        "images_registered": n_in,
        "registration_rate": 1.0,
        "iterations": iterations,
        "matcher": "mock",
        "mock": True,
        "gaussian_count": n_pts,
        "colmap_seconds": 0.1,
        "train_seconds": 0.1,
        "ply_mb": round(ply.stat().st_size / 1e6, 2),
        "metrics": {},
    }
    (out / "reconstruct_report.json").write_text(json.dumps(rep, indent=2))
    log.info("[MOCK] Reconstruction complete: %d/%d registered, %d Gaussians", n_in, n_in, n_pts)
    return rep

def reconstruct(cfg: dict, out: Path) -> dict:
    is_mock = bool(cfg.get("_mock") or cfg.get("_dry_run") or cfg.get("mock") or cfg.get("reconstruct", {}).get("mock"))
    if is_mock:
        preflight(mock=True)
        return mock_reconstruct(cfg, out)

    env = preflight(mock=False)
    require_training_gpu(env["gpu"])
    frames = out / "frames"
    frame_files = sorted({p.resolve() for ext in ("*.jpg", "*.jpeg", "*.png") for p in frames.glob(ext)})
    n_in = len(frame_files)
    if n_in == 0:
        raise PipelineError(f"No frames in {frames.resolve()}", "Run the extract_frames stage first.")

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
        colmap_cmd = [
            "ns-process-data", "images",
            "--data", str(frames.resolve()),
            "--output-dir", str(data.resolve()),
            "--matching-method", c["matcher"],
        ]
        if not c.get("use_gpu", True):
            colmap_cmd.append("--no-gpu")
        elif _is_headless_linux():
            # COLMAP's CUDA SIFT path may still require an OpenGL context, which
            # is unavailable in headless Colab/CI/Linux sessions.
            log.info("Headless Linux detected; selecting CPU SIFT to avoid COLMAP OpenGL context failure.")
            colmap_cmd.append("--no-gpu")
        try:
            run_cmd(colmap_cmd, logs / "colmap.log",
                    "Check COLMAP installs (`colmap -h`). Try matcher=exhaustive in config.yaml, or capture per docs/SOP.md.")
        except PipelineError as e:
            # Headless Linux / Colab without OpenGL X11 context crashes with context_.create()
            if "--no-gpu" not in colmap_cmd and any(k in str(e) for k in ("context_.create()", "opengl_utils", "Check failed: context_", "OpenGL", "SiftExtraction.use_gpu")):
                log.warning("COLMAP OpenGL/GPU SIFT failed because headless Linux lacks an OpenGL display context. Automatically falling back to CPU SIFT (--no-gpu)...")
                colmap_fallback_cmd = list(colmap_cmd) + ["--no-gpu"]
                run_cmd(colmap_fallback_cmd, logs / "colmap.log",
                        "COLMAP failed on CPU as well. Check COLMAP installs (`colmap -h`) or capture per docs/SOP.md.")
            else:
                raise
    t_colmap = time.perf_counter() - t0
    reg = registration_stats(data, n_in)
    check_registration(reg, c["min_registration_rate"])

    t0 = time.perf_counter()
    if resume and list(train.rglob("config.yml")):
        log.info("Reusing existing training run in %s", train)
    else:
        check_flags(["ns-train", "splatfacto"], ["--max-num-iterations", "--data"])
        run_cmd([
            "ns-train", t["method"],
            "--data", str(data.resolve()),
            "--max-num-iterations", str(t["iterations"]),
            "--output-dir", str(train.resolve()),
            "--viewer.quit-on-train-completion", "True",
        ], logs / "train.log", "CUDA out of memory? Use fast mode, fewer frames, or the Colab notebook. See logs/train.log.")
    t_train = time.perf_counter() - t0
    cfg_path = latest_config(train)

    run_cmd([
        "ns-export", "gaussian-splat",
        "--load-config", str(cfg_path.resolve()),
        "--output-dir", str(splat.resolve()),
    ], logs / "export.log", "Re-run `ns-export gaussian-splat --help` to check flags.")
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
