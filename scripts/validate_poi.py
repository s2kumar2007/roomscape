"""validate_poi.py: Validate poi.json schema and collision bounds/walkability.

Usage:
  python scripts/validate_poi.py <path_to_poi.json> <path_to_collision.json>
"""
from __future__ import annotations
import json
import math
import sys
from pathlib import Path

# Add pipeline to pythonpath
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "pipeline"))

from navigation import GridNav

def validate_poi(poi_path: Path, collision_path: Path) -> tuple[bool, list[str]]:
    errors: list[str] = []

    if not poi_path.exists():
        return False, [f"POI file not found: {poi_path}"]
    if not collision_path.exists():
        return False, [f"Collision file not found: {collision_path}"]

    try:
        poi_doc = json.loads(poi_path.read_text(encoding="utf-8"))
    except Exception as e:
        return False, [f"Failed to parse JSON in {poi_path}: {e}"]

    try:
        col_doc = json.loads(collision_path.read_text(encoding="utf-8"))
    except Exception as e:
        return False, [f"Failed to parse JSON in {collision_path}: {e}"]

    if not isinstance(poi_doc, dict):
        return False, ["Root of poi.json must be an object/dict"]

    version = poi_doc.get("version")
    if version != 1:
        errors.append(f"Expected poi.json version 1, got {version}")

    pois = poi_doc.get("pois")
    if not isinstance(pois, list):
        errors.append(f"'pois' field must be a list, got {type(pois).__name__}")
        return False, errors

    grid = GridNav(col_doc)
    b_min = col_doc.get("bounds", {}).get("min", [-float("inf"), -float("inf"), -float("inf")])
    b_max = col_doc.get("bounds", {}).get("max", [float("inf"), float("inf"), float("inf")])

    seen_ids: set[str] = set()

    for idx, p in enumerate(pois):
        p_prefix = f"POI #{idx}"
        if not isinstance(p, dict):
            errors.append(f"{p_prefix}: Must be a dictionary object")
            continue

        p_id = p.get("id")
        if not isinstance(p_id, str) or not p_id.strip():
            errors.append(f"{p_prefix}: 'id' must be a non-empty string")
        elif p_id in seen_ids:
            errors.append(f"{p_prefix} ('{p_id}'): Duplicate ID detected")
        else:
            seen_ids.add(p_id)

        p_name = p.get("name")
        if not isinstance(p_name, str) or not p_name.strip():
            errors.append(f"{p_prefix} ('{p_id}'): 'name' must be a non-empty string")

        pos = p.get("position")
        if not isinstance(pos, (list, tuple)) or len(pos) != 2:
            errors.append(f"{p_prefix} ('{p_id}'): 'position' must be a 2-element array [x, z]")
            continue

        try:
            x, z = float(pos[0]), float(pos[1])
        except (ValueError, TypeError):
            errors.append(f"{p_prefix} ('{p_id}'): 'position' coordinates must be numbers")
            continue

        # Check inside bounds
        if not (b_min[0] <= x <= b_max[0] and b_min[2] <= z <= b_max[2]):
            errors.append(
                f"{p_prefix} ('{p_id}'): position [{x:.2f}, {z:.2f}] is outside scene bounds "
                f"([{b_min[0]:.2f}, {b_min[2]:.2f}] .. [{b_max[0]:.2f}, {b_max[2]:.2f}])"
            )

        # Snap to walkable within 1.0 m
        ok_snap, sx, sz, dist = grid.snap_to_walkable(x, z, max_radius_m=1.0)
        if not ok_snap or dist > 1.0:
            errors.append(
                f"{p_prefix} ('{p_id}'): position [{x:.2f}, {z:.2f}] cannot snap to a walkable cell within 1.0 m "
                f"(snap distance: {dist:.2f} m)"
            )

    return len(errors) == 0, errors

def main() -> int:
    if len(sys.argv) < 3:
        print("Usage: python scripts/validate_poi.py <poi.json> <collision.json>")
        return 2

    poi_path = Path(sys.argv[1])
    collision_path = Path(sys.argv[2])

    ok, errors = validate_poi(poi_path, collision_path)
    if ok:
        print(f"[OK] {poi_path} is valid.")
        return 0

    print(f"[FAIL] {poi_path} validation failed with {len(errors)} error(s):")
    for err in errors:
        print(f"  - {err}")
    return 1

if __name__ == "__main__":
    sys.exit(main())
