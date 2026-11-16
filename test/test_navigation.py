"""test_navigation.py: Unit tests and benchmarks for Python A* navigation core."""
from __future__ import annotations
import json
import math
import time
from pathlib import Path
import pytest
from navigation import GridNav, check_line_of_sight, find_path, smooth_path

def create_synthetic_collision(
    grid_cells: list[list[int]], cell_size: float = 0.1, origin: tuple[float, float] = (0.0, 0.0)
) -> dict:
    """Helper to create a collision_doc from a 2D array of cells (rows = Z, cols = X)."""
    nz = len(grid_cells)
    nx = len(grid_cells[0])
    flat = []
    for row in grid_cells:
        flat.extend(row)
    return {
        "version": 1,
        "size": [nx, nz],
        "cell_size": cell_size,
        "origin": list(origin),
        "inflated": flat,
        "grid": flat,
    }

def test_straight_path():
    # 5x5 open grid, all floor (1)
    grid = [[1] * 5 for _ in range(5)]
    doc = create_synthetic_collision(grid)
    res = find_path(doc, [0.05, 0.05], [0.35, 0.05])
    assert res["ok"] is True
    assert len(res["cells"]) == 4
    assert res["cost"] == pytest.approx(3.0, abs=1e-6)

def test_detour_around_obstacle():
    # 5x5 grid with obstacle in middle:
    # 1 1 1 1 1
    # 1 1 0 1 1
    # 1 1 0 1 1
    # 1 1 0 1 1
    # 1 1 1 1 1
    grid = [[1] * 5 for _ in range(5)]
    for z in range(1, 4):
        grid[z][2] = 2  # blocked
    doc = create_synthetic_collision(grid)
    # Start at (0, 2), goal at (4, 2)
    start = [0.05, 0.25]
    goal = [0.45, 0.25]
    res = find_path(doc, start, goal)
    assert res["ok"] is True
    # The path must detour around the obstacle (no cell in the path can be x=2 for z in [1,3])
    for ix, iz in res["cells"]:
        assert not (ix == 2 and 1 <= iz <= 3)

def test_gap_in_wall():
    # Wall with single gap at z=2:
    # 1 1 0 1 1
    # 1 1 0 1 1
    # 1 1 1 1 1  <- gap
    # 1 1 0 1 1
    # 1 1 0 1 1
    grid = [[1] * 5 for _ in range(5)]
    for z in [0, 1, 3, 4]:
        grid[z][2] = 2
    doc = create_synthetic_collision(grid)
    res = find_path(doc, [0.05, 0.05], [0.45, 0.45])
    assert res["ok"] is True
    # Path must pass through gap at (2, 2)
    assert (2, 2) in res["cells"]

def test_unreachable_goal():
    # Goal enclosed in walls:
    # 1 1 1 1 1
    # 1 2 2 2 1
    # 1 2 1 2 1  <- (2, 2) is isolated
    # 1 2 2 2 1
    # 1 1 1 1 1
    grid = [[1] * 5 for _ in range(5)]
    for r in range(1, 4):
        for c in range(1, 4):
            grid[r][c] = 2
    grid[2][2] = 1  # island
    doc = create_synthetic_collision(grid)
    res = find_path(doc, [0.05, 0.05], [0.25, 0.25], snap_radius_m=0.05)
    assert res["ok"] is False
    assert "No walkable path" in res["reason"]

def test_start_goal_in_blocked_cell_snapped():
    # 5x5 open grid, start/goal in blocked cells at borders, snapped to walkable
    grid = [[1] * 5 for _ in range(5)]
    grid[0][0] = 2
    grid[4][4] = 2
    doc = create_synthetic_collision(grid)
    res = find_path(doc, [0.05, 0.05], [0.45, 0.45], snap_radius_m=0.3)
    assert res["ok"] is True
    assert res["snap_start_dist"] > 0
    assert res["snap_goal_dist"] > 0

def test_no_diagonal_corner_cutting():
    # 3x3 grid:
    # S = (0, 0), G = (1, 1)
    # Walls at (1, 0) and (0, 1)
    # 1 2 1
    # 2 1 1
    # 1 1 1
    grid = [
        [1, 2, 1],
        [2, 1, 1],
        [1, 1, 1],
    ]
    doc = create_synthetic_collision(grid)
    # Direct diagonal step from (0,0) to (1,1) is disallowed because (1,0) and (0,1) are walls.
    # The only valid path must not cut through the corner directly;
    # Since (0,0) is surrounded by walls (1,0) and (0,1) and bounds, it is completely trapped!
    res = find_path(doc, [0.05, 0.05], [0.15, 0.15], snap_radius_m=0.05)
    assert res["ok"] is False

def test_smoothing_never_longer_and_has_los():
    # Test on real scene collision
    scene_col_path = Path(__file__).resolve().parent.parent / "viewer" / "public" / "scene" / "collision.json"
    doc = json.loads(scene_col_path.read_text(encoding="utf-8"))
    res = find_path(doc, [0.65, -4.25], [3.5, -4.5])
    assert res["ok"] is True
    assert res["length"] <= res["raw_length"] + 1e-5
    # Verify line of sight on all smoothed segments
    g = GridNav(doc)
    wps = res["waypoints"]
    for i in range(1, len(wps)):
        assert check_line_of_sight(g, wps[i - 1][0], wps[i - 1][1], wps[i][0], wps[i][1])

def test_real_grid_and_synthetic_300x300_benchmark():
    # 1. Real scene collision benchmark
    scene_col_path = Path(__file__).resolve().parent.parent / "viewer" / "public" / "scene" / "collision.json"
    doc = json.loads(scene_col_path.read_text(encoding="utf-8"))
    t0 = time.perf_counter()
    res_real = find_path(doc, [0.65, -4.25], [3.5, -4.5])
    t_real_ms = (time.perf_counter() - t0) * 1000.0
    assert res_real["ok"] is True

    # 2. Synthetic 300x300 grid benchmark with obstacles
    grid_300 = [[1] * 300 for _ in range(300)]
    # Add scattered wall columns
    for z in range(50, 250):
        grid_300[z][100] = 2
        grid_300[z][200] = 2
    # Open passages
    grid_300[150][100] = 1
    grid_300[150][200] = 1

    doc_300 = create_synthetic_collision(grid_300, cell_size=0.1)
    t0 = time.perf_counter()
    res_300 = find_path(doc_300, [1.0, 15.0], [25.0, 15.0])
    t_300_ms = (time.perf_counter() - t0) * 1000.0
    assert res_300["ok"] is True

    print(f"\n[BENCHMARK] Python A* real scene grid: {t_real_ms:.2f} ms")
    print(f"[BENCHMARK] Python A* synthetic 300x300 grid: {t_300_ms:.2f} ms")
