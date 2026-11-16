/**
 * routeRenderer.ts: 3D route visualisation and navigation HUD.
 *
 * Features:
 * - Flat instanced discs along the smoothed path every ~0.4 m at y=0.05
 * - depthTest=false, high renderOrder (999) to prevent z-fighting
 * - Synchronised with 2D minimap polyline
 * - Distance, approx indicator, ETA, and guided walk controls
 */
import * as THREE from "three";
import type { Minimap } from "./minimap";
import type { NavState } from "./navigator";

export class RouteRenderer {
  private discMesh: THREE.InstancedMesh | null = null;
  private discGeo: THREE.CylinderGeometry;
  private discMat: THREE.MeshBasicMaterial;
  private navHud: HTMLElement | null = null;
  private dummy = new THREE.Object3D();
  private disposers: (() => void)[] = [];

  constructor(
    private pathLayer: THREE.Group,
    private minimap: Minimap,
    private onAutoWalk: () => void,
    private onCancelNav: () => void
  ) {
    // Flat disc geometry: radius 0.12m, height 0.01m
    this.discGeo = new THREE.CylinderGeometry(0.12, 0.12, 0.01, 16);
    this.discMat = new THREE.MeshBasicMaterial({
      color: 0x4da3ff,
      depthTest: false,
      transparent: true,
      opacity: 0.85,
    });

    if (typeof document !== "undefined") {
      this.createHUD();
    }
  }

  private createHUD(): void {
    this.navHud = document.createElement("div");
    this.navHud.id = "nav-hud";
    this.navHud.style.position = "fixed";
    this.navHud.style.top = "52px";
    this.navHud.style.left = "50%";
    this.navHud.style.transform = "translateX(-50%)";
    this.navHud.style.background = "rgba(11, 13, 16, 0.9)";
    this.navHud.style.border = "1px solid #4da3ff";
    this.navHud.style.borderRadius = "8px";
    this.navHud.style.padding = "8px 14px";
    this.navHud.style.display = "none";
    this.navHud.style.alignItems = "center";
    this.navHud.style.gap = "12px";
    this.navHud.style.zIndex = "25";
    this.navHud.style.fontSize = "13px";
    this.navHud.style.color = "#ffffff";
    this.navHud.style.boxShadow = "0 4px 16px rgba(0,0,0,0.6)";

    const info = document.createElement("div");
    info.className = "nav-info";
    info.style.display = "flex";
    info.style.alignItems = "center";
    info.style.gap = "6px";
    this.navHud.appendChild(info);

    const btnWalk = document.createElement("button");
    btnWalk.className = "btn-walk";
    btnWalk.textContent = "🚶 Walk me there";
    btnWalk.style.background = "#1b3a5f";
    btnWalk.style.border = "1px solid #4da3ff";
    btnWalk.style.color = "#ffffff";
    btnWalk.style.borderRadius = "5px";
    btnWalk.style.padding = "4px 8px";
    btnWalk.style.cursor = "pointer";
    btnWalk.style.fontSize = "12px";
    btnWalk.onclick = () => this.onAutoWalk();
    this.navHud.appendChild(btnWalk);

    const btnCancel = document.createElement("button");
    btnCancel.textContent = "✕";
    btnCancel.title = "Cancel Navigation (Esc)";
    btnCancel.style.background = "transparent";
    btnCancel.style.border = "none";
    btnCancel.style.color = "#aaa";
    btnCancel.style.fontSize = "14px";
    btnCancel.style.cursor = "pointer";
    btnCancel.onclick = () => this.onCancelNav();
    this.navHud.appendChild(btnCancel);

    document.body.appendChild(this.navHud);
    this.disposers.push(() => this.navHud?.remove());
  }

  update(navState: NavState, isAutoWalking = false): void {
    if (navState.status === "idle") {
      this.clear();
      if (this.navHud) this.navHud.style.display = "none";
      return;
    }

    if (navState.status === "arrived") {
      this.clear();
      if (this.navHud) {
        this.navHud.style.display = "flex";
        const info = this.navHud.querySelector(".nav-info");
        if (info) info.innerHTML = `<span>🎉</span><b>Arrived at ${navState.targetName ?? "destination"}!</b>`;
        const btnWalk = this.navHud.querySelector(".btn-walk") as HTMLElement;
        if (btnWalk) btnWalk.style.display = "none";
      }
      return;
    }

    // Status is "routing"
    const wps = navState.waypoints;
    this.minimap.setPath(wps);
    this.render3DPath(wps);

    if (this.navHud) {
      this.navHud.style.display = "flex";
      const info = this.navHud.querySelector(".nav-info");
      const approxLabel = navState.isApproximateScale ? " <span style='opacity:0.75'>(approx)</span>" : "";
      if (info) {
        info.innerHTML = `<span>📍</span><b>${navState.targetName}</b> · <span>${navState.remainingDistance.toFixed(1)} m${approxLabel}</span> · <span style='opacity:0.8'>ETA ${navState.etaSeconds}s</span>`;
      }
      const btnWalk = this.navHud.querySelector(".btn-walk") as HTMLElement;
      if (btnWalk) {
        btnWalk.style.display = "block";
        btnWalk.textContent = isAutoWalking ? "⏸ Stop walking" : "🚶 Walk me there";
        btnWalk.style.background = isAutoWalking ? "#852b2b" : "#1b3a5f";
      }
    }
  }

  private render3DPath(waypoints: [number, number][]): void {
    if (this.discMesh) {
      this.pathLayer.remove(this.discMesh);
      this.discMesh.dispose();
      this.discMesh = null;
    }

    if (waypoints.length <= 1) return;

    // Resample waypoints every ~0.4 m
    const stepM = 0.4;
    const points: [number, number][] = [waypoints[0]];

    for (let i = 1; i < waypoints.length; i++) {
      const p0 = waypoints[i - 1];
      const p1 = waypoints[i];
      const segLen = Math.hypot(p1[0] - p0[0], p1[1] - p0[1]);
      const steps = Math.max(1, Math.floor(segLen / stepM));
      for (let s = 1; s <= steps; s++) {
        const t = s / steps;
        points.push([
          p0[0] + (p1[0] - p0[0]) * t,
          p0[1] + (p1[1] - p0[1]) * t,
        ]);
      }
    }

    const count = points.length;
    this.discMesh = new THREE.InstancedMesh(this.discGeo, this.discMat, count);
    this.discMesh.renderOrder = 999;

    for (let i = 0; i < count; i++) {
      const pt = points[i];
      this.dummy.position.set(pt[0], 0.05, pt[1]);
      this.dummy.scale.set(1, 1, 1);
      this.dummy.updateMatrix();
      this.discMesh.setMatrixAt(i, this.dummy.matrix);
    }
    this.discMesh.instanceMatrix.needsUpdate = true;
    this.pathLayer.add(this.discMesh);
  }

  clear(): void {
    this.minimap.setPath([]);
    if (this.discMesh) {
      this.pathLayer.remove(this.discMesh);
      this.discMesh.dispose();
      this.discMesh = null;
    }
  }

  dispose(): void {
    this.clear();
    this.discGeo.dispose();
    this.discMat.dispose();
    this.disposers.forEach((d) => d());
  }
}
