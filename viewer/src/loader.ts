/** Scene loading with real byte-level progress. Base URL: ?scene=<url> > VITE_SCENE_BASE > ./scene/ */
import type { CollisionDoc } from "./collision";

export interface Meta {
  version: number; scene_file: string; format: "splat" | "ply"; gaussian_count: number; size_mb: number;
  spawn: { position: [number, number, number]; yaw: number }; eye_height: number; walk_speed: number; run_speed: number;
  bounds: { min: number[]; max: number[] };
  scale: { method: string; factor: number; approximate: boolean; confidence: number };
  collision_file: string;
  mock?: boolean;
}
export interface LoadedScene { meta: Meta; collision: CollisionDoc; bytes: Uint8Array; base: string }

export function sceneBase(): string {
  const q = new URLSearchParams(location.search).get("scene");
  const b = q ?? (import.meta.env.VITE_SCENE_BASE as string | undefined) ?? "./scene/";
  return b.endsWith("/") ? b : b + "/";
}

async function getJSON<T>(url: string): Promise<T> {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`Failed to load ${url} (HTTP ${r.status})`);
  return (await r.json()) as T;
}

export async function loadScene(onProgress: (frac: number, label: string) => void): Promise<LoadedScene> {
  const base = sceneBase();
  onProgress(0, "Reading scene info");
  const meta = await getJSON<Meta>(base + "meta.json");
  const collision = await getJSON<CollisionDoc>(base + meta.collision_file);
  const r = await fetch(base + meta.scene_file);
  if (!r.ok || !r.body) throw new Error(`Failed to load ${meta.scene_file} (HTTP ${r.status})`);
  const total = Number(r.headers.get("content-length")) || meta.size_mb * 1e6;
  const reader = r.body.getReader(); const chunks: Uint8Array[] = []; let got = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    chunks.push(value); got += value.length;
    onProgress(Math.min(0.95, got / total), `Downloading ${(got / 1e6).toFixed(1)} / ${(total / 1e6).toFixed(1)} MB`);
  }
  const bytes = new Uint8Array(got); let o = 0;
  for (const c of chunks) { bytes.set(c, o); o += c.length; }
  return { meta, collision, bytes, base };
}
