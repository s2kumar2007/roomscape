import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { BLOCKED, CollisionMap, FLOOR, decodeRLE, type CollisionDoc } from "./collision";

const doc = JSON.parse(readFileSync(new URL("../public/scene/collision.json", import.meta.url), "utf8")) as CollisionDoc;
const meta = JSON.parse(readFileSync(new URL("../public/scene/meta.json", import.meta.url), "utf8"));

describe("collision (cross-checked against Python-generated collision.json)", () => {
  const m = new CollisionMap(doc);
  it("decodes full grids", () => {
    expect(m.grid.length).toBe(m.nx * m.nz); expect(m.inflated.length).toBe(m.nx * m.nz);
    expect(() => decodeRLE([[1, 3]], 4)).toThrow();
  });
  it("spawn is walkable", () => expect(m.isWalkable(meta.spawn.position[0], meta.spawn.position[2])).toBe(true));
  it("out of bounds is not walkable", () => { expect(m.isWalkable(m.ox - 5, m.oz)).toBe(false); expect(m.isWalkable(m.ox + 1e4, m.oz)).toBe(false); });
  it("walking far in any direction never leaves walkable space (no tunnelling, even with a huge step)", () => {
    const [sx, sz] = [meta.spawn.position[0], meta.spawn.position[2]];
    for (let a = 0; a < 360; a += 15) {
      let x = sx, z = sz;
      for (let i = 0; i < 40; i++) { [x, z] = m.move(x, z, Math.cos(a * Math.PI / 180) * 3, Math.sin(a * Math.PI / 180) * 3); expect(m.isWalkable(x, z)).toBe(true); }
    }
  });
  it("slides along a wall instead of stopping dead", () => {
    // find a walkable cell next to a continuous wall (blocked column to +x), open space along +z
    for (let iz = 1; iz < m.nz - 2; iz++) for (let ix = 1; ix < m.nx - 2; ix++) {
      const at = (x: number, z: number) => m.inflated[z * m.nx + x];
      if (at(ix, iz) === FLOOR && at(ix, iz + 1) === FLOOR && at(ix, iz + 2) === FLOOR && at(ix + 1, iz) === BLOCKED && at(ix + 1, iz + 1) === BLOCKED && at(ix + 1, iz + 2) === BLOCKED) {
        const x0 = m.ox + (ix + 0.5) * m.cell, z0 = m.oz + (iz + 0.5) * m.cell;
        const [x1, z1] = m.move(x0, z0, m.cell * 1.5, m.cell * 1.5);   // diagonal into the wall
        expect(m.isWalkable(x1, z1)).toBe(true); expect(x1).toBeLessThan(m.ox + (ix + 1) * m.cell);   // stopped at the wall
        expect(z1 - z0).toBeGreaterThan(m.cell); return;                                              // but kept sliding along it
      }
    }
    throw new Error("no wall-adjacent test cell found");
  });
});
