# Roomscape: Metric 3D Gaussian Digital Twin with Semantic POI Search & Obstacle-Aware Navigation

**Competition**: Techfest IIT Bombay 2026-27 — Namma Space Challenge  
**Team**: Roomscape Project  
**Keywords**: 3D Gaussian Splatting, Spatial AI, Indoor Navigation, A* Pathfinding, Digital Twin, WebGL  

---

## Abstract

Indoor navigation in complex built environments requires high visual fidelity, metric accuracy, and real-time obstacle avoidance, yet traditional photogrammetry meshes are either computationally prohibitive for mobile web clients or lack the semantic understanding necessary for wayfinding. In this work, we present **Roomscape**, a complete end-to-end spatial computing pipeline that transforms a standard monocular smartphone video into a metric-scaled 3D Gaussian Splatting (3DGS) digital twin accessible within any modern WebGL2 web browser.

Our system introduces three technical innovations:
1. **Automated Metric Scale & Floor Extraction**: Utilizing COLMAP Structure-from-Motion and Nerfstudio's `splatfacto` model, our pipeline automatically recovers metric scale via calibrated AprilTag marker triangulation (with camera height fallback) and establishes a gravity-aligned floor frame ($Y=0$) through RANSAC plane fitting.
2. **2D Discrete Obstacle Proxy**: We extract a 2D occupancy grid directly from the aligned 3D Gaussian point cloud within the human traversal band ($0.15\text{--}1.8\text{ m}$), subsequently dilated by an agent radius ($0.25\text{ m}$) to yield a robust navigation proxy without expensive 3D mesh reconstruction.
3. **Semantic Discovery & Real-Time Navigation (Round 2)**: We introduce an interactive spatial navigation runtime featuring:
   - Line-of-sight wall-occluded POI label projection that prevents labels from bleeding through physical partitions.
   - A pure fuzzy search engine supporting typo-tolerant Levenshtein ranking with keyboard-first modal navigation.
   - A zero-allocation TypeScript 8-connected A* planner enforcing strict corner-clearance constraints and line-of-sight path smoothing that computes optimal trajectories in under $1\text{ ms}$.
   - Guided auto-walk traversal leveraging collision slide physics, dynamic ETA calculation, and off-path automatic rerouting.

The complete system is cross-platform, requires zero proprietary GPU runtimes on the client, and includes an interactive in-browser authoring tool (`?edit=1`) for venue operators. Roomscape represents a practical bridge between photorealistic spatial capture and practical indoor mobility.
