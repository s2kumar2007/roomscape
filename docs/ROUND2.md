# Round 2: Obstacle-Aware Navigation & Semantic POI Exploration

Roomscape Round 2 enhances the metric 3D Gaussian splat digital twin with interactive Point of Interest (POI) discovery, fuzzy search, and obstacle-aware A* pathfinding.

---

## 1. System Architecture

```
                                  [poi.json]
                                       │
                                       ▼
                             ┌───────────────────┐
                             │    POI Manager    │
                             │ (load/snap/cull)  │
                             └─────────┬─────────┘
                                       │
                   ┌───────────────────┼───────────────────┐
                   ▼                   ▼                   ▼
         ┌───────────────────┐ ┌───────────────┐ ┌───────────────────┐
         │ 3D World Markers  │ │  DOM Overlay  │ │   Search Engine   │
         │ (Cylinder Pins)   │ │  (LOS Occluded)│ │  (Levenshtein <=2)│
         └───────────────────┘ └───────┬───────┘ └─────────┬─────────┘
                                       │                   │
                                       ▼                   ▼
                             ┌───────────────────────────────┐
                             │       User Selects POI        │
                             └───────────────┬───────────────┘
                                             ▼
                               ┌───────────────────────────┐
                               │     A* Path Planner       │
                               │  (8-conn, no corner cut)  │
                               └─────────────┬─────────────┘
                                             ▼
                               ┌───────────────────────────┐
                               │   LOS Path Smoothing      │
                               │  (never longer than raw)  │
                               └─────────────┬─────────────┘
                                             ▼
                               ┌───────────────────────────┐
                               │     Navigator Engine      │
                               │ (idle -> routing -> arrived)│
                               └─────────────┬─────────────┘
                                             ▼
                   ┌─────────────────────────┴─────────────────────────┐
                   ▼                                                   ▼
         ┌───────────────────┐                               ┌───────────────────┐
         │ 3D Instanced Discs│                               │  Minimap Polyline │
         │  (renderOrder 999)│                               │ (Sync Canvas 2D)  │
         └───────────────────┘                               └───────────────────┘
```

---

## 2. POI Specification (`poi.json`)

### File Location and Schema
`poi.json` lives alongside `meta.json` in `viewer/public/scene/` (or any custom scene URL). It is loaded via `sceneBase()`.

```json
{
  "version": 1,
  "pois": [
    {
      "id": "entrance",
      "name": "Main Entrance",
      "category": "door",
      "aliases": ["exit", "door", "entryway"],
      "position": [0.0, 0.0],
      "description": "Main entrance foyer to the workspace",
      "icon": "door"
    }
  ]
}
```

### Validation & Degradation Rules
1. **Schema Check**: Validated by `scripts/validate_poi.py <poi.json> <collision.json>`. Non-zero exit on structural errors.
2. **Bounds Check**: Every POI's `position` $[x, z]$ must lie within `meta.bounds`.
3. **Walkable Snapping**: The point is snapped to the nearest cell with `inflated == 1` within a $1.0\text{ m}$ radius.
4. **Graceful Degradation**:
   - Any POI outside bounds or $> 1.0\text{ m}$ from walkable space is skipped with a banner (e.g., `"1 POIs ignored"`).
   - If `poi.json` is missing (404), the viewer functions normally without error.
   - Scene exports via `pipeline/export_scene.py` never overwrite or delete user-authored `poi.json`.

---

## 3. A* Pathfinding Algorithm

### Parity Implementations
- **Python reference**: `pipeline/navigation.py`
- **TypeScript engine**: `viewer/src/astar.ts`

Both implementations enforce identical movement rules, heuristics, and tie-breaking:
- **Topology**: 8-neighbour grid over the inflated obstacle map (`inflated == 1`).
- **Cost model**:
  - Orthogonal step: $1.0$ (scaled by grid cell size).
  - Diagonal step: $\sqrt{2} \approx 1.41421356$.
- **Strict No Corner Cutting**:
  A diagonal move from $(x, z)$ to $(x + dx, z + dz)$ is valid **if and only if** both orthogonal neighbours $(x + dx, z)$ and $(x, z + dz)$ are walkable (`inflated == 1`).
- **Octile Heuristic**:
  $$h(dx, dz) = \min(|dx|, |dz|) \cdot \sqrt{2} + (|dx| - |dz|) \cdot 1.0 \quad \text{where } |dx| \ge |dz|$$
- **Data Structure**: Binary min-heap with $O(\log N)$ insertions/extracts and $O(1)$ query counter tracking (zero per-frame memory allocations in TypeScript).
- **Start/Goal Snapping**: If the requested point is inside an obstacle or wall, the algorithm scans outward in expanding concentric Manhattan rings up to $1.5\text{ m}$ to locate the closest walkable cell.
- **Line-of-Sight Path Smoothing**:
  A raycast (Bresenham / DDA over the discrete grid) verifies continuous obstacle clearance between non-adjacent waypoints. Collinear and redundant turns are eliminated without cutting corners, guaranteeing that the smoothed path is never longer than the raw path.

### Measured Performance Benchmarks
| Benchmark Case | Python Reference (`navigation.py`) | TypeScript Engine (`astar.ts`) | Parity Error |
|---|---|---|---|
| Real Scene Grid ($74 \times 81$) | 2.75 ms | 0.54 ms | $< 10^{-6}$ |
| Synthetic Grid ($300 \times 300$) | 7.47 ms | 0.87 ms | $< 10^{-6}$ |
| 25 Fixture Cases (`astar_cases.json`) | PASS | PASS | $0.000000$ |

---

## 4. Navigator State Machine

The navigator manages destination targeting, real-time tracking, ETA updates, and rerouting:

```
               setGoal(start, goal)
        ┌───────────────────────────────────┐
        │                                   │
        ▼                                   │
   ┌─────────┐   Path found            ┌────┴────┐
──>│  IDLE   │────────────────────────>│ ROUTING │
   └─────────┘                         └────┬────┘
        ▲                                   │
        │ Cancel / Esc                      │ dist <= 0.6 m
        │                                   ▼
        └──────────────────────────────┌─────────┐
                                       │ ARRIVED │
                                       └─────────┘
```

- **Update Loop**: Invoked each frame with the player's world position $[x, z]$.
- **Waypoints Tracking**: Advances waypoints as the player reaches within $0.6\text{ m}$ of intermediate nodes.
- **Off-Path Rerouting**: If the player deviates by more than $1.5\text{ m}$ from the active path segment, the navigator automatically recalculates a new path from the current position.
- **Speed & ETA**:
  $$\text{ETA} = \left\lceil \frac{\text{remaining distance}}{\text{walk\_speed}} \right\rceil$$
  Displays an `(approx)` badge if the scene was reconstructed without an AprilTag metric scale marker.
- **Auto-Walk**: When enabled via "Walk me there", the controller automatically moves the player along the path using `CollisionMap.move` collision physics, sliding along walls and preventing any out-of-bounds penetration.

---

## 5. POI Label Overlay & Occlusion

- **3D Projection**: World coordinates are projected to normalized device coordinates (NDC) and positioned as absolute DOM labels.
- **Frustum Culling**: Labels behind the camera ($\vec{v} \cdot \vec{d}_{\text{cam}} \le 0$) are hidden immediately.
- **Distance Attenuation**: Labels fade out between $8\text{ m}$ and $15\text{ m}$.
- **Wall Occlusion**: A discrete 2D raycast on the raw `BLOCKED` grid tests line-of-sight between the camera cell and the POI cell. Labels occluded by intervening walls are hidden so they do not show through partitions.
- **Density Cap**: At most 60 visible labels are displayed at any time, prioritizing the closest points to the camera.

---

## 6. Search System

- **Trigger**: Press `/` without Shift (leaving `?` reserved for Help), or click the "🔍 Search" button in the HUD.
- **Ranking Priority**:
  1. Exact name match (score 1000)
  2. Prefix name match (score 800)
  3. Token / word boundary match (score 600)
  4. Alias match (exact 500, prefix 400)
  5. Category match (score 300)
  6. Fuzzy match (Levenshtein distance $\le 2$, score $100 - 25 \times \text{dist}$)
- **Controls**:
  - `↑` / `↓`: Navigate candidate list
  - `Enter`: Select POI and begin navigation
  - `Esc`: Close search and return to 3D exploration
  - Touch: Tap any search result item

---

## 7. Controls Reference

| Control | Action | Scope |
|---|---|---|
| **Mouse Drag / Click** | Look around (pointer lock) | 3D Viewport |
| **W, A, S, D** | Move forward / left / back / right | 3D Navigation |
| **Shift** | Sprint (run speed) | 3D Navigation |
| **/** | Open POI Search modal | Global |
| **? / H** | Toggle Help and Controls overlay | Global |
| **F** | Toggle FPS and resolution counter | Global |
| **R** | Reset player position to scene entrance | Global |
| **Esc** | Close Search / Cancel active navigation route | Global |
| **Touch Joystick** | Left thumbpad moves, right swipe rotates camera | Mobile / Tablet |
| **?edit=1** | Dev Mode: 'E' to add POI, 'Del' to undo, 'Export' to download | URL Query |

---

## 8. Dev Mode: Interactive POI Authoring

Appending `?edit=1` to the viewer URL activates authoring mode:
1. A 3D cursor ring follows the camera crosshair projected onto the floor plane ($Y = 0$).
2. The cursor turns **green** over walkable areas (`inflated == 1`) and **red** over obstacles.
3. Press **E** to create a POI at the current crosshair.
4. Press **Delete** / **Backspace** to remove the most recently added POI.
5. Click **Export poi.json** in the top-right HUD to validate all entries and trigger an immediate browser-side JSON download. No backend server required.

---

## 9. Known Limitations

- **Software WebGL vs Real GPU**: Headless CI runs using Chromium with SwiftShader (`--use-angle=swiftshader`). Frame rates recorded during software testing ($15\text{--}30\text{ FPS}$) reflect CPU rasterization, whereas native WebGL2 execution on dedicated GPUs easily maintains $\ge 60\text{ FPS}$.
- **Floor Height Assumption**: The current A* grid operates on a single horizontal floor plane ($Y = 0 \pm 0.15\text{ m}$). Multi-story buildings or staircases require multi-layer height grids.
- **Static Collision Representation**: Dynamic obstacles (people moving in the room) are not tracked in real-time; the collision mesh reflects the reconstructed geometry from the source video walkthrough.
