/** First-person controls: pointer-lock look, WASD + Shift, smooth frame-rate-independent acceleration, collision, touch fallback. */
import * as THREE from "three";
import type { CollisionMap } from "./collision";

export class FirstPersonControls {
  yaw = 0; pitch = 0; x = 0; z = 0;
  private vx = 0; private vz = 0;
  private keys = new Set<string>();
  private joy = { x: 0, y: 0 };
  private lookId: number | null = null; private lastLook = { x: 0, y: 0 };
  private disposers: (() => void)[] = [];
  private spawn = { x: 0, z: 0, yaw: 0 };
  constructor(private cam: THREE.PerspectiveCamera, private dom: HTMLElement, private col: CollisionMap,
              private opt: { eye: number; walk: number; run: number; accel?: number; sens?: number }) {
    const on = <K extends keyof WindowEventMap>(t: K, f: (e: WindowEventMap[K]) => void) => { window.addEventListener(t, f); this.disposers.push(() => window.removeEventListener(t, f)); };
    on("keydown", (e) => { this.keys.add(e.code); });
    on("keyup", (e) => { this.keys.delete(e.code); });
    on("blur", () => this.keys.clear());
    on("mousemove", (e) => { if (document.pointerLockElement === this.dom) this.look(e.movementX, e.movementY); });
    const click = () => { if (!matchMedia("(pointer: coarse)").matches) void this.dom.requestPointerLock?.(); };
    this.dom.addEventListener("click", click); this.disposers.push(() => this.dom.removeEventListener("click", click));
    if (matchMedia("(pointer: coarse)").matches) this.setupTouch();
  }
  setSpawn(x: number, z: number, yaw: number): void { this.spawn = { x, z, yaw }; this.reset(); }
  reset(): void { this.x = this.spawn.x; this.z = this.spawn.z; this.yaw = this.spawn.yaw; this.pitch = 0; this.vx = this.vz = 0; this.apply(); }
  private look(dx: number, dy: number): void {
    const s = this.opt.sens ?? 0.0022;
    this.yaw -= dx * s; this.pitch = Math.max(-1.45, Math.min(1.45, this.pitch - dy * s));
  }
  private setupTouch(): void {
    const joy = document.createElement("div"); joy.className = "joy"; const knob = document.createElement("i"); joy.appendChild(knob); document.body.appendChild(joy);
    let jid: number | null = null;
    const jmove = (e: PointerEvent) => {
      const r = joy.getBoundingClientRect(); let dx = (e.clientX - r.left - r.width / 2) / (r.width / 2), dy = (e.clientY - r.top - r.height / 2) / (r.height / 2);
      const m = Math.hypot(dx, dy); if (m > 1) { dx /= m; dy /= m; }
      this.joy = { x: dx, y: dy }; knob.style.transform = `translate(${dx * 35}px, ${dy * 35}px)`;
    };
    joy.addEventListener("pointerdown", (e) => { jid = e.pointerId; joy.setPointerCapture(jid); jmove(e); });
    joy.addEventListener("pointermove", (e) => { if (e.pointerId === jid) jmove(e); });
    const jend = (e: PointerEvent) => { if (e.pointerId === jid) { jid = null; this.joy = { x: 0, y: 0 }; knob.style.transform = ""; } };
    joy.addEventListener("pointerup", jend); joy.addEventListener("pointercancel", jend);
    this.dom.addEventListener("pointerdown", (e) => { if (e.pointerType !== "mouse" && this.lookId === null) { this.lookId = e.pointerId; this.lastLook = { x: e.clientX, y: e.clientY }; } });
    this.dom.addEventListener("pointermove", (e) => { if (e.pointerId === this.lookId) { this.look((e.clientX - this.lastLook.x) * 1.6, (e.clientY - this.lastLook.y) * 1.6); this.lastLook = { x: e.clientX, y: e.clientY }; } });
    const lend = (e: PointerEvent) => { if (e.pointerId === this.lookId) this.lookId = null; };
    this.dom.addEventListener("pointerup", lend); this.dom.addEventListener("pointercancel", lend);
    this.disposers.push(() => joy.remove());
  }
  update(dt: number): void {
    const k = this.keys;
    let fx = (k.has("KeyW") || k.has("ArrowUp") ? 1 : 0) - (k.has("KeyS") || k.has("ArrowDown") ? 1 : 0) - this.joy.y;
    let rx = (k.has("KeyD") || k.has("ArrowRight") ? 1 : 0) - (k.has("KeyA") || k.has("ArrowLeft") ? 1 : 0) + this.joy.x;
    const m = Math.hypot(fx, rx); if (m > 1) { fx /= m; rx /= m; }
    const speed = k.has("ShiftLeft") || k.has("ShiftRight") ? this.opt.run : this.opt.walk;
    const sy = Math.sin(this.yaw), cy = Math.cos(this.yaw);
    const tx = (-sy * fx + cy * rx) * speed, tz = (-cy * fx - sy * rx) * speed;
    const a = 1 - Math.exp(-(this.opt.accel ?? 10) * dt);       // frame-rate-independent smoothing
    this.vx += (tx - this.vx) * a; this.vz += (tz - this.vz) * a;
    if (Math.abs(this.vx) + Math.abs(this.vz) > 1e-4) {
      const [nx, nz] = this.col.move(this.x, this.z, this.vx * dt, this.vz * dt);
      if (nx === this.x) this.vx = 0; if (nz === this.z) this.vz = 0;   // kill velocity into walls
      this.x = nx; this.z = nz;
    }
    this.apply();
  }
  private apply(): void {
    this.cam.position.set(this.x, this.opt.eye, this.z);
    this.cam.rotation.set(this.pitch, this.yaw, 0, "YXZ");
  }
  dispose(): void { this.disposers.forEach((d) => d()); }
}
