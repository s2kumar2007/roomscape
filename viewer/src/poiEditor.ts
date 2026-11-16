/**
 * poiEditor.ts: Dev-mode POI authoring tool (?edit=1).
 *
 * Features:
 * - Crosshair ray intersects floor plane (y=0)
 * - Walkable floor preview cursor
 * - "E" adds a POI with modal/prompt input
 * - "Delete" removes the last added POI
 * - Client-side validation before download
 * - "Export poi.json" triggers client-side download without server
 */
import * as THREE from "three";
import { snapPosition, type ValidatedPOI, type POIDoc } from "./poi";
import type { CollisionMap } from "./collision";
import type { Meta } from "./loader";
import { isInputFocused } from "./controls";

export class POIEditor {
  private active = false;
  private floorPlane = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0);
  private raycaster = new THREE.Raycaster();
  private cursorMesh: THREE.Mesh | null = null;
  private aimPos = new THREE.Vector3();
  private hasIntersection = false;
  private disposers: (() => void)[] = [];
  private editorHud: HTMLElement | null = null;

  private centerNdc = new THREE.Vector2(0, 0);

  constructor(
    private scene: THREE.Scene,
    private camera: THREE.PerspectiveCamera,
    private col: CollisionMap,
    private meta: Meta,
    private pois: ValidatedPOI[],
    private onPOIsChanged: (updatedPOIs: ValidatedPOI[]) => void
  ) {
    if (typeof window === "undefined") return;

    const q = new URLSearchParams(location.search).get("edit");
    if (q === "1") {
      this.active = true;
      this.init();
    }
  }

  isActive(): boolean {
    return this.active;
  }

  private init(): void {
    // 3D Visual cursor on floor plane
    const geo = new THREE.RingGeometry(0.12, 0.16, 24);
    geo.rotateX(-Math.PI / 2);
    const mat = new THREE.MeshBasicMaterial({
      color: 0x00e676,
      depthTest: false,
      transparent: true,
      opacity: 0.9,
    });
    this.cursorMesh = new THREE.Mesh(geo, mat);
    this.cursorMesh.renderOrder = 1000;
    this.scene.add(this.cursorMesh);
    this.disposers.push(() => {
      if (this.cursorMesh) {
        this.scene.remove(this.cursorMesh);
        geo.dispose();
        mat.dispose();
      }
    });

    this.createHUD();
    this.setupKeyListeners();
  }

  private createHUD(): void {
    this.editorHud = document.createElement("div");
    this.editorHud.id = "editor-hud";
    this.editorHud.style.position = "fixed";
    this.editorHud.style.bottom = "12px";
    this.editorHud.style.left = "12px";
    this.editorHud.style.background = "rgba(11, 13, 16, 0.95)";
    this.editorHud.style.border = "1px solid #ffab00";
    this.editorHud.style.borderRadius = "8px";
    this.editorHud.style.padding = "8px 14px";
    this.editorHud.style.zIndex = "40";
    this.editorHud.style.fontSize = "12px";
    this.editorHud.style.color = "#ffab00";
    this.editorHud.style.display = "flex";
    this.editorHud.style.flexDirection = "column";
    this.editorHud.style.gap = "6px";
    this.editorHud.style.boxShadow = "0 4px 16px rgba(0,0,0,0.6)";

    const title = document.createElement("div");
    title.innerHTML = `<b>🛠️ POI Authoring Mode (?edit=1)</b>`;
    this.editorHud.appendChild(title);

    const helpText = document.createElement("div");
    helpText.style.color = "#ccc";
    helpText.textContent = `Aim crosshair at floor. Press 'E' to add POI, 'Delete' to undo. (${this.pois.length} POIs)`;
    this.editorHud.appendChild(helpText);

    const btnRow = document.createElement("div");
    btnRow.style.display = "flex";
    btnRow.style.gap = "8px";
    btnRow.style.marginTop = "4px";

    const btnAdd = document.createElement("button");
    btnAdd.textContent = "+ Add POI (E)";
    btnAdd.style.background = "#2a3b2a";
    btnAdd.style.border = "1px solid #00e676";
    btnAdd.style.color = "#00e676";
    btnAdd.style.borderRadius = "4px";
    btnAdd.style.padding = "4px 8px";
    btnAdd.style.cursor = "pointer";
    btnAdd.onclick = () => this.promptAddPOI();
    btnRow.appendChild(btnAdd);

    const btnUndo = document.createElement("button");
    btnUndo.textContent = "Delete Last";
    btnUndo.style.background = "#3b2a2a";
    btnUndo.style.border = "1px solid #ff5252";
    btnUndo.style.color = "#ff5252";
    btnUndo.style.borderRadius = "4px";
    btnUndo.style.padding = "4px 8px";
    btnUndo.style.cursor = "pointer";
    btnUndo.onclick = () => this.deleteLastPOI();
    btnRow.appendChild(btnUndo);

    const btnExport = document.createElement("button");
    btnExport.textContent = "💾 Export poi.json";
    btnExport.style.background = "#1b3a5f";
    btnExport.style.border = "1px solid #4da3ff";
    btnExport.style.color = "#ffffff";
    btnExport.style.borderRadius = "4px";
    btnExport.style.padding = "4px 8px";
    btnExport.style.cursor = "pointer";
    btnExport.onclick = () => this.exportPOIJson();
    btnRow.appendChild(btnExport);

    this.editorHud.appendChild(btnRow);
    document.body.appendChild(this.editorHud);
    this.disposers.push(() => this.editorHud?.remove());
  }

  private setupKeyListeners(): void {
    const onKey = (e: KeyboardEvent) => {
      if (!this.active || isInputFocused()) return;

      if (e.code === "KeyE") {
        e.preventDefault();
        this.promptAddPOI();
      } else if (e.code === "Delete" || e.key === "Delete") {
        e.preventDefault();
        this.deleteLastPOI();
      }
    };

    window.addEventListener("keydown", onKey);
    this.disposers.push(() => window.removeEventListener("keydown", onKey));
  }

  update(): void {
    if (!this.active || !this.cursorMesh) return;

    // Raycast crosshair (0, 0 in NDC) to floor plane y=0
    this.raycaster.setFromCamera(this.centerNdc, this.camera);
    const hit = this.raycaster.ray.intersectPlane(this.floorPlane, this.aimPos);

    if (hit) {
      this.hasIntersection = true;
      this.cursorMesh.visible = true;
      this.cursorMesh.position.set(hit.x, 0.02, hit.z);

      const [snapOk, , , dist] = snapPosition(this.col, hit.x, hit.z, 1.0);
      const isWalkable = snapOk && dist <= 1.0;
      (this.cursorMesh.material as THREE.MeshBasicMaterial).color.setHex(isWalkable ? 0x00e676 : 0xff5252);
    } else {
      this.hasIntersection = false;
      this.cursorMesh.visible = false;
    }
  }

  promptAddPOI(): void {
    if (!this.hasIntersection) {
      alert("Crosshair must intersect the floor plane (y=0).");
      return;
    }

    const rawX = this.aimPos.x;
    const rawZ = this.aimPos.z;

    const bMin = this.meta?.bounds?.min ?? [-Infinity, -Infinity, -Infinity];
    const bMax = this.meta?.bounds?.max ?? [Infinity, Infinity, Infinity];
    if (rawX < bMin[0] || rawX > bMax[0] || rawZ < bMin[2] || rawZ > bMax[2]) {
      alert(`Position (${rawX.toFixed(2)}, ${rawZ.toFixed(2)}) is outside scene bounds.`);
      return;
    }

    const [snapOk, sx, sz, snapDist] = snapPosition(this.col, rawX, rawZ, 1.0);
    if (!snapOk || snapDist > 1.0) {
      alert(`Position (${rawX.toFixed(2)}, ${rawZ.toFixed(2)}) is more than 1.0 m from walkable space.`);
      return;
    }

    const defaultName = `Point of Interest ${this.pois.length + 1}`;
    const name = prompt("POI Name (e.g. Conference Table):", defaultName);
    if (!name || !name.trim()) return;

    const category = prompt("Category (e.g. desk, door, seating, display, amenity):", "desk") || "general";
    const aliasesRaw = prompt("Aliases (comma-separated, optional):", "") || "";
    const aliases = aliasesRaw
      .split(",")
      .map((a) => a.trim())
      .filter((a) => a.length > 0);

    const slug = name
      .toLowerCase()
      .replace(/[^\w\s-]/g, "")
      .trim()
      .replace(/\s+/g, "_");
    const id = `${slug || "poi"}_${Date.now().toString(36).slice(-4)}`;

    const newPOI: ValidatedPOI = {
      id,
      name: name.trim(),
      category: category.trim(),
      aliases,
      position: [Number(rawX.toFixed(3)), Number(rawZ.toFixed(3))],
      worldPos: [Number(sx.toFixed(3)), Number(sz.toFixed(3))],
      originalPos: [Number(rawX.toFixed(3)), Number(rawZ.toFixed(3))],
      snapDist: Number(snapDist.toFixed(3)),
    };

    this.pois.push(newPOI);
    this.onPOIsChanged(this.pois);
    this.updateHUDText();
  }

  deleteLastPOI(): void {
    if (this.pois.length === 0) return;
    const removed = this.pois.pop();
    this.onPOIsChanged(this.pois);
    this.updateHUDText();
    if (removed) {
      console.log(`[Authoring] Removed POI: ${removed.name} (${removed.id})`);
    }
  }

  private updateHUDText(): void {
    if (!this.editorHud) return;
    const help = this.editorHud.querySelector("div:nth-child(2)");
    if (help) {
      help.textContent = `Aim crosshair at floor. Press 'E' to add POI, 'Delete' to undo. (${this.pois.length} POIs)`;
    }
  }

  exportPOIJson(): void {
    const doc: POIDoc = {
      version: 1,
      description: "Authored POI dataset for Roomscape digital twin viewer",
      pois: this.pois.map((p) => ({
        id: p.id,
        name: p.name,
        category: p.category,
        aliases: p.aliases,
        position: p.position,
        description: p.description,
        icon: p.icon,
      })),
    };

    const jsonText = JSON.stringify(doc, null, 2);
    const blob = new Blob([jsonText], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "poi.json";
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    console.log(`[Authoring] Exported ${doc.pois.length} POIs to poi.json.`);
  }

  dispose(): void {
    this.disposers.forEach((d) => d());
  }
}
