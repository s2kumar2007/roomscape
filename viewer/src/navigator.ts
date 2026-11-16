/**
 * navigator.ts: Pure navigation state machine.
 *
 * States: "idle" | "routing" | "arrived"
 * Handles:
 * - Distance to goal calculation
 * - ETA calculation at configurable walk speed
 * - Arrival detection (radius <= 0.6 m)
 * - Off-path detection and automatic rerouting (when > 1.5 m off path)
 * - Cancellation (Esc or UI cancel button)
 */
import type { AStarFinder } from "./astar";

export type NavStatus = "idle" | "routing" | "arrived";

export interface NavState {
  status: NavStatus;
  target: [number, number] | null;
  targetName: string | null;
  waypoints: [number, number][];
  remainingDistance: number;
  etaSeconds: number;
  isApproximateScale: boolean;
  rerouteCount: number;
}

export class Navigator {
  private status: NavStatus = "idle";
  private target: [number, number] | null = null;
  private targetName: string | null = null;
  private waypoints: [number, number][] = [];
  private rerouteCount = 0;

  readonly arrivalRadiusM = 0.6;
  readonly rerouteThresholdM = 1.5;

  constructor(
    private astar: AStarFinder,
    private walkSpeed = 1.4,
    private isApproximateScale = false
  ) {}

  getStatus(): NavStatus {
    return this.status;
  }

  getTarget(): [number, number] | null {
    return this.target;
  }

  getWaypoints(): [number, number][] {
    return this.waypoints;
  }

  setGoal(
    playerPos: [number, number],
    target: [number, number],
    targetName: string = "Destination"
  ): boolean {
    const res = this.astar.findPath(playerPos, target);
    if (!res.ok) {
      return false;
    }

    this.status = "routing";
    this.target = target;
    this.targetName = targetName;
    this.waypoints = res.waypoints;
    this.rerouteCount = 0;
    return true;
  }

  cancel(): void {
    this.status = "idle";
    this.target = null;
    this.targetName = null;
    this.waypoints = [];
  }

  update(playerPos: [number, number]): NavState {
    if (this.status === "idle" || !this.target || this.waypoints.length === 0) {
      return {
        status: "idle",
        target: null,
        targetName: null,
        waypoints: [],
        remainingDistance: 0,
        etaSeconds: 0,
        isApproximateScale: this.isApproximateScale,
        rerouteCount: this.rerouteCount,
      };
    }

    const [px, pz] = playerPos;
    const finalWp = this.waypoints[this.waypoints.length - 1];
    const distToGoal = Math.hypot(finalWp[0] - px, finalWp[1] - pz);

    // 1. Check arrival
    if (distToGoal <= this.arrivalRadiusM) {
      this.status = "arrived";
      return {
        status: "arrived",
        target: this.target,
        targetName: this.targetName,
        waypoints: [],
        remainingDistance: 0,
        etaSeconds: 0,
        isApproximateScale: this.isApproximateScale,
        rerouteCount: this.rerouteCount,
      };
    }

    // 2. Find closest point on path and check if player is off-path
    const { minDistanceToPath, closestWaypointIdx } = this.projectToPath(px, pz);

    // Trigger reroute if more than 1.5 m off-path
    if (minDistanceToPath > this.rerouteThresholdM) {
      const res = this.astar.findPath(playerPos, this.target);
      if (res.ok) {
        this.waypoints = res.waypoints;
        this.rerouteCount++;
      }
    } else if (closestWaypointIdx > 0) {
      // Trim waypoints behind player
      this.waypoints = this.waypoints.slice(closestWaypointIdx);
    }

    // 3. Compute remaining distance along waypoints
    let remainingDistance = 0;
    if (this.waypoints.length > 0) {
      remainingDistance = Math.hypot(this.waypoints[0][0] - px, this.waypoints[0][1] - pz);
      for (let i = 1; i < this.waypoints.length; i++) {
        remainingDistance += Math.hypot(
          this.waypoints[i][0] - this.waypoints[i - 1][0],
          this.waypoints[i][1] - this.waypoints[i - 1][1]
        );
      }
    }

    const etaSeconds = this.walkSpeed > 0 ? remainingDistance / this.walkSpeed : 0;

    return {
      status: this.status,
      target: this.target,
      targetName: this.targetName,
      waypoints: this.waypoints,
      remainingDistance: Number(remainingDistance.toFixed(2)),
      etaSeconds: Math.ceil(etaSeconds),
      isApproximateScale: this.isApproximateScale,
      rerouteCount: this.rerouteCount,
    };
  }

  private projectToPath(px: number, pz: number): { minDistanceToPath: number; closestWaypointIdx: number } {
    let minDistanceToPath = Infinity;
    let closestWaypointIdx = 0;

    for (let i = 0; i < this.waypoints.length; i++) {
      const wp = this.waypoints[i];
      const d = Math.hypot(wp[0] - px, wp[1] - pz);
      if (d < minDistanceToPath) {
        minDistanceToPath = d;
        closestWaypointIdx = i;
      }
    }

    // Also check segment perpendicular distances
    for (let i = 0; i < this.waypoints.length - 1; i++) {
      const a = this.waypoints[i];
      const b = this.waypoints[i + 1];
      const dist = distanceToSegment(px, pz, a[0], a[1], b[0], b[1]);
      if (dist < minDistanceToPath) {
        minDistanceToPath = dist;
      }
    }

    return { minDistanceToPath, closestWaypointIdx };
  }
}

function distanceToSegment(
  px: number,
  pz: number,
  x1: number,
  z1: number,
  x2: number,
  z2: number
): number {
  const dx = x2 - x1;
  const dz = z2 - z1;
  const lenSq = dx * dx + dz * dz;
  if (lenSq === 0) return Math.hypot(px - x1, pz - z1);

  const t = Math.max(0, Math.min(1, ((px - x1) * dx + (pz - z1) * dz) / lenSq));
  const projX = x1 + t * dx;
  const projZ = z1 + t * dz;
  return Math.hypot(px - projX, pz - projZ);
}
