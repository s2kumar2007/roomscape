import { describe, it, expect } from "vitest";
import { CollisionMap, type CollisionDoc } from "./collision";
import { AStarFinder } from "./astar";
import fixtureData from "./__fixtures__/astar_cases.json";
import sceneCollision from "../public/scene/collision.json";

function makeSyntheticDoc(gridCells: number[][], cellSize = 0.1, origin: [number, number] = [0, 0]): CollisionDoc {
  const nz = gridCells.length;
  const nx = gridCells[0].length;
  const flat: number[] = [];
  for (const row of gridCells) {
    for (const v of row) flat.push(v);
  }
  // Encode into simple RLE runs
  const runs: [number, number][] = [];
  let curVal = flat[0];
  let curLen = 0;
  for (const v of flat) {
    if (v === curVal) {
      curLen++;
    } else {
      runs.push([curVal, curLen]);
      curVal = v;
      curLen = 1;
    }
  }
  runs.push([curVal, curLen]);

  return {
    version: 1,
    origin,
    cell_size: cellSize,
    size: [nx, nz],
    encoding: "rle_row_major",
    grid: runs,
    inflated: runs,
    agent_radius_m: 0.25,
    floor_height: 0,
    bounds: { min: [0, 0, 0], max: [nx * cellSize, 2, nz * cellSize] },
  };
}

describe("AStarFinder Parity and Functionality", () => {
  const colMap = new CollisionMap(sceneCollision as unknown as CollisionDoc);
  const finder = new AStarFinder(colMap);

  it("matches Python reference optimal cost on all fixtures within 1e-6", () => {
    for (const testCase of fixtureData.cases) {
      const res = finder.findPath(
        testCase.start as [number, number],
        testCase.goal as [number, number]
      );
      expect(res.ok).toBe(true);
      if (res.ok) {
        expect(Math.abs(res.cost - testCase.expected_cost)).toBeLessThanOrEqual(1e-6);
        expect(res.cells.length).toBe(testCase.expected_cells);
      }
    }
  });

  it("prevents diagonal corner cutting between obstacles", () => {
    // 3x3 grid: (1, 0) and (0, 1) are blocked (2), start at (0, 0), goal at (1, 1)
    const grid = [
      [1, 2, 1],
      [2, 1, 1],
      [1, 1, 1],
    ];
    const doc = makeSyntheticDoc(grid);
    const col = new CollisionMap(doc);
    const f = new AStarFinder(col);
    const res = f.findPath([0.05, 0.05], [0.15, 0.15], 0.05);
    expect(res.ok).toBe(false);
  });

  it("detours around obstacles", () => {
    const grid = [
      [1, 1, 1, 1, 1],
      [1, 1, 2, 1, 1],
      [1, 1, 2, 1, 1],
      [1, 1, 2, 1, 1],
      [1, 1, 1, 1, 1],
    ];
    const doc = makeSyntheticDoc(grid);
    const col = new CollisionMap(doc);
    const f = new AStarFinder(col);
    const res = f.findPath([0.05, 0.25], [0.45, 0.25]);
    expect(res.ok).toBe(true);
    if (res.ok) {
      for (const [ix, iz] of res.cells) {
        expect(ix === 2 && iz >= 1 && iz <= 3).toBe(false);
      }
    }
  });

  it("handles unreachable goals gracefully with typed result", () => {
    const grid = [
      [1, 1, 1, 1, 1],
      [1, 2, 2, 2, 1],
      [1, 2, 1, 2, 1],
      [1, 2, 2, 2, 1],
      [1, 1, 1, 1, 1],
    ];
    const doc = makeSyntheticDoc(grid);
    const col = new CollisionMap(doc);
    const f = new AStarFinder(col);
    const res = f.findPath([0.05, 0.05], [0.25, 0.25], 0.05);
    expect(res.ok).toBe(false);
    if (!res.ok) {
      expect(res.reason).toContain("No walkable path exists");
    }
  });

  it("snaps start and goal inside blocked cells to nearest walkable", () => {
    const grid = [
      [2, 1, 1, 1, 1],
      [1, 1, 1, 1, 1],
      [1, 1, 1, 1, 1],
      [1, 1, 1, 1, 1],
      [1, 1, 1, 1, 2],
    ];
    const doc = makeSyntheticDoc(grid);
    const col = new CollisionMap(doc);
    const f = new AStarFinder(col);
    const res = f.findPath([0.05, 0.05], [0.45, 0.45], 0.3);
    expect(res.ok).toBe(true);
    if (res.ok) {
      expect(res.snapStartDist).toBeGreaterThan(0);
      expect(res.snapGoalDist).toBeGreaterThan(0);
    }
  });

  it("smoothed path keeps line of sight and is never longer than raw path", () => {
    const res = finder.findPath([0.65, -4.25], [3.5, -4.5]);
    expect(res.ok).toBe(true);
    if (res.ok) {
      expect(res.length).toBeLessThanOrEqual(res.rawLength + 1e-4);
      for (let i = 1; i < res.waypoints.length; i++) {
        const [x0, z0] = res.waypoints[i - 1];
        const [x1, z1] = res.waypoints[i];
        expect(finder.checkLineOfSight(x0, z0, x1, z1)).toBe(true);
      }
    }
  });

  it("measures performance on real grid and synthetic 300x300 grid", () => {
    // 1. Real scene benchmark
    const t0 = performance.now();
    const resReal = finder.findPath([0.65, -4.25], [3.5, -4.5]);
    const tRealMs = performance.now() - t0;
    expect(resReal.ok).toBe(true);

    // 2. Synthetic 300x300 grid benchmark
    const grid300: number[][] = [];
    for (let z = 0; z < 300; z++) {
      const row: number[] = new Array(300).fill(1);
      if (z >= 50 && z <= 250) {
        row[100] = 2;
        row[200] = 2;
      }
      grid300.push(row);
    }
    grid300[150][100] = 1;
    grid300[150][200] = 1;

    const doc300 = makeSyntheticDoc(grid300, 0.1);
    const col300 = new CollisionMap(doc300);
    const finder300 = new AStarFinder(col300);

    const t1 = performance.now();
    const res300 = finder300.findPath([1.0, 15.0], [25.0, 15.0]);
    const t300Ms = performance.now() - t1;
    expect(res300.ok).toBe(true);

    console.log(`[BENCHMARK] TypeScript A* real scene grid: ${tRealMs.toFixed(2)} ms`);
    console.log(`[BENCHMARK] TypeScript A* synthetic 300x300 grid: ${t300Ms.toFixed(2)} ms`);
  });
});
