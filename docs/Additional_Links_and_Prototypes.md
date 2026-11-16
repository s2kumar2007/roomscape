# Additional Links and Prototypes

This document compiles external resources, cloud notebooks, repositories, and demonstration references for the Roomscape project (Techfest IIT Bombay, Namma Space Challenge).

---

## 1. Repository & CI Verification

- **GitHub Repository**: [https://github.com/s2kumar2007/roomscape](https://github.com/s2kumar2007/roomscape)
- **Continuous Integration (GitHub Actions)**: Automated 5-stage verification (pytest, vitest, TypeScript check, production build, Playwright headless browser E2E) on Ubuntu runners.
- **Workflow Run Status**: All stages passing on latest `main` branch.

---

## 2. Cloud Reconstruction Notebook (GPU-Accelerated)

For training real 3D Gaussian splats without a local NVIDIA GPU:
- **Google Colab Notebook**: Located in this repo at [`notebooks/reconstruct_colab.ipynb`](file:///C:/Users/K/OneDrive/Documents/namma-space/namma-space/notebooks/reconstruct_colab.ipynb).
- **Environment**: CUDA 11.8 / PyTorch 2.1 / Nerfstudio 1.1 / COLMAP on free or Pro T4/V100 GPU tiers.
- **Usage**:
  1. Upload your phone walkthrough video (`.mp4` / `.mov`).
  2. Run all cells: extracts sharp frames, performs Structure-from-Motion (COLMAP), trains `splatfacto` model (7,000 iterations in fast mode or 30,000 in quality mode).
  3. Automatically runs floor plane RANSAC alignment and AprilTag metric scaling.
  4. Downloads bundled `scene.splat`, `collision.json`, and `meta.json` ready to place in `viewer/public/scene/`.

---

## 3. Video Demonstrations

- **Round 1 Demo**: Highlighting video capture, Structure-from-Motion camera trajectory, floor plane alignment, metric scale recovery, and initial 3D viewer navigation.
- **Round 2 Demo Script**: [`docs/video_script_round2.md`](file:///C:/Users/K/OneDrive/Documents/namma-space/namma-space/docs/video_script_round2.md) covering semantic POIs, wall-occluded labels, fuzzy search modal, obstacle-aware A* routing, and auto-walk guidance.

---

## 4. Prototypes & Future Roadmap (Round 3 AR Bonus)

- **WebXR AR Passthrough**: Prototyping camera feed alignment using device IMU and WebXR hit-testing for real-world 1:1 venue navigation.
- **USDZ / QuickLook Export**: GLB and USDZ model export for zero-install AR previews on iOS Safari and Android Scene Viewer.
- **Dynamic Obstacle Avoidance**: Integrating real-time sensor depth (LiDAR / WebXR Depth API) to dynamically modify the collision grid when people or temporary barriers obstruct paths.
