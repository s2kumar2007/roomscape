import { describe, it, expect, beforeEach, afterEach } from "vitest";
import * as THREE from "three";
import { CollisionMap, type CollisionDoc } from "./collision";
import {
  validateAndSnapPOIs,
  checkRawGridLineOfSight,
  POILabelOverlay,
  type ValidatedPOI,
} from "./poi";
import type { Meta } from "./loader";
import sceneCollision from "../public/scene/collision.json";

describe("POI validation, snapping, and overlay culling", () => {
  const col = new CollisionMap(sceneCollision as unknown as CollisionDoc);
  const mockMeta: Meta = {
    version: 1,
    scene_file: "scene.splat",
    format: "splat",
    gaussian_count: 50000,
    size_mb: 1.5,
    spawn: { position: [0.65, 1.6, -4.25], yaw: 0 },
    eye_height: 1.6,
    walk_speed: 1.4,
    run_speed: 3.0,
    bounds: {
      min: [-0.938, -0.017, -8.2],
      max: [6.152, 2.635, -1.693],
    },
    scale: { method: "apriltag", factor: 2.7, approximate: false, confidence: 0.99 },
    collision_file: "collision.json",
  };

  it("validates and snaps valid POIs", () => {
    const rawPOIs = [
      {
        id: "entrance",
        name: "Main Entrance",
        category: "door",
        aliases: ["exit"],
        position: [0.65, -4.25],
      },
      {
        id: "desk",
        name: "Work Desk",
        category: "desk",
        position: [1.5, -3.5],
      },
    ];

    const { pois, ignoredCount } = validateAndSnapPOIs(rawPOIs, mockMeta, col);
    expect(ignoredCount).toBe(0);
    expect(pois.length).toBe(2);
    expect(pois[0].id).toBe("entrance");
    expect(pois[0].snapDist).toBeLessThanOrEqual(1.0);
  });

  it("ignores duplicate IDs, out of bounds POIs, and unsnappable POIs", () => {
    const rawPOIs = [
      { id: "p1", name: "Valid 1", position: [0.65, -4.25] },
      { id: "p1", name: "Duplicate ID", position: [1.5, -3.5] }, // dup id
      { id: "p2", name: "Out of Bounds", position: [99.0, 99.0] }, // out of bounds
      { id: "p3", name: "Way in blocked wall", position: [-0.9, -8.1] }, // too far from walkable (>1m)
      { id: "", name: "Empty ID", position: [0.65, -4.25] },
      null,
    ];

    const { pois, ignoredCount } = validateAndSnapPOIs(rawPOIs, mockMeta, col);
    expect(pois.length).toBe(1);
    expect(pois[0].id).toBe("p1");
    expect(ignoredCount).toBe(5);
  });

  it("detects wall occlusion on raw grid correctly", () => {
    // Look from camera at spawn (0.65, -4.25) to a point clearly behind a wall
    // Check line of sight to a nearby open point
    const canSeeOpen = checkRawGridLineOfSight(col, 0.65, -4.25, 1.5, -3.5);
    expect(canSeeOpen).toBe(true);

    // Coordinate through the known center obstacle / wall column:
    // Cell (30, 30) or cross-room across solid wall
    const wallOccluded = checkRawGridLineOfSight(col, 0.0, -2.0, 5.0, -7.0);
    expect(wallOccluded).toBe(false);
  });

  describe("POILabelOverlay DOM projection", () => {
    let overlay: POILabelOverlay;
    let camera: THREE.PerspectiveCamera;
    const createdElements: any[] = [];

    beforeEach(() => {
      createdElements.length = 0;
      const makeMockElement = (tag: string) => {
        const el: any = {
          tagName: tag,
          style: {},
          children: [] as any[],
          innerHTML: "",
          appendChild: (child: any) => {
            el.children.push(child);
            createdElements.push(child);
            return child;
          },
          remove: () => {},
          addEventListener: () => {},
          querySelector: (sel: string) => ({ textContent: "" }),
        };
        return el;
      };

      (globalThis as any).document = {
        createElement: (tag: string) => makeMockElement(tag),
        body: makeMockElement("body"),
      };
      (globalThis as any).window = {
        innerWidth: 1920,
        innerHeight: 1080,
      };

      overlay = new POILabelOverlay((globalThis as any).document.body);
      camera = new THREE.PerspectiveCamera(70, 16 / 9, 0.1, 100);
      camera.position.set(0.65, 1.6, -4.25);
      camera.lookAt(1.5, 1.6, -3.5);
      camera.updateMatrixWorld();
    });

    afterEach(() => {
      overlay?.dispose();
    });

    it("displays in-front labels and hides rear labels", () => {
      const testPois: ValidatedPOI[] = [
        {
          id: "front",
          name: "In Front",
          category: "desk",
          position: [1.5, -3.5],
          worldPos: [1.5, -3.5],
          originalPos: [1.5, -3.5],
          snapDist: 0,
        },
        {
          id: "behind",
          name: "Behind Cam",
          category: "door",
          position: [0.65, -6.5], // behind camera facing +X, -Z
          worldPos: [0.65, -6.5],
          originalPos: [0.65, -6.5],
          snapDist: 0,
        },
      ];

      overlay.setPOIs(testPois);
      overlay.update(camera, col, testPois);

      // The 2 POI label elements were created inside the container
      const frontEl = createdElements.find((e) => e.innerHTML.includes("In Front"));
      const behindEl = createdElements.find((e) => e.innerHTML.includes("Behind Cam"));

      expect(frontEl).toBeDefined();
      expect(behindEl).toBeDefined();
      expect(frontEl.style.display).toBe("block");
      expect(behindEl.style.display).toBe("none");
    });
  });
});
