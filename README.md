# Roomscape

Roomscape turns a phone walkthrough video into a metric-scaled 3D Gaussian-splat scene that can be explored in a browser.

## Quick start

The reconstruction stage uses Nerfstudio and CUDA. Use a Linux machine with an NVIDIA GPU for a real reconstruction; the CPU mock runs the complete pipeline with synthetic reconstruction data.

```bash
# 1. Create the video/COLMAP environment (Python 3.10, FFmpeg, COLMAP, base dependencies).
bash scripts/setup_env.sh
conda activate namma-space

# 2. Install the CUDA-matched PyTorch build, then Nerfstudio, following the official
#    installation guide for your driver/CUDA combination: https://docs.nerf.studio/quickstart/installation.html
pip install nerfstudio

# 3. Check the environment, then reconstruct a video.
python scripts/check_gpu.py
python pipeline/run_pipeline.py --video /path/to/walkthrough.mp4 --out ./roomscape-output --mode fast

# CPU-only end-to-end pipeline check (does not invoke COLMAP or train a real model).
python pipeline/run_pipeline.py --video /path/to/walkthrough.mp4 --out ./roomscape-mock --mode fast --mock
```

The extraction stage writes selected frames to `<out>/frames/`. Nerfstudio's `ns-process-data images` consumes that folder and writes camera transforms under `<out>/ns_data/`; reconstruction exports `<out>/splat.ply` for alignment and later stages. Successful exports are copied to `viewer/public/scene/`.

## Requirements

- Linux is the supported target for GPU reconstruction. Install NVIDIA drivers and a CUDA-enabled PyTorch build compatible with your driver before installing Nerfstudio.
- For a real `splatfacto` run, use an NVIDIA GPU with at least 8 GB VRAM; 12 GB or more is recommended for 4K source footage and quality mode. Fast mode downsizes images to 1920 px and trains for 7,000 iterations; quality mode uses up to 500 frames and 30,000 iterations.
- FFmpeg, COLMAP, Python 3.10, OpenCV-contrib, NumPy, PyYAML, Matplotlib, and Nerfstudio are required. `scripts/setup_env.sh` installs the Conda/base environment. Nerfstudio and CUDA-specific PyTorch are installed separately to avoid selecting an incompatible CUDA wheel.
- Browser viewer requires a current WebGL2-capable browser.

## Capture and run

Follow [docs/SOP.md](docs/SOP.md) for lighting, camera settings, and a repeatable walkthrough. A typical run is:

```bash
python pipeline/run_pipeline.py --video /path/to/clip.mp4 --out ./roomscape-output --mode fast
```

Use `--mode quality` for a longer training run. Use `--resume` after an interruption; completed stages are skipped and reconstruction reuses available COLMAP/training outputs. Use `--frames N`, `--trim-start SEC`, and `--trim-end SEC` to adjust extraction, or `--no-gpu` to disable GPU use by COLMAP (Nerfstudio training still needs CUDA). The command writes `report.json` and `report.md` in the output folder. Failures include the stage, exception traceback, captured process output, and a suggested fix.

## Viewer

```bash
cd viewer
npm ci
npm run dev
```

Open the local Vite URL. Click the scene to capture the mouse; use WASD and the mouse to move/look, Shift to sprint, H or `?` for help, R or **Reset** to return to spawn, and F to toggle FPS. The minimap displays the collision grid. Build a static viewer with `npm run build`.

See [docs/DEPLOY.md](docs/DEPLOY.md) for hosting and scene URL configuration. See [CREDITS.md](CREDITS.md) for third-party licenses and [LICENSE](LICENSE) for this repository's license.
