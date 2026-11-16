"""e2e_round2.py: End-to-end browser verification of Roomscape Round 2 using Playwright.

Workflow:
1. Start ephemeral `vite preview` on an open port.
2. Launch Chromium with software WebGL (SwiftShader).
3. Wait for window.__roomscapeReady === true.
4. Open search with "/", type a POI query, press Enter.
5. Assert route exists (length > 0).
6. Trigger "Walk me there" guided auto-walk.
7. Sample positions during walk, verifying all sampled positions are walkable.
8. Wait for arrival, verify final position is within 0.7 m of goal.
9. Assert zero console errors.
10. Save screenshot and report. Always terminate preview server in finally block.
"""
from __future__ import annotations
import argparse
import json
import math
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
VIEWER_DIR = REPO_ROOT / "viewer"
OUT_DIR = REPO_ROOT / "out"

def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]

def run_e2e_attempt(port: int, screenshot_path: Path, timeout_sec: float = 60.0) -> dict:
    from playwright.sync_api import sync_playwright, Error as PWError

    errors: list[str] = []
    fps_samples: list[float] = []
    walk_samples: list[list[float]] = []
    all_walkable = True

    url = f"http://localhost:{port}"

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--use-gl=angle",
                "--use-angle=swiftshader",
                "--enable-unsafe-swiftshader",
                "--ignore-gpu-blocklist",
                "--no-sandbox",
            ],
        )
        page = browser.new_page(viewport={"width": 1280, "height": 720})

        page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
        page.on("console", lambda m: errors.append(f"console.error: {m.text}") if m.type == "error" else None)

        t0 = time.time()
        print(f"-> Loading {url} ...")
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_function("window.__roomscapeReady === true", timeout=timeout_sec * 1000)
        load_time = time.time() - t0
        print(f"-> Roomscape ready in {load_time:.2f}s")

        # Check initial stats
        stats = page.evaluate("window.__roomscapeStats")

        # 1. Press "/" to open search box
        print("-> Pressing '/' to open search overlay...")
        page.keyboard.press("Slash")
        page.wait_for_selector("#search-overlay", state="visible", timeout=5000)

        # 2. Type "Workstation Desk" and press Enter
        print("-> Typing 'desk' and pressing Enter...")
        page.fill("#search-input", "desk")
        time.sleep(0.3)
        page.keyboard.press("Enter")
        time.sleep(0.5)

        # 3. Assert route exists
        route_info = page.evaluate("""() => {
            const nav = window.roomscape?.navigator;
            const ctrl = window.roomscape?.controls;
            if (!nav || !ctrl) return null;
            const state = nav.update([ctrl.x, ctrl.z]);
            return {
                status: state.status,
                target: state.target,
                targetName: state.targetName,
                waypointsCount: state.waypoints.length,
                remainingDistance: state.remainingDistance
            };
        }""")

        if not route_info or route_info["waypointsCount"] == 0 or route_info["remainingDistance"] <= 0:
            browser.close()
            return {
                "ok": False,
                "reason": f"Route not found or empty: {route_info}",
                "errors": errors,
            }

        print(f"-> Active route to {route_info['targetName']}: {route_info['remainingDistance']:.2f} m, {route_info['waypointsCount']} waypoints")

        # 4. Trigger "Walk me there" guided walk
        print("-> Starting guided auto-walk...")
        page.click("#nav-hud .btn-walk")

        # 5. Sample positions during walk
        goal = route_info["target"]
        walk_start = time.time()
        arrived = False

        while time.time() - walk_start < 25.0:
            time.sleep(0.3)
            pos_info = page.evaluate("""() => {
                const ctrl = window.roomscape?.controls;
                const col = window.roomscape?.collision;
                const nav = window.roomscape?.navigator;
                const s = window.roomscapeStats;
                if (!ctrl || !col || !nav) return null;
                const isWalk = col.isWalkable(ctrl.x, ctrl.z);
                const state = nav.update([ctrl.x, ctrl.z]);
                return {
                    pos: [ctrl.x, ctrl.z],
                    isWalkable: isWalk,
                    status: state.status,
                    remainingDist: state.remainingDistance,
                    isAutoWalking: ctrl.isAutoWalking,
                    fps: s ? s.fps : 0
                };
            }""")

            if not pos_info:
                continue

            walk_samples.append(pos_info["pos"])
            if not pos_info["isWalkable"]:
                all_walkable = False

            if pos_info["fps"] > 0:
                fps_samples.append(pos_info["fps"])

            if pos_info["status"] == "arrived" or pos_info["remainingDist"] <= 0.6:
                arrived = True
                print("-> Navigator reported arrival at destination!")
                break

        final_pos = page.evaluate("(() => { const c = window.roomscape?.controls; return c ? [c.x, c.z] : [0, 0] })()")
        dist_to_goal = math.hypot(final_pos[0] - goal[0], final_pos[1] - goal[1])
        print(f"-> Final position: [{final_pos[0]:.2f}, {final_pos[1]:.2f}], distance to goal: {dist_to_goal:.2f} m")

        # Save screenshot
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        try:
            page.evaluate("window.roomscape?.renderer?.setAnimationLoop(null)")
            page.screenshot(path=str(screenshot_path), timeout=15000)
            print(f"-> Screenshot saved to {screenshot_path}")
        except Exception as e:
            print(f"[!] Screenshot warning: {e}")

        browser.close()

    avg_fps = sum(fps_samples) / len(fps_samples) if fps_samples else 0.0
    within_radius = dist_to_goal <= 0.7

    ok = (
        len(errors) == 0
        and arrived
        and within_radius
        and all_walkable
        and len(walk_samples) > 2
    )

    reason = ""
    if not within_radius:
        reason = f"Final distance {dist_to_goal:.2f} m > 0.7 m threshold"
    elif not all_walkable:
        reason = "A sampled position along auto-walk was not walkable"
    elif errors:
        reason = f"Console or page errors detected: {errors[:2]}"

    return {
        "ok": ok,
        "reason": reason,
        "load_time_sec": round(load_time, 2),
        "target": route_info["targetName"],
        "goal_pos": goal,
        "final_pos": final_pos,
        "final_distance_to_goal_m": round(dist_to_goal, 3),
        "sampled_positions_count": len(walk_samples),
        "all_positions_walkable": all_walkable,
        "average_fps_software": round(avg_fps, 1),
        "fps_note": "software rendering (SwiftShader), not GPU performance",
        "errors": errors,
    }

def main() -> int:
    parser = argparse.ArgumentParser(description="Roomscape Round 2 E2E test")
    parser.add_argument("--retries", type=int, default=1, help="Max retries on failure")
    args = parser.parse_args()

    # Ensure build exists
    dist_index = VIEWER_DIR / "dist" / "index.html"
    if not dist_index.exists():
        print("-> Building viewer before E2E...")
        subprocess.run(["npm", "run", "build"], cwd=str(VIEWER_DIR), shell=True, check=True)

    port = find_free_port()
    print(f"-> Starting vite preview on port {port}...")

    npx_bin = shutil.which("npx") or "npx"
    preview_proc = subprocess.Popen(
        [npx_bin, "vite", "preview", "--port", str(port), "--strictPort"],
        cwd=str(VIEWER_DIR),
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # Wait for server to respond
    time.sleep(2.0)

    screenshot_path = OUT_DIR / "e2e_screenshot.png"
    report_path = OUT_DIR / "e2e_report.json"

    res = None
    try:
        attempts = 0
        max_attempts = 1 + args.retries
        while attempts < max_attempts:
            attempts += 1
            if attempts > 1:
                print(f"\n[!] Retrying E2E test (attempt {attempts} of {max_attempts})...")
            try:
                res = run_e2e_attempt(port, screenshot_path)
                if res["ok"]:
                    if attempts > 1:
                        res["retried"] = True
                        res["attempts"] = attempts
                    break
            except Exception as e:
                res = {"ok": False, "reason": str(e), "errors": [str(e)]}

    finally:
        print("-> Terminating vite preview server...")
        try:
            if sys.platform == "win32":
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(preview_proc.pid)], capture_output=True)
            else:
                preview_proc.terminate()
        except Exception:
            pass

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(res, indent=2), encoding="utf-8")
    print(f"\n==========================================")
    print(f"E2E Round 2 Result: {'PASS' if res and res.get('ok') else 'FAIL'}")
    print(f"Report: {report_path}")
    print(f"==========================================")
    print(json.dumps(res, indent=2))

    return 0 if res and res.get("ok") else 1

if __name__ == "__main__":
    sys.exit(main())
