/** Collision map: decodes collision.json (RLE grids) and resolves movement with wall sliding. */
export const UNKNOWN = 0, FLOOR = 1, BLOCKED = 2;

export interface CollisionDoc {
  version: number; origin: [number, number]; cell_size: number; size: [number, number];
  encoding: string; grid: [number, number][]; inflated: [number, number][];
  agent_radius_m: number; floor_height: number; bounds: { min: number[]; max: number[] };
}

export function decodeRLE(runs: [number, number][], n: number): Uint8Array {
  const out = new Uint8Array(n); let p = 0;
  for (const [v, len] of runs) { if (v) out.fill(v, p, p + len); p += len; }
  if (p !== n) throw new Error(`collision RLE length ${p} != ${n}`);
  return out;
}

export class CollisionMap {
  readonly nx: number; readonly nz: number; readonly cell: number; readonly ox: number; readonly oz: number;
  readonly grid: Uint8Array; readonly inflated: Uint8Array;
  constructor(readonly doc: CollisionDoc) {
    if (doc.encoding !== "rle_row_major") throw new Error(`Unsupported collision encoding: ${doc.encoding}`);
    [this.nx, this.nz] = doc.size; this.cell = doc.cell_size; [this.ox, this.oz] = doc.origin;
    this.grid = decodeRLE(doc.grid, this.nx * this.nz); this.inflated = decodeRLE(doc.inflated, this.nx * this.nz);
  }
  /** Walkable iff the inflated grid says FLOOR (agent radius already applied). Out of bounds is not walkable. */
  isWalkable(x: number, z: number): boolean {
    const ix = Math.floor((x - this.ox) / this.cell), iz = Math.floor((z - this.oz) / this.cell);
    if (ix < 0 || iz < 0 || ix >= this.nx || iz >= this.nz) return false;
    return this.inflated[iz * this.nx + ix] === FLOOR;
  }
  /** Move (x,z) by (dx,dz) in sub-steps; slide along walls by trying each axis separately. Never tunnels, never leaves bounds. */
  move(x: number, z: number, dx: number, dz: number): [number, number] {
    const steps = Math.max(1, Math.ceil(Math.hypot(dx, dz) / (this.cell * 0.5)));
    const sx = dx / steps, sz = dz / steps;
    for (let i = 0; i < steps; i++) {
      if (this.isWalkable(x + sx, z + sz)) { x += sx; z += sz; }
      else if (this.isWalkable(x + sx, z)) x += sx;
      else if (this.isWalkable(x, z + sz)) z += sz;
      else break;
    }
    return [x, z];
  }
}
