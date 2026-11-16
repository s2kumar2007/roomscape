# Roomscape Proof-of-Concept (PoC) Web Viewer

The Roomscape Web Viewer is a zero-install, browser-based 3D digital twin explorer built on WebGL2, Three.js, and Spark 3D Gaussian Splatting.

---

## 1. Core Architecture

The viewer loads three primary artifacts produced by the reconstruction pipeline:
1. **`scene.splat`**: 3D Gaussian splat point cloud (compressed, 32 bytes/Gaussian, containing position, scale, rotation, and RGB color).
2. **`meta.json`**: Scene bounds, spawn position and yaw, metric scaling confidence, eye height, and walk/run speeds.
3. **`collision.json`**: 2D discrete occupancy grid with floor and obstacle labels, dilated by the agent radius ($0.25\text{ m}$) into an obstacle map.
4. **`poi.json`** *(Round 2)*: Points of Interest with names, categories, descriptions, aliases, and 2D metric coordinates.

```
       [scene.splat]           [meta.json]           [collision.json]         [poi.json]
             │                      │                       │                      │
             ▼                      ▼                       ▼                      ▼
      SparkGSplatMesh       FirstPersonControls        CollisionMap            POIManager
             │                      │                       │                      │
             └──────────────┬───────┴───────────────┬───────┴──────────────────────┘
                            │                       │
                            ▼                       ▼
                    Three.js Viewport        A* Path Planner
                   (WebGL2 60+ FPS)      (Obstacle-Aware Routing)
```

---

## 2. Interaction & Navigation Capabilities

- **First-Person Camera**: Desktop mouse-look with pointer lock; WASD movement with wall collision and slide physics.
- **Mobile Touch Controls**: Dynamic on-screen joystick for movement, right-side touch dragging for look orientation.
- **2D Real-Time Minimap**: Canvas overlay rendering the walkable floor area, obstacles, player position cone, and active route polyline.
- **Semantic POI Overlay**: Projective 3D-to-2D labels with distance fading and real-time line-of-sight wall occlusion.
- **Fuzzy Search Modal**: Triggered by `/`; keyboard arrow navigation, instant match ranking, and single-click route planning.
- **Guided Auto-Walk**: Automated avatar navigation along smoothed A* paths with dynamic speed regulation and obstacle avoidance.
- **Interactive POI Authoring (`?edit=1`)**: In-browser floor crosshair raycaster allowing users to place, test, and export `poi.json` without backend services.

---

## 3. Performance & Resource Budgets

| Metric | Target | Measured (Real Scene) | Measured (Headless CI / SwiftShader) |
|---|---|---|---|
| Framerate (Desktop GPU) | $\ge 60\text{ FPS}$ | $60\text{ FPS}$ (V-Sync) | $20\text{--}35\text{ FPS}$ (Software WebGL) |
| Initial Load Time | $\le 2.0\text{ s}$ | $0.41\text{ s}$ | $0.85\text{ s}$ |
| A* Path Computation | $\le 5.0\text{ ms}$ | $0.54\text{ ms}$ | $0.87\text{ ms}$ |
| Search Latency | $\le 10\text{ ms}$ | $< 1.0\text{ ms}$ | $< 1.0\text{ ms}$ |
| Memory Footprint | $\le 150\text{ MB}$ | $\sim 78\text{ MB}$ | $\sim 92\text{ MB}$ |

---

## 4. Browser & Hardware Compatibility

- **Desktop**: Chrome 110+, Edge 110+, Firefox 115+, Safari 16.4+ (WebGL2 required).
- **Mobile**: Android Chrome, iOS Safari (iOS 16+).
- **GPU Tier**: Integrated Intel Iris Xe, Apple Silicon M1+, NVIDIA GTX 1050+ or better.
