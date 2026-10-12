/** Minimap: draws the walkable grid once, then the 'you are here' arrow each frame. Round 2: setPath() overlay hook. */
import { BLOCKED, FLOOR, type CollisionMap } from "./collision";

export class Minimap {
  private ctx: CanvasRenderingContext2D; private base: HTMLCanvasElement; private s: number; private path: [number, number][] = [];
  constructor(private cv: HTMLCanvasElement, private col: CollisionMap) {
    const ctx = cv.getContext("2d"); if (!ctx) throw new Error("2D canvas unavailable");
    this.ctx = ctx; this.s = Math.min(cv.width / col.nx, cv.height / col.nz);
    this.base = document.createElement("canvas"); this.base.width = col.nx; this.base.height = col.nz;
    const bctx = this.base.getContext("2d")!; const img = bctx.createImageData(col.nx, col.nz);
    for (let i = 0; i < col.grid.length; i++) {
      const v = col.grid[i], inf = col.inflated[i]; const c = v === BLOCKED ? [200, 70, 70] : inf === FLOOR ? [225, 225, 225] : v === FLOOR ? [150, 150, 170] : [40, 40, 40];
      img.data.set([c[0], c[1], c[2], 255], i * 4);
    }
    bctx.putImageData(img, 0, 0);
  }
  /** ROUND 2 HOOK: polyline of world (x, z) points drawn over the map. */
  setPath(p: [number, number][]): void { this.path = p; }
  draw(x: number, z: number, yaw: number): void {
    const { ctx, s, col } = this; ctx.imageSmoothingEnabled = false; ctx.clearRect(0, 0, this.cv.width, this.cv.height);
    ctx.drawImage(this.base, 0, 0, col.nx * s, col.nz * s);
    const px = ((x - col.ox) / col.cell) * s, pz = ((z - col.oz) / col.cell) * s;
    if (this.path.length > 1) { ctx.strokeStyle = "#4da3ff"; ctx.lineWidth = 3; ctx.beginPath(); this.path.forEach(([a, b], i) => { const X = ((a - col.ox) / col.cell) * s, Z = ((b - col.oz) / col.cell) * s; i ? ctx.lineTo(X, Z) : ctx.moveTo(X, Z); }); ctx.stroke(); }
    const ang = Math.atan2(-Math.cos(yaw), -Math.sin(yaw));    // forward = (-sin yaw, -cos yaw) in (x, z)
    ctx.save(); ctx.translate(px, pz); ctx.rotate(ang); ctx.fillStyle = "#00e676"; ctx.strokeStyle = "#000"; ctx.lineWidth = 2;
    ctx.beginPath(); ctx.moveTo(12, 0); ctx.lineTo(-8, 8); ctx.lineTo(-4, 0); ctx.lineTo(-8, -8); ctx.closePath(); ctx.fill(); ctx.stroke(); ctx.restore();
  }
}
