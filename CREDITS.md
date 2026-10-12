# Credits

| Library | Licence | Use |
|---|---|---|
| Nerfstudio | Apache-2.0 | Data processing (COLMAP wrapper), `splatfacto` training, export |
| gsplat | Apache-2.0 | Gaussian rasterization backend used by Nerfstudio |
| COLMAP | BSD-3-Clause | Structure-from-Motion camera poses |
| OpenCV | Apache-2.0 (4.5+) | Frame extraction, sharpness scoring, marker detection |
| NumPy | BSD-3-Clause | Numerics |
| PyYAML | MIT | Config loading |
| pytest | MIT | Tests |
| Three.js | MIT | 3D rendering in the viewer |
| Spark (@sparkjsdev/spark) | MIT | Gaussian splat renderer for Three.js |
| Vite / Vitest / TypeScript | MIT / MIT / Apache-2.0 | Viewer build, tests, typing |
| Matplotlib | PSF-based (BSD-compatible) | Debug plots |
| Playwright | Apache-2.0 | Viewer health check |
| FFmpeg | LGPL/GPL (used as external CLI only) | Video codec support |

**Avoided on purpose:** `plyfile` (GPL-3.0) is NOT used; PLY I/O is implemented in `pipeline/gsplat_io.py`.
Licences listed from the projects' published terms; re-verify against each repo in Phase 12.

**Not used:** the original Inria 3D Gaussian Splatting reference code (non-commercial licence).
