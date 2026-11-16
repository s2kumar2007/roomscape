/**
 * poi.ts: POI data loading, validation, snapping, and DOM-overlay 3D-projected labels.
 *
 * Features:
 * - Graceful degradation: invalid POIs ignored, missing poi.json handled silently
 * - Snapping to walkable cell within 1 m
 * - Frustum & camera rear culling
 * - Distance-based fading (fades beyond 6m, hidden beyond 16m)
 * - Wall occlusion culling using raw BLOCKED collision grid (never shows through walls)
 * - 60-label cap and 2D screen overlap suppression
 */
import * as THREE from "three";
import { BLOCKED, FLOOR, type CollisionMap } from "./collision";
import type { Meta } from "./loader";

export interface POIDef {
  id: string;
  name: string;
  category: string;
  aliases?: string[];
  position: [number, number];
  description?: string;
  icon?: string;
}

export interface ValidatedPOI extends POIDef {
  worldPos: [number, number];
  originalPos: [number, number];
  snapDist: number;
}

export interface POIDoc {
  version: number;
  pois: POIDef[];
  description?: string;
}

export interface LoadPOIResult {
  pois: ValidatedPOI[];
  ignoredCount: number;
  totalFound: number;
}

export function snapPosition(
  col: CollisionMap,
  x: number,
  z: number,
  maxRadiusM = 1.0
): [boolean, number, number, number] {
  const cx = Math.floor((x - col.ox) / col.cell);
  const cz = Math.floor((z - col.oz) / col.cell);

  if (cx >= 0 && cz >= 0 && cx < col.nx && cz < col.nz && col.inflated[cz * col.nx + cx] === FLOOR) {
    const wx = col.ox + (cx + 0.5) * col.cell;
    const wz = col.oz + (cz + 0.5) * col.cell;
    return [true, wx, wz, Math.hypot(x - wx, z - wz)];
  }

  const maxCells = Math.ceil(maxRadiusM / col.cell);
  let bestX = -1;
  let bestZ = -1;
  let bestDistSq = maxRadiusM * maxRadiusM;

  for (let diz = -maxCells; diz <= maxCells; diz++) {
    const niz = cz + diz;
    if (niz < 0 || niz >= col.nz) continue;
    for (let dix = -maxCells; dix <= maxCells; dix++) {
      const nix = cx + dix;
      if (nix < 0 || nix >= col.nx) continue;
      if (col.inflated[niz * col.nx + nix] === FLOOR) {
        const wx = col.ox + (nix + 0.5) * col.cell;
        const wz = col.oz + (niz + 0.5) * col.cell;
        const dSq = (wx - x) ** 2 + (wz - z) ** 2;
        if (dSq <= bestDistSq) {
          bestDistSq = dSq;
          bestX = wx;
          bestZ = wz;
        }
      }
    }
  }

  if (bestX !== -1) {
    return [true, bestX, bestZ, Math.sqrt(bestDistSq)];
  }
  return [false, x, z, Infinity];
}

export function validateAndSnapPOIs(
  rawList: unknown[],
  meta: Meta,
  col: CollisionMap
): { pois: ValidatedPOI[]; ignoredCount: number } {
  const pois: ValidatedPOI[] = [];
  const seenIds = new Set<string>();
  let ignoredCount = 0;

  const minX = meta.bounds?.min?.[0] ?? -Infinity;
  const maxX = meta.bounds?.max?.[0] ?? Infinity;
  const minZ = meta.bounds?.min?.[2] ?? -Infinity;
  const maxZ = meta.bounds?.max?.[2] ?? Infinity;

  for (const item of rawList) {
    if (!item || typeof item !== "object") {
      ignoredCount++;
      continue;
    }
    const raw = item as Record<string, unknown>;
    const id = typeof raw.id === "string" ? raw.id.trim() : "";
    const name = typeof raw.name === "string" ? raw.name.trim() : "";
    const category = typeof raw.category === "string" ? raw.category.trim() : "general";
    const aliases = Array.isArray(raw.aliases) ? raw.aliases.filter((a): a is string => typeof a === "string") : [];
    const description = typeof raw.description === "string" ? raw.description : undefined;
    const icon = typeof raw.icon === "string" ? raw.icon : undefined;

    if (!id || !name || seenIds.has(id)) {
      ignoredCount++;
      continue;
    }

    if (!Array.isArray(raw.position) || raw.position.length !== 2) {
      ignoredCount++;
      continue;
    }
    const x = Number(raw.position[0]);
    const z = Number(raw.position[1]);
    if (!Number.isFinite(x) || !Number.isFinite(z)) {
      ignoredCount++;
      continue;
    }

    // Check bounds
    if (x < minX || x > maxX || z < minZ || z > maxZ) {
      ignoredCount++;
      continue;
    }

    // Snap to walkable cell within 1.0 m
    const [snapOk, sx, sz, snapDist] = snapPosition(col, x, z, 1.0);
    if (!snapOk || snapDist > 1.0) {
      ignoredCount++;
      continue;
    }

    seenIds.add(id);
    pois.push({
      id,
      name,
      category,
      aliases,
      position: [x, z],
      worldPos: [sx, sz],
      originalPos: [x, z],
      snapDist,
      description,
      icon,
    });
  }

  return { pois, ignoredCount };
}

export async function loadPOIs(base: string, meta: Meta, col: CollisionMap): Promise<LoadPOIResult> {
  const url = base + "poi.json";
  try {
    const res = await fetch(url);
    if (!res.ok) {
      return { pois: [], ignoredCount: 0, totalFound: 0 };
    }
    const doc = (await res.json()) as POIDoc;
    if (!doc || !Array.isArray(doc.pois)) {
      return { pois: [], ignoredCount: 0, totalFound: 0 };
    }
    const { pois, ignoredCount } = validateAndSnapPOIs(doc.pois, meta, col);
    return { pois, ignoredCount, totalFound: doc.pois.length };
  } catch {
    // Graceful degradation on network or parse error
    return { pois: [], ignoredCount: 0, totalFound: 0 };
  }
}

/** Check line of sight across the raw BLOCKED grid (BLOCKED = 2). */
export function checkRawGridLineOfSight(
  col: CollisionMap,
  x0: number,
  z0: number,
  x1: number,
  z1: number
): boolean {
  const u0 = (x0 - col.ox) / col.cell;
  const v0 = (z0 - col.oz) / col.cell;
  const u1 = (x1 - col.ox) / col.cell;
  const v1 = (z1 - col.oz) / col.cell;

  const ix = Math.floor(u0);
  const iz = Math.floor(v0);
  const ixEnd = Math.floor(u1);
  const izEnd = Math.floor(v1);

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
    if (tMaxX < tMaxZ) {
      currX += stepX;
      tMaxX += tDeltaX;
    } else {
      currZ += stepZ;
      tMaxZ += tDeltaZ;
    }

    if (currX >= 0 && currZ >= 0 && currX < col.nx && currZ < col.nz) {
      if (col.grid[currZ * col.nx + currX] === BLOCKED) {
        return false; // occluded by wall
      }
    }
  }

  return true;
}

export class POILabelOverlay {
  private container: HTMLElement | null = null;
  private elements = new Map<string, HTMLElement>();
  private disposers: (() => void)[] = [];
  private tempVec = new THREE.Vector3();
  private camDir = new THREE.Vector3();

  constructor(parent?: HTMLElement) {
    if (typeof document !== "undefined") {
      const p = parent ?? document.body;
      this.container = document.createElement("div");
      this.container.id = "poi-overlay";
      this.container.style.position = "fixed";
      this.container.style.inset = "0";
      this.container.style.pointerEvents = "none";
      this.container.style.overflow = "hidden";
      this.container.style.zIndex = "15";
      p.appendChild(this.container);
      this.disposers.push(() => this.container?.remove());
    }
  }

  setPOIs(pois: ValidatedPOI[], onSelectPOI?: (poi: ValidatedPOI) => void): void {
    if (!this.container || typeof document === "undefined") return;
    this.container.innerHTML = "";
    this.elements.clear();

    for (const poi of pois) {
      const el = document.createElement("div");
      el.className = "poi-label";
      el.style.position = "absolute";
      el.style.display = "none";
      el.style.pointerEvents = "auto";
      el.style.cursor = "pointer";
      el.style.transform = "translate(-50%, -100%)";
      el.style.background = "rgba(16, 22, 34, 0.85)";
      el.style.border = "1px solid rgba(77, 163, 255, 0.4)";
      el.style.borderRadius = "6px";
      el.style.padding = "4px 8px";
      el.style.color = "#ffffff";
      el.style.fontSize = "12px";
      el.style.whiteSpace = "nowrap";
      el.style.backdropFilter = "blur(4px)";
      el.style.userSelect = "none";
      el.style.transition = "opacity 0.2s, transform 0.1s";
      el.style.boxShadow = "0 2px 6px rgba(0,0,0,0.5)";

      const icon = poi.icon ? `<span style="margin-right:4px;">${this.getCategoryEmoji(poi.category)}</span>` : "";
      el.innerHTML = `${icon}<b>${poi.name}</b><span class="poi-dist" style="margin-left:6px; opacity:0.75; font-size:11px;"></span>`;

      el.addEventListener("click", (e) => {
        e.stopPropagation();
        onSelectPOI?.(poi);
      });

      this.container.appendChild(el);
      this.elements.set(poi.id, el);
    }
  }

  private getCategoryEmoji(cat: string): string {
    switch (cat.toLowerCase()) {
      case "door":
      case "exit":
        return "🚪";
      case "desk":
      case "workstation":
        return "💻";
      case "display":
      case "screen":
        return "📊";
      case "seating":
      case "chair":
      case "lounge":
        return "🛋️";
      case "amenity":
      case "coffee":
        return "☕";
      case "view":
      case "window":
        return "🪟";
      default:
        return "📍";
    }
  }

  update(
    camera: THREE.PerspectiveCamera,
    col: CollisionMap,
    pois: ValidatedPOI[],
    labelHeight = 1.0,
    maxLabels = 60
  ): void {
    if (pois.length === 0) return;

    const width = window.innerWidth;
    const height = window.innerHeight;
    const camX = camera.position.x;
    const camZ = camera.position.z;

    camera.getWorldDirection(this.camDir);

    // Filter and sort visible candidates by distance
    interface Candidate {
      poi: ValidatedPOI;
      el: HTMLElement;
      dist: number;
      screenX: number;
      screenY: number;
      opacity: number;
    }

    const candidates: Candidate[] = [];

    for (const poi of pois) {
      const el = this.elements.get(poi.id);
      if (!el) continue;

      const px = poi.worldPos[0];
      const pz = poi.worldPos[1];
      const dist = Math.hypot(camX - px, camZ - pz);

      // Max view distance 16 m
      if (dist > 16.0) {
        el.style.display = "none";
        continue;
      }

      // Check if behind camera
      const toPoiX = px - camX;
      const toPoiZ = pz - camZ;
      const dot = toPoiX * this.camDir.x + toPoiZ * this.camDir.z;
      if (dot <= 0.1) {
        el.style.display = "none";
        continue;
      }

      // Line of sight occlusion check on raw BLOCKED grid (no seeing through walls)
      if (!checkRawGridLineOfSight(col, camX, camZ, px, pz)) {
        el.style.display = "none";
        continue;
      }

      // 3D project
      this.tempVec.set(px, labelHeight, pz);
      this.tempVec.project(camera);

      // Outside NDC frustum
      if (this.tempVec.z > 1.0 || this.tempVec.x < -1.1 || this.tempVec.x > 1.1 || this.tempVec.y < -1.1 || this.tempVec.y > 1.1) {
        el.style.display = "none";
        continue;
      }

      const screenX = ((this.tempVec.x + 1) * 0.5) * width;
      const screenY = ((-this.tempVec.y + 1) * 0.5) * height;

      // Distance fade: full opacity <= 6m, fades to 0 at 16m
      const opacity = dist <= 6.0 ? 1.0 : Math.max(0.15, 1.0 - (dist - 6.0) / 10.0);

      candidates.push({ poi, el, dist, screenX, screenY, opacity });
    }

    // Sort by distance (closest first)
    candidates.sort((a, b) => a.dist - b.dist);

    // Limit to maxLabels and simple overlap prevention
    const placedBoxes: { x1: number; y1: number; x2: number; y2: number }[] = [];
    const chosen = candidates.slice(0, maxLabels);

    // Hide any unchosen candidates
    for (let i = maxLabels; i < candidates.length; i++) {
      candidates[i].el.style.display = "none";
    }

    for (const c of chosen) {
      const approxW = 100;
      const approxH = 26;
      const box = {
        x1: c.screenX - approxW / 2,
        y1: c.screenY - approxH,
        x2: c.screenX + approxW / 2,
        y2: c.screenY,
      };

      // Check overlap with closer placed labels
      let overlaps = false;
      for (const p of placedBoxes) {
        if (!(box.x2 < p.x1 || box.x1 > p.x2 || box.y2 < p.y1 || box.y1 > p.y2)) {
          overlaps = true;
          break;
        }
      }

      if (overlaps) {
        c.el.style.display = "none";
        continue;
      }

      placedBoxes.push(box);
      c.el.style.display = "block";
      c.el.style.left = `${c.screenX.toFixed(1)}px`;
      c.el.style.top = `${c.screenY.toFixed(1)}px`;
      c.el.style.opacity = c.opacity.toFixed(2);

      const distSpan = c.el.querySelector(".poi-dist");
      if (distSpan) {
        distSpan.textContent = `${c.dist.toFixed(1)}m`;
      }
    }
  }

  dispose(): void {
    this.disposers.forEach((d) => d());
    this.elements.clear();
  }
}
