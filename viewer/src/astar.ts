/**
 * astar.ts: 8-connected obstacle-aware A* pathfinding & line-of-sight smoothing.
 *
 * Designed for zero per-frame allocations on repeated path queries:
 * Reuses pre-allocated typed arrays and a flat binary min-heap.
 */
import { FLOOR, type CollisionMap } from "./collision";

export interface PathResultSuccess {
  ok: true;
  cells: [number, number][];
  rawWaypoints: [number, number][];
  rawLength: number;
  waypoints: [number, number][];
  length: number;
  cost: number;
  snappedStart: [number, number];
  snappedGoal: [number, number];
  snapStartDist: number;
  snapGoalDist: number;
}

export interface PathResultFailure {
  ok: false;
  reason: string;
  snappedStart?: [number, number];
  snappedGoal?: [number, number];
  snapStartDist?: number;
  snapGoalDist?: number;
}

export type PathResult = PathResultSuccess | PathResultFailure;

const SQRT2 = Math.SQRT2;
const OCTILE_FACTOR = SQRT2 - 1.0;

// 8 directions: [dx, dz, cost, ortho1_dx, ortho1_dz, ortho2_dx, ortho2_dz]
// For orthogonal moves: ortho checks are 0
const MOVES: readonly [number, number, number, number, number, number, number][] = [
  // Orthogonal (cost 1.0)
  [1, 0, 1.0, 0, 0, 0, 0],
  [-1, 0, 1.0, 0, 0, 0, 0],
  [0, 1, 1.0, 0, 0, 0, 0],
  [0, -1, 1.0, 0, 0, 0, 0],
  // Diagonal (cost sqrt(2)): require both orthogonal components to be walkable
  [1, 1, SQRT2, 1, 0, 0, 1],
  [1, -1, SQRT2, 1, 0, 0, -1],
  [-1, 1, SQRT2, -1, 0, 0, 1],
  [-1, -1, SQRT2, -1, 0, 0, -1],
];

export class AStarFinder {
  private nx: number;
  private nz: number;
  private cell: number;
  private ox: number;
  private oz: number;
  private totalCells: number;

  // Reusable typed arrays across queries (zero per-query allocation)
  private gScore: Float64Array;
  private cameFrom: Int32Array;
  private runTag: Uint32Array;
  private currentRun = 1;

  // Pre-allocated flat binary min-heap
  private heapIndices: Int32Array;
  private heapKeys: Float64Array;
  private heapSize = 0;

  constructor(private col: CollisionMap) {
    this.nx = col.nx;
    this.nz = col.nz;
    this.cell = col.cell;
    this.ox = col.ox;
    this.oz = col.oz;
    this.totalCells = this.nx * this.nz;

    this.gScore = new Float64Array(this.totalCells);
    this.cameFrom = new Int32Array(this.totalCells);
    this.runTag = new Uint32Array(this.totalCells);

    this.heapIndices = new Int32Array(this.totalCells);
    this.heapKeys = new Float64Array(this.totalCells);
  }

  isWalkableCell(ix: number, iz: number): boolean {
    if (ix < 0 || iz < 0 || ix >= this.nx || iz >= this.nz) return false;
    return this.col.inflated[iz * this.nx + ix] === FLOOR;
  }

  cellToWorld(ix: number, iz: number): [number, number] {
    return [
      this.ox + (ix + 0.5) * this.cell,
      this.oz + (iz + 0.5) * this.cell,
    ];
  }

  worldToCell(x: number, z: number): [number, number] {
    return [
      Math.floor((x - this.ox) / this.cell),
      Math.floor((z - this.oz) / this.cell),
    ];
  }

  snapToWalkable(x: number, z: number, maxRadiusM: number = 1.5): [boolean, number, number, number] {
    const [cx, cz] = this.worldToCell(x, z);
    if (this.isWalkableCell(cx, cz)) {
      const [wx, wz] = this.cellToWorld(cx, cz);
      const dist = Math.hypot(x - wx, z - wz);
      return [true, cx, cz, dist];
    }

    const maxCells = Math.ceil(maxRadiusM / this.cell);
    let bestX = -1;
    let bestZ = -1;
    let bestDistSq = maxRadiusM * maxRadiusM;

    for (let diz = -maxCells; diz <= maxCells; diz++) {
      const niz = cz + diz;
      if (niz < 0 || niz >= this.nz) continue;
      for (let dix = -maxCells; dix <= maxCells; dix++) {
        const nix = cx + dix;
        if (nix < 0 || nix >= this.nx) continue;
        if (this.col.inflated[niz * this.nx + nix] === FLOOR) {
          const [wx, wz] = this.cellToWorld(nix, niz);
          const dSq = (wx - x) ** 2 + (wz - z) ** 2;
          if (dSq <= bestDistSq) {
            bestDistSq = dSq;
            bestX = nix;
            bestZ = niz;
          }
        }
      }
    }

    if (bestX !== -1) {
      return [true, bestX, bestZ, Math.sqrt(bestDistSq)];
    }
    return [false, -1, -1, Infinity];
  }

  // --- Binary Heap operations ---
  private heapPush(index: number, key: number): void {
    let i = this.heapSize++;
    this.heapIndices[i] = index;
    this.heapKeys[i] = key;
    while (i > 0) {
      const parent = (i - 1) >> 1;
      if (this.heapKeys[parent] <= this.heapKeys[i]) break;
      this.swapHeap(parent, i);
      i = parent;
    }
  }

  private heapPop(): number {
    const root = this.heapIndices[0];
    const last = --this.heapSize;
    if (last > 0) {
      this.heapIndices[0] = this.heapIndices[last];
      this.heapKeys[0] = this.heapKeys[last];
      let i = 0;
      while (true) {
        const left = (i << 1) + 1;
        const right = left + 1;
        let smallest = i;
        if (left < this.heapSize && this.heapKeys[left] < this.heapKeys[smallest]) smallest = left;
        if (right < this.heapSize && this.heapKeys[right] < this.heapKeys[smallest]) smallest = right;
        if (smallest === i) break;
        this.swapHeap(i, smallest);
        i = smallest;
      }
    }
    return root;
  }

  private swapHeap(a: number, b: number): void {
    const tmpIdx = this.heapIndices[a];
    this.heapIndices[a] = this.heapIndices[b];
    this.heapIndices[b] = tmpIdx;
    const tmpKey = this.heapKeys[a];
    this.heapKeys[a] = this.heapKeys[b];
    this.heapKeys[b] = tmpKey;
  }

  /** Line of sight test between world (x0, z0) and (x1, z1). */
  checkLineOfSight(x0: number, z0: number, x1: number, z1: number): boolean {
    const u0 = (x0 - this.ox) / this.cell;
    const v0 = (z0 - this.oz) / this.cell;
    const u1 = (x1 - this.ox) / this.cell;
    const v1 = (z1 - this.oz) / this.cell;

    const ix = Math.floor(u0);
    const iz = Math.floor(v0);
    const ixEnd = Math.floor(u1);
    const izEnd = Math.floor(v1);

    if (!this.isWalkableCell(ix, iz) || !this.isWalkableCell(ixEnd, izEnd)) {
      return false;
    }

    const du = u1 - u0;
    const dv = v1 - v0;

    const stepX = du > 0 ? 1 : du < 0 ? -1 : 0;
    const stepZ = dv > 0 ? 1 : dv < 0 ? -1 : 0;

    let tMaxX = stepX > 0 ? (Math.floor(u0) + 1 - u0) / du : stepX < 0 ? (u0 - Math.floor(u0)) / -du : Infinity;
    const tDeltaX = stepX !== 0 ? 1 / Math.abs(du) : Infinity;

    let tMaxZ = stepZ > 0 ? (Math.floor(v0) + 1 - v0) / dv : stepZ < 0 ? (v0 - Math.floor(v0)) / -dv : Infinity;
    const tDeltaZ = stepZ !== 0 ? 1 / Math.abs(dv) : Infinity;

    let currX = ix;
    let currZ = iz;
    const maxSteps = (Math.abs(ixEnd - ix) + Math.abs(izEnd - iz) + 2) * 2;
    let steps = 0;

    while ((currX !== ixEnd || currZ !== izEnd) && steps < maxSteps) {
      steps++;
      const eps = 1e-9;
      if (Math.abs(tMaxX - tMaxZ) < eps) {
        const nextX = currX + stepX;
        const nextZ = currZ + stepZ;
        if (!this.isWalkableCell(currX + stepX, currZ) || !this.isWalkableCell(currX, currZ + stepZ)) {
          return false;
        }
        currX = nextX;
        currZ = nextZ;
        tMaxX += tDeltaX;
        tMaxZ += tDeltaZ;
      } else if (tMaxX < tMaxZ) {
        currX += stepX;
        tMaxX += tDeltaX;
      } else {
        currZ += stepZ;
        tMaxZ += tDeltaZ;
      }

      if (!this.isWalkableCell(currX, currZ)) {
        return false;
      }
    }

    return true;
  }

  smoothPath(rawWaypoints: [number, number][]): [number, number][] {
    if (rawWaypoints.length <= 2) {
      return rawWaypoints.slice();
    }

    const smoothed: [number, number][] = [rawWaypoints[0]];
    let currIdx = 0;
    const n = rawWaypoints.length;

    while (currIdx < n - 1) {
      let furthestVisible = currIdx + 1;
      for (let checkIdx = n - 1; checkIdx > currIdx + 1; checkIdx--) {
        const p0 = rawWaypoints[currIdx];
        const p1 = rawWaypoints[checkIdx];
        if (this.checkLineOfSight(p0[0], p0[1], p1[0], p1[1])) {
          furthestVisible = checkIdx;
          break;
        }
      }
      smoothed.push(rawWaypoints[furthestVisible]);
      currIdx = furthestVisible;
    }

    return smoothed;
  }

  findPath(start: [number, number], goal: [number, number], snapRadiusM: number = 1.5): PathResult {
    const [startX, startZ] = start;
    const [goalX, goalZ] = goal;

    const [okS, sIx, sIz, sDist] = this.snapToWalkable(startX, startZ, snapRadiusM);
    if (!okS) {
      return {
        ok: false,
        reason: `Start position (${startX.toFixed(2)}, ${startZ.toFixed(2)}) not walkable and cannot be snapped within ${snapRadiusM.toFixed(1)} m`,
      };
    }

    const [okG, gIx, gIz, gDist] = this.snapToWalkable(goalX, goalZ, snapRadiusM);
    if (!okG) {
      return {
        ok: false,
        reason: `Goal position (${goalX.toFixed(2)}, ${goalZ.toFixed(2)}) not walkable and cannot be snapped within ${snapRadiusM.toFixed(1)} m`,
      };
    }

    const snappedStart = this.cellToWorld(sIx, sIz);
    const snappedGoal = this.cellToWorld(gIx, gIz);

    if (sIx === gIx && sIz === gIz) {
      const wp: [number, number][] = [snappedStart];
      return {
        ok: true,
        cells: [[sIx, sIz]],
        rawWaypoints: wp,
        rawLength: 0,
        waypoints: wp,
        length: 0,
        cost: 0,
        snappedStart,
        snappedGoal,
        snapStartDist: sDist,
        snapGoalDist: gDist,
      };
    }

    // Advance runTag iteration (resets visited status in O(1) without reallocations)
    this.currentRun++;
    if (this.currentRun === 0xffffffff) {
      this.runTag.fill(0);
      this.currentRun = 1;
    }
    const run = this.currentRun;

    const startIndex = sIz * this.nx + sIx;
    const goalIndex = gIz * this.nx + gIx;

    this.heapSize = 0;
    this.gScore[startIndex] = 0;
    this.cameFrom[startIndex] = -1;
    this.runTag[startIndex] = run;

    const h0 = octileHeuristic(sIx, sIz, gIx, gIz);
    this.heapPush(startIndex, h0);

    let found = false;

    while (this.heapSize > 0) {
      const currIdx = this.heapPop();
      if (currIdx === goalIndex) {
        found = true;
        break;
      }

      const currG = this.gScore[currIdx];
      const cx = currIdx % this.nx;
      const cz = (currIdx / this.nx) | 0;

      for (let i = 0; i < 8; i++) {
        const [dx, dz, cost, o1x, o1z, o2x, o2z] = MOVES[i];
        const nx = cx + dx;
        const nz = cz + dz;

        if (nx < 0 || nz < 0 || nx >= this.nx || nz >= this.nz) continue;
        const neighborIdx = nz * this.nx + nx;

        if (this.col.inflated[neighborIdx] !== FLOOR) continue;

        // NO CORNER CUTTING: for diagonal moves, verify both orthogonal neighbours
        if (cost > 1.0) {
          if (
            this.col.inflated[(cz + o1z) * this.nx + (cx + o1x)] !== FLOOR ||
            this.col.inflated[(cz + o2z) * this.nx + (cx + o2x)] !== FLOOR
          ) {
            continue;
          }
        }

        const tentativeG = currG + cost;
        const visitedInThisRun = this.runTag[neighborIdx] === run;

        if (!visitedInThisRun || tentativeG < this.gScore[neighborIdx]) {
          this.runTag[neighborIdx] = run;
          this.gScore[neighborIdx] = tentativeG;
          this.cameFrom[neighborIdx] = currIdx;
          const h = octileHeuristic(nx, nz, gIx, gIz);
          this.heapPush(neighborIdx, tentativeG + h);
        }
      }
    }

    if (!found) {
      return {
        ok: false,
        reason: `No walkable path exists between (${startX.toFixed(2)}, ${startZ.toFixed(2)}) and (${goalX.toFixed(2)}, ${goalZ.toFixed(2)})`,
        snappedStart,
        snappedGoal,
        snapStartDist: sDist,
        snapGoalDist: gDist,
      };
    }

    // Reconstruct path
    const cells: [number, number][] = [];
    let p = goalIndex;
    while (p !== -1) {
      cells.push([p % this.nx, (p / this.nx) | 0]);
      p = this.cameFrom[p];
    }
    cells.reverse();

    const rawWaypoints: [number, number][] = cells.map(([ix, iz]) => this.cellToWorld(ix, iz));
    const cost = this.gScore[goalIndex];
    const rawLength = cost * this.cell;

    const waypoints = this.smoothPath(rawWaypoints);
    let length = 0;
    for (let i = 1; i < waypoints.length; i++) {
      length += Math.hypot(waypoints[i][0] - waypoints[i - 1][0], waypoints[i][1] - waypoints[i - 1][1]);
    }

    return {
      ok: true,
      cells,
      rawWaypoints,
      rawLength: Number(rawLength.toFixed(4)),
      waypoints,
      length: Number(length.toFixed(4)),
      cost: Number(cost.toFixed(6)),
      snappedStart,
      snappedGoal,
      snapStartDist: Number(sDist.toFixed(4)),
      snapGoalDist: Number(gDist.toFixed(4)),
    };
  }
}

function octileHeuristic(ix1: number, iz1: number, ix2: number, iz2: number): number {
  const dx = Math.abs(ix1 - ix2);
  const dz = Math.abs(iz1 - iz2);
  return dx < dz ? dz + OCTILE_FACTOR * dx : dx + OCTILE_FACTOR * dz;
}
