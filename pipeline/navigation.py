"""navigation.py: 8-connected A* pathfinding and line-of-sight smoothing.

Operates on the inflated collision grid where walkable == 1 (FLOOR).
Rules:
- 8-neighbourhood: cost 1.0 (orthogonal) / sqrt(2) (diagonal).
- NO corner cutting: diagonal moves allowed ONLY if both orthogonal neighbours are walkable.
- Octile distance heuristic: h = max(dx, dz) + (sqrt(2) - 1) * min(dx, dz).
- Priority queue: min-heap (heapq).
- Coordinate snapping: snaps start and goal to the nearest walkable cell within a capped radius.
- Error handling: typed dict return {"ok": False, "reason": str}, never unhandled exceptions.
- Line-of-sight smoothing: string-pulling shortcutting verifying every intersected cell is walkable.
"""
from __future__ import annotations
import heapq
import math
from typing import Any, Sequence

SQRT2 = math.sqrt(2.0)
OCTILE_FACTOR = SQRT2 - 1.0  # ~0.4142135623730951

# 8 directions: (dx, dz, cost, (ortho1_dx, ortho1_dz), (ortho2_dx, ortho2_dz))
# For orthogonal moves, ortho checks are None
NEIGHBORS = [
    # Orthogonal moves (cost 1.0)
    (1, 0, 1.0, None, None),
    (-1, 0, 1.0, None, None),
    (0, 1, 1.0, None, None),
    (0, -1, 1.0, None, None),
    # Diagonal moves (cost sqrt(2)): require both orthogonal components to be walkable
    (1, 1, SQRT2, (1, 0), (0, 1)),
    (1, -1, SQRT2, (1, 0), (0, -1)),
    (-1, 1, SQRT2, (-1, 0), (0, 1)),
    (-1, -1, SQRT2, (-1, 0), (0, -1)),
]

def rle_decode_1d(runs: Sequence[Sequence[int]], total: int) -> list[int]:
    """Decode RLE runs [[val, len], ...] into a 1D list of ints."""
    out: list[int] = []
    for val, length in runs:
        out.extend([val] * length)
    if len(out) != total:
        raise ValueError(f"RLE total {len(out)} != expected {total}")
    return out

class GridNav:
    """Navigation grid decoded from collision.json doc."""

    def __init__(self, doc: dict[str, Any]):
        self.nx: int = int(doc["size"][0])
        self.nz: int = int(doc["size"][1])
        self.cell_size: float = float(doc["cell_size"])
        self.ox: float = float(doc["origin"][0])
        self.oz: float = float(doc["origin"][1])
        total = self.nx * self.nz
        # Walkable iff inflated value == 1 (FLOOR)
        if isinstance(doc["inflated"], list) and len(doc["inflated"]) > 0 and isinstance(doc["inflated"][0], (list, tuple)):
            self.inflated = rle_decode_1d(doc["inflated"], total)
        else:
            self.inflated = list(doc["inflated"])

    def in_bounds(self, ix: int, iz: int) -> bool:
        return 0 <= ix < self.nx and 0 <= iz < self.nz

    def is_walkable(self, ix: int, iz: int) -> bool:
        if not self.in_bounds(ix, iz):
            return False
        return self.inflated[iz * self.nx + ix] == 1

    def cell_to_world(self, ix: int, iz: int) -> tuple[float, float]:
        """Convert cell coords (ix, iz) to cell-centre world coords (x, z)."""
        return (
            self.ox + (ix + 0.5) * self.cell_size,
            self.oz + (iz + 0.5) * self.cell_size,
        )

    def world_to_cell(self, x: float, z: float) -> tuple[int, int]:
        """Convert world coords (x, z) to cell indices (ix, iz)."""
        ix = int(math.floor((x - self.ox) / self.cell_size))
        iz = int(math.floor((z - self.oz) / self.cell_size))
        return ix, iz

    def snap_to_walkable(
        self, x: float, z: float, max_radius_m: float = 1.5
    ) -> tuple[bool, int, int, float]:
        """Find the nearest walkable cell to world (x, z) within max_radius_m.

        Returns: (found, ix, iz, snap_distance_m)
        """
        cx, cz = self.world_to_cell(x, z)
        if self.is_walkable(cx, cz):
            # Already walkable; distance to cell center or 0
            wx, wz = self.cell_to_world(cx, cz)
            dist = math.hypot(x - wx, z - wz)
            return True, cx, cz, dist

        max_cells = int(math.ceil(max_radius_m / self.cell_size))
        best_cell = None
        best_dist_sq = (max_radius_m ** 2)

        for diz in range(-max_cells, max_cells + 1):
            niz = cz + diz
            if niz < 0 or niz >= self.nz:
                continue
            for dix in range(-max_cells, max_cells + 1):
                nix = cx + dix
                if nix < 0 or nix >= self.nx:
                    continue
                if self.inflated[niz * self.nx + nix] == 1:
                    wx, wz = self.cell_to_world(nix, niz)
                    d_sq = (wx - x) ** 2 + (wz - z) ** 2
                    if d_sq <= best_dist_sq:
                        best_dist_sq = d_sq
                        best_cell = (nix, niz)

        if best_cell is not None:
            return True, best_cell[0], best_cell[1], math.sqrt(best_dist_sq)
        return False, -1, -1, float("inf")

def octile_distance(dx: int, dz: int) -> float:
    adx = abs(dx)
    adz = abs(dz)
    return (adx + adz) + OCTILE_FACTOR * min(adx, adz) if adx > adz else (adz + adx) + OCTILE_FACTOR * min(adx, adz)

def octile_heuristic(ix1: int, iz1: int, ix2: int, iz2: int) -> float:
    dx = abs(ix1 - ix2)
    dz = abs(iz1 - iz2)
    if dx < dz:
        return dz + OCTILE_FACTOR * dx
    return dx + OCTILE_FACTOR * dz

def check_line_of_sight(grid: GridNav, x0: float, z0: float, x1: float, z1: float) -> bool:
    """Supercover line-of-sight test between world coords (x0, z0) and (x1, z1).

    Traverses all grid cells intersected by the line segment.
    Returns True iff every intersected cell is walkable.
    """
    # Convert endpoints to continuous cell coordinates
    u0 = (x0 - grid.ox) / grid.cell_size
    v0 = (z0 - grid.oz) / grid.cell_size
    u1 = (x1 - grid.ox) / grid.cell_size
    v1 = (z1 - grid.oz) / grid.cell_size

    ix = int(math.floor(u0))
    iz = int(math.floor(v0))
    ix_end = int(math.floor(u1))
    iz_end = int(math.floor(v1))

    if not grid.is_walkable(ix, iz) or not grid.is_walkable(ix_end, iz_end):
        return False

    du = u1 - u0
    dv = v1 - v0

    step_x = 1 if du > 0 else (-1 if du < 0 else 0)
    step_z = 1 if dv > 0 else (-1 if dv < 0 else 0)

    # Parametric distance to next cell boundary
    if step_x > 0:
        t_max_x = (math.floor(u0) + 1.0 - u0) / du
        t_delta_x = 1.0 / du
    elif step_x < 0:
        t_max_x = (u0 - math.floor(u0)) / (-du)
        t_delta_x = 1.0 / (-du)
    else:
        t_max_x = float("inf")
        t_delta_x = float("inf")

    if step_z > 0:
        t_max_z = (math.floor(v0) + 1.0 - v0) / dv
        t_delta_z = 1.0 / dv
    elif step_z < 0:
        t_max_z = (v0 - math.floor(v0)) / (-dv)
        t_delta_z = 1.0 / (-dv)
    else:
        t_max_z = float("inf")
        t_delta_z = float("inf")

    curr_x = ix
    curr_z = iz

    # Guard against infinite loops with a step budget
    max_steps = (abs(ix_end - ix) + abs(iz_end - iz) + 2) * 2
    steps = 0

    while (curr_x != ix_end or curr_z != iz_end) and steps < max_steps:
        steps += 1
        eps = 1e-9
        if abs(t_max_x - t_max_z) < eps:
            # Traverses corner: must verify both orthogonal neighbours to avoid corner-cutting
            next_x = curr_x + step_x
            next_z = curr_z + step_z
            if not grid.is_walkable(curr_x + step_x, curr_z) or not grid.is_walkable(curr_x, curr_z + step_z):
                return False
            curr_x = next_x
            curr_z = next_z
            t_max_x += t_delta_x
            t_max_z += t_delta_z
        elif t_max_x < t_max_z:
            curr_x += step_x
            t_max_x += t_delta_x
        else:
            curr_z += step_z
            t_max_z += t_delta_z

        if not grid.is_walkable(curr_x, curr_z):
            return False

    return True

def smooth_path(grid: GridNav, raw_waypoints: list[list[float]]) -> list[list[float]]:
    """Greedy string-pulling line-of-sight smoothing.

    Guarantees:
    - Never crosses an un-walkable cell.
    - Resulting polyline length is <= raw path length.
    - Endpoints are preserved.
    """
    if len(raw_waypoints) <= 2:
        return [list(pt) for pt in raw_waypoints]

    smoothed: list[list[float]] = [raw_waypoints[0]]
    curr_idx = 0
    n = len(raw_waypoints)

    while curr_idx < n - 1:
        # Search backwards from the end for the furthest visible waypoint
        furthest_visible = curr_idx + 1
        for check_idx in range(n - 1, curr_idx + 1, -1):
            p0 = raw_waypoints[curr_idx]
            p1 = raw_waypoints[check_idx]
            if check_line_of_sight(grid, p0[0], p0[1], p1[0], p1[1]):
                furthest_visible = check_idx
                break
        smoothed.append(raw_waypoints[furthest_visible])
        curr_idx = furthest_visible

    return smoothed

def compute_polyline_length(pts: list[list[float]]) -> float:
    tot = 0.0
    for i in range(1, len(pts)):
        tot += math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1])
    return tot

def find_path(
    collision_doc: dict[str, Any],
    start: Sequence[float],
    goal: Sequence[float],
    snap_radius_m: float = 1.5,
) -> dict[str, Any]:
    """Execute obstacle-aware A* pathfinding.

    Parameters:
        collision_doc: dict conforming to collision.json schema.
        start: [x, z] world coordinates in metres.
        goal: [x, z] world coordinates in metres.
        snap_radius_m: max search radius to snap non-walkable coords.

    Returns:
        Typed dictionary containing status, waypoints, cells, and lengths.
    """
    if not isinstance(start, (list, tuple)) or len(start) < 2:
        return {"ok": False, "reason": "Invalid start coordinates"}
    if not isinstance(goal, (list, tuple)) or len(goal) < 2:
        return {"ok": False, "reason": "Invalid goal coordinates"}

    grid = GridNav(collision_doc)

    start_x, start_z = float(start[0]), float(start[1])
    goal_x, goal_z = float(goal[0]), float(goal[1])

    # Snap start and goal to nearest walkable cells
    ok_s, s_ix, s_iz, s_dist = grid.snap_to_walkable(start_x, start_z, snap_radius_m)
    if not ok_s:
        return {
            "ok": False,
            "reason": f"Start position ({start_x:.2f}, {start_z:.2f}) not walkable and cannot be snapped within {snap_radius_m:.1f} m",
        }

    ok_g, g_ix, g_iz, g_dist = grid.snap_to_walkable(goal_x, goal_z, snap_radius_m)
    if not ok_g:
        return {
            "ok": False,
            "reason": f"Goal position ({goal_x:.2f}, {goal_z:.2f}) not walkable and cannot be snapped within {snap_radius_m:.1f} m",
        }

    snapped_start = grid.cell_to_world(s_ix, s_iz)
    snapped_goal = grid.cell_to_world(g_ix, g_iz)

    if s_ix == g_ix and s_iz == g_iz:
        wp = [[snapped_start[0], snapped_start[1]]]
        return {
            "ok": True,
            "cells": [(s_ix, s_iz)],
            "raw_waypoints": wp,
            "raw_length": 0.0,
            "waypoints": wp,
            "length": 0.0,
            "cost": 0.0,
            "snapped_start": list(snapped_start),
            "snapped_goal": list(snapped_goal),
            "snap_start_dist": s_dist,
            "snap_goal_dist": g_dist,
        }

    # A* Algorithm Setup
    # Priority Queue elements: (f_score, g_score, counter, (ix, iz))
    open_heap: list[tuple[float, float, int, tuple[int, int]]] = []
    counter = 0

    h0 = octile_heuristic(s_ix, s_iz, g_ix, g_iz)
    heapq.heappush(open_heap, (h0, 0.0, counter, (s_ix, s_iz)))

    g_score: dict[tuple[int, int], float] = {(s_ix, s_iz): 0.0}
    came_from: dict[tuple[int, int], tuple[int, int]] = {}
    closed_set: set[tuple[int, int]] = set()

    found = False

    while open_heap:
        _, current_g, _, current = heapq.heappop(open_heap)

        if current in closed_set:
            continue
        closed_set.add(current)

        if current == (g_ix, g_iz):
            found = True
            break

        cx, cz = current

        for dx, dz, step_cost, o1, o2 in NEIGHBORS:
            nx = cx + dx
            nz = cz + dz

            if not grid.is_walkable(nx, nz):
                continue

            # NO CORNER CUTTING: for diagonal moves, verify both orthogonal neighbours are walkable
            if o1 is not None and o2 is not None:
                if not grid.is_walkable(cx + o1[0], cz + o1[1]) or not grid.is_walkable(cx + o2[0], cz + o2[1]):
                    continue

            neighbor = (nx, nz)
            if neighbor in closed_set:
                continue

            tentative_g = current_g + step_cost
            if tentative_g < g_score.get(neighbor, float("inf")):
                g_score[neighbor] = tentative_g
                came_from[neighbor] = current
                h = octile_heuristic(nx, nz, g_ix, g_iz)
                f = tentative_g + h
                counter += 1
                heapq.heappush(open_heap, (f, tentative_g, counter, neighbor))

    if not found:
        return {
            "ok": False,
            "reason": f"No walkable path exists between ({start_x:.2f}, {start_z:.2f}) and ({goal_x:.2f}, {goal_z:.2f})",
            "snapped_start": list(snapped_start),
            "snapped_goal": list(snapped_goal),
            "snap_start_dist": s_dist,
            "snap_goal_dist": g_dist,
        }

    # Reconstruct Path
    curr = (g_ix, g_iz)
    path_cells: list[tuple[int, int]] = [curr]
    while curr in came_from:
        curr = came_from[curr]
        path_cells.append(curr)
    path_cells.reverse()

    raw_waypoints = [list(grid.cell_to_world(ix, iz)) for ix, iz in path_cells]
    optimal_cost = g_score[(g_ix, g_iz)]
    raw_length_m = optimal_cost * grid.cell_size

    # Line-of-sight smoothing
    smoothed = smooth_path(grid, raw_waypoints)
    smoothed_len = compute_polyline_length(smoothed)

    return {
        "ok": True,
        "cells": path_cells,
        "raw_waypoints": raw_waypoints,
        "raw_length": round(raw_length_m, 4),
        "waypoints": smoothed,
        "length": round(smoothed_len, 4),
        "cost": round(optimal_cost, 6),
        "snapped_start": list(snapped_start),
        "snapped_goal": list(snapped_goal),
        "snap_start_dist": round(s_dist, 4),
        "snap_goal_dist": round(g_dist, 4),
    }
