import { describe, it, expect, beforeEach, afterEach } from "vitest";
import * as THREE from "three";
import { FirstPersonControls, isInputFocused } from "./controls";
import { CollisionMap, type CollisionDoc } from "./collision";

describe("Controls and Keyboard Focus Guard", () => {
  let controls: FirstPersonControls;
  let cam: THREE.PerspectiveCamera;
  let dom: any;
  let col: CollisionMap;
  const listeners: Record<string, ((e: any) => void)[]> = {};

  const mockDoc: CollisionDoc = {
    version: 1,
    origin: [0, 0],
    cell_size: 0.1,
    size: [20, 20],
    encoding: "rle_row_major",
    grid: [[1, 400]],
    inflated: [[1, 400]],
    agent_radius_m: 0.25,
    floor_height: 0,
    bounds: { min: [0, 0, 0], max: [2, 2, 2] },
  };

  beforeEach(() => {
    for (const k of Object.keys(listeners)) delete listeners[k];

    (globalThis as any).matchMedia = () => ({ matches: false });
    (globalThis as any).window = {
      addEventListener: (type: string, fn: (e: any) => void) => {
        listeners[type] = listeners[type] || [];
        listeners[type].push(fn);
      },
      removeEventListener: (type: string, fn: (e: any) => void) => {
        if (!listeners[type]) return;
        listeners[type] = listeners[type].filter((f) => f !== fn);
      },
      matchMedia: () => ({ matches: false }),
    };

    dom = {
      addEventListener: () => {},
      removeEventListener: () => {},
      requestPointerLock: () => {},
    };

    (globalThis as any).document = {
      activeElement: null,
      pointerLockElement: null,
      addEventListener: () => {},
      removeEventListener: () => {},
    };

    cam = new THREE.PerspectiveCamera();
    col = new CollisionMap(mockDoc);
    controls = new FirstPersonControls(cam, dom as HTMLElement, col, { eye: 1.6, walk: 1.4, run: 3.0 });
    controls.setSpawn(1.0, 1.0, 0);
  });

  afterEach(() => {
    controls?.dispose();
  });

  it("isInputFocused detects focused input and textarea", () => {
    (globalThis as any).document.activeElement = { tagName: "INPUT" };
    expect(isInputFocused()).toBe(true);

    (globalThis as any).document.activeElement = { tagName: "TEXTAREA" };
    expect(isInputFocused()).toBe(true);

    (globalThis as any).document.activeElement = { tagName: "DIV", isContentEditable: true };
    expect(isInputFocused()).toBe(true);

    (globalThis as any).document.activeElement = { tagName: "DIV", isContentEditable: false };
    expect(isInputFocused()).toBe(false);

    (globalThis as any).document.activeElement = null;
    expect(isInputFocused()).toBe(false);
  });

  it("ignores movement keys when input is focused", () => {
    (globalThis as any).document.activeElement = { tagName: "INPUT" };

    // Simulate keydown on window
    const handlers = listeners["keydown"] || [];
    for (const h of handlers) {
      h({ code: "KeyW" });
      h({ code: "ArrowUp" });
    }

    expect(controls.keys.has("KeyW")).toBe(false);
    expect(controls.keys.has("ArrowUp")).toBe(false);
  });

  it("processes movement keys normally when input is not focused", () => {
    (globalThis as any).document.activeElement = null;

    const downHandlers = listeners["keydown"] || [];
    for (const h of downHandlers) {
      h({ code: "KeyW" });
    }

    expect(controls.keys.has("KeyW")).toBe(true);

    const upHandlers = listeners["keyup"] || [];
    for (const h of upHandlers) {
      h({ code: "KeyW" });
    }

    expect(controls.keys.has("KeyW")).toBe(false);
  });
});
