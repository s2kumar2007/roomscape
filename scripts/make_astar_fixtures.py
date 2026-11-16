"""make_astar_fixtures.py: Generate deterministic A* test cases from collision.json.

Output: viewer/src/__fixtures__/astar_cases.json
Asserted by vitest to achieve cross-language Python <-> TypeScript parity within 1e-6.
"""
from __future__ import annotations
import json
import random
import sys
from pathlib import Path

# Add pipeline to pythonpath
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "pipeline"))

from navigation import GridNav, find_path

def main() -> int:
    col_path = REPO_ROOT / "viewer" / "public" / "scene" / "collision.json"
    if not col_path.exists():
        print(f"[!] collision.json not found at {col_path}")
        return 1

    col_doc = json.loads(col_path.read_text(encoding="utf-8"))
    grid = GridNav(col_doc)

    # Gather all walkable cells
    walkable_cells: list[tuple[int, int]] = []
    for iz in range(grid.nz):
        for ix in range(grid.nx):
            if grid.is_walkable(ix, iz):
                walkable_cells.append((ix, iz))

    print(f"Total walkable cells in scene: {len(walkable_cells)}")
    if not walkable_cells:
        print("[!] No walkable cells found in collision.json")
        return 1

    rng = random.Random(42)
    cases: list[dict] = []

    # 1. Zero-distance case (same cell)
    c0 = walkable_cells[0]
    p0 = grid.cell_to_world(c0[0], c0[1])
    res0 = find_path(col_doc, p0, p0)
    assert res0["ok"] is True
    cases.append({
        "id": "zero_distance",
        "start": [round(p0[0], 4), round(p0[1], 4)],
        "goal": [round(p0[0], 4), round(p0[1], 4)],
        "expected_cost": res0["cost"],
        "expected_cells": len(res0["cells"]),
    })

    # 2. Adjacent orthogonal / diagonal cells
    for dix, diz, label in [(1, 0, "adjacent_ortho"), (1, 1, "adjacent_diag")]:
        for c in walkable_cells:
            target = (c[0] + dix, c[1] + diz)
            if target in walkable_cells:
                # verify corner cutting rule for diagonal
                if dix != 0 and diz != 0:
                    if not grid.is_walkable(c[0] + dix, c[1]) or not grid.is_walkable(c[0], c[1] + diz):
                        continue
                w1 = grid.cell_to_world(c[0], c[1])
                w2 = grid.cell_to_world(target[0], target[1])
                res = find_path(col_doc, w1, w2)
                if res["ok"]:
                    cases.append({
                        "id": label,
                        "start": [round(w1[0], 4), round(w1[1], 4)],
                        "goal": [round(w2[0], 4), round(w2[1], 4)],
                        "expected_cost": res["cost"],
                        "expected_cells": len(res["cells"]),
                    })
                    break

    # 3. Random reachable pairs of varying distances
    attempts = 0
    while len(cases) < 25 and attempts < 200:
        attempts += 1
        c_a = rng.choice(walkable_cells)
        c_b = rng.choice(walkable_cells)
        p_a = grid.cell_to_world(c_a[0], c_a[1])
        p_b = grid.cell_to_world(c_b[0], c_b[1])
        res = find_path(col_doc, p_a, p_b)
        if res["ok"]:
            cases.append({
                "id": f"random_pair_{len(cases)}",
                "start": [round(p_a[0], 4), round(p_a[1], 4)],
                "goal": [round(p_b[0], 4), round(p_b[1], 4)],
                "expected_cost": res["cost"],
                "expected_cells": len(res["cells"]),
                "expected_length": res["length"],
            })

    out_dir = REPO_ROOT / "viewer" / "src" / "__fixtures__"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "astar_cases.json"
    out_file.write_text(json.dumps({"cases": cases}, indent=2), encoding="utf-8")
    print(f"[OK] Generated {len(cases)} A* test fixtures at {out_file}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
