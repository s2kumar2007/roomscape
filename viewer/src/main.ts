import * as THREE from "three";
import type { SplatMesh } from "@sparkjsdev/spark";
import { CollisionMap } from "./collision";
import { FirstPersonControls } from "./controls";
import { loadScene } from "./loader";
import { Minimap } from "./minimap";
import { UI } from "./ui";

declare global { interface Window { nammaSpace?: Record<string, unknown>; __nammaReady?: boolean; __nammaStats?: { fps: number; pixelRatio: number; loadMs: number; gaussians: number } } }

async function main(): Promise<void> {
  const t0 = performance.now();
  let reset = () => {};
  const ui = new UI(() => reset());
  const sparkP = import("@sparkjsdev/spark");           // lazy chunk: loading screen shows immediately
  const loaded = await loadScene((f, l) => ui.progress(f, l));
  const { SparkRenderer, SplatMesh: SplatMeshCls, SplatFileType } = await sparkP;
  const { meta, collision, bytes } = loaded;
  ui.progress(0.97, "Preparing renderer");

  const renderer = new THREE.WebGLRenderer({ antialias: false, powerPreference: "high-performance" });   // AA hurts splat perf (Spark docs)
  const maxRatio = Math.min(window.devicePixelRatio || 1, 2);
  let ratio = Math.min(maxRatio, 1.5);
  renderer.setPixelRatio(ratio); renderer.setSize(window.innerWidth, window.innerHeight);
  document.getElementById("app")!.appendChild(renderer.domElement);
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(70, window.innerWidth / window.innerHeight, 0.05, 200);
  const spark = new SparkRenderer({ renderer }); scene.add(spark);

  const mesh = await new Promise<SplatMesh>((resolve, reject) => {
    try {
      const m: SplatMesh = new SplatMeshCls({ fileBytes: bytes, fileType: meta.format === "ply" ? SplatFileType.PLY : SplatFileType.SPLAT, onLoad: () => resolve(m) });
      scene.add(m);
    } catch (e) { reject(e); }
  });

  // ROUND 2 HOOKS: add POI markers to poiLayer and A* path lines to pathLayer. Both are exposed on window.nammaSpace.
  const poiLayer = new THREE.Group(); poiLayer.name = "poiLayer"; scene.add(poiLayer);
  const pathLayer = new THREE.Group(); pathLayer.name = "pathLayer"; scene.add(pathLayer);

  const col = new CollisionMap(collision);
  const controls = new FirstPersonControls(camera, renderer.domElement, col, { eye: meta.eye_height, walk: meta.walk_speed, run: meta.run_speed });
  controls.setSpawn(meta.spawn.position[0], meta.spawn.position[2], meta.spawn.yaw);
  reset = () => controls.reset();
  const minimap = new Minimap(document.getElementById("minimap") as HTMLCanvasElement, col);
  if (meta.scale.approximate) ui.banner("Scale is approximate (no marker detected)");
  window.nammaSpace = { scene, camera, poiLayer, pathLayer, collision: col, meta, controls, minimap, mesh, renderer };

  const onResize = () => { camera.aspect = window.innerWidth / window.innerHeight; camera.updateProjectionMatrix(); renderer.setSize(window.innerWidth, window.innerHeight); };
  window.addEventListener("resize", onResize);

  // frame loop + adaptive resolution (drop res if FPS < 30 for 2 s; recover slowly when fast)
  let last = performance.now(), acc = 0, frames = 0, lowFor = 0, highFor = 0, fps = 60;
  renderer.setAnimationLoop(() => {
    const now = performance.now(); const dt = Math.min(0.1, (now - last) / 1000); last = now;
    controls.update(dt); minimap.draw(controls.x, controls.z, controls.yaw);
    renderer.render(scene, camera);
    acc += dt; frames++;
    if (acc >= 0.5) {
      fps = frames / acc; acc = 0; frames = 0;
      lowFor = fps < 30 ? lowFor + 0.5 : 0; highFor = fps > 58 ? highFor + 0.5 : 0;
      if (lowFor >= 2 && ratio > 0.5) { ratio = Math.max(0.5, ratio - 0.25); renderer.setPixelRatio(ratio); renderer.setSize(window.innerWidth, window.innerHeight); lowFor = 0; }
      else if (highFor >= 6 && ratio < maxRatio) { ratio = Math.min(maxRatio, ratio + 0.25); renderer.setPixelRatio(ratio); renderer.setSize(window.innerWidth, window.innerHeight); highFor = 0; }
      ui.fps(fps, ratio / maxRatio);
      window.__nammaStats = { fps, pixelRatio: ratio, loadMs: window.__nammaStats?.loadMs ?? 0, gaussians: meta.gaussian_count };
    }
  });
  const loadMs = performance.now() - t0;
  window.__nammaStats = { fps: 0, pixelRatio: ratio, loadMs, gaussians: meta.gaussian_count };
  window.__nammaReady = true; ui.progress(1, "Ready"); ui.done();

  window.addEventListener("pagehide", () => {     // free GPU memory
    renderer.setAnimationLoop(null); controls.dispose(); window.removeEventListener("resize", onResize);
    scene.remove(mesh); mesh.dispose(); spark.dispose?.(); renderer.dispose();
  });
}

main().catch((e: unknown) => { console.error(e); new UI(() => {}).error(`${e instanceof Error ? e.message : String(e)}\n\nCheck that scene/meta.json, collision.json and the scene file are served (see docs/DEPLOY.md).`); });
