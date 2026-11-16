import { describe, it, expect } from "vitest";
import { Navigator } from "./navigator";
import { AStarFinder } from "./astar";
import { CollisionMap, type CollisionDoc } from "./collision";

describe("Navigator State Machine", () => {
  const mockDoc: CollisionDoc = {
    version: 1,
    origin: [0, 0],
    cell_size: 0.1,
    size: [50, 50],
    encoding: "rle_row_major",
    grid: [[1, 2500]],
    inflated: [[1, 2500]],
    agent_radius_m: 0.25,
    floor_height: 0,
    bounds: { min: [0, 0, 0], max: [5, 2, 5] },
  };

  const col = new CollisionMap(mockDoc);
  const astar = new AStarFinder(col);

  it("starts in idle state", () => {
    const nav = new Navigator(astar, 1.4, false);
    const state = nav.update([1.0, 1.0]);
    expect(state.status).toBe("idle");
    expect(state.waypoints.length).toBe(0);
    expect(state.target).toBeNull();
  });

  it("transitions to routing upon setting valid goal", () => {
    const nav = new Navigator(astar, 1.4, true);
    const ok = nav.setGoal([1.0, 1.0], [4.0, 1.0], "Test Target");
    expect(ok).toBe(true);

    const state = nav.update([1.0, 1.0]);
    expect(state.status).toBe("routing");
    expect(state.targetName).toBe("Test Target");
    expect(state.waypoints.length).toBeGreaterThan(0);
    expect(state.remainingDistance).toBeGreaterThan(2.5);
    expect(state.etaSeconds).toBeGreaterThan(0);
    expect(state.isApproximateScale).toBe(true);
  });

  it("transitions to arrived when within 0.6 m radius", () => {
    const nav = new Navigator(astar, 1.4, false);
    nav.setGoal([1.0, 1.0], [4.0, 1.0], "Exit");

    // Move player right next to goal (e.g. at 3.9, 1.0 => 0.1m away)
    const state = nav.update([3.95, 1.0]);
    expect(state.status).toBe("arrived");
    expect(state.remainingDistance).toBe(0);
  });

  it("reroutes when more than 1.5 m off-path", () => {
    const nav = new Navigator(astar, 1.4, false);
    nav.setGoal([1.0, 1.0], [4.0, 1.0], "Exit");

    // Waypoints are along Z ~ 1.0. Move player far off to Z = 3.5 (2.5 m away)
    const state = nav.update([2.0, 3.5]);
    expect(state.status).toBe("routing");
    expect(state.rerouteCount).toBeGreaterThanOrEqual(1);
  });

  it("resets to idle on cancel", () => {
    const nav = new Navigator(astar, 1.4, false);
    nav.setGoal([1.0, 1.0], [4.0, 1.0], "Exit");
    expect(nav.getStatus()).toBe("routing");

    nav.cancel();
    expect(nav.getStatus()).toBe("idle");
    const state = nav.update([1.0, 1.0]);
    expect(state.status).toBe("idle");
  });
});
