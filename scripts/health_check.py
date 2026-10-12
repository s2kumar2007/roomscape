"""Open the deployed viewer in headless Chromium (Playwright), wait for load, walk forward, report load time + average FPS.

Usage: python scripts/health_check.py --url https://<project>.pages.dev [--seconds 10] [--screenshot out.png]
Exit code 0 = healthy, 1 = failed (page error, timeout, or FPS below --min-fps), 2 = tooling problem.
NOTE: headless CI uses software WebGL (SwiftShader), so FPS there is far lower than on a real GPU.
"""
from __future__ import annotations
import argparse, json, sys, time

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True); ap.add_argument("--seconds", type=float, default=10.0)
    ap.add_argument("--timeout", type=float, default=120.0, help="max seconds to wait for the scene to load")
    ap.add_argument("--min-fps", type=float, default=0.0, help="fail if average FPS is below this (0 = report only)")
    ap.add_argument("--screenshot"); ap.add_argument("--headed", action="store_true")
    ap.add_argument("--width", type=int, default=1280); ap.add_argument("--height", type=int, default=720)
    a = ap.parse_args()
    try:
        from playwright.sync_api import sync_playwright, Error as PWError
    except ImportError:
        print("[!] Playwright missing: pip install playwright && python -m playwright install chromium"); return 2
    errors: list[str] = []
    with sync_playwright() as p:
        try:
            b = p.chromium.launch(headless=not a.headed, args=["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"])
        except PWError as e:
            print(f"[!] Cannot launch Chromium: {str(e).splitlines()[0]}\n    Fix: python -m playwright install chromium"); return 2
        pg = b.new_page(viewport={"width": a.width, "height": a.height})
        pg.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
        pg.on("console", lambda m: errors.append(f"console.error: {m.text}") if m.type == "error" else None)
        t0 = time.time()
        try:
            pg.goto(a.url, wait_until="domcontentloaded", timeout=60000)
            pg.wait_for_function("window.__nammaReady === true", timeout=a.timeout * 1000)
        except PWError as e:
            try: err = pg.evaluate("document.getElementById('error')?.textContent || ''")
            except PWError: err = ""   # page never loaded (e.g. connection refused)
            print(json.dumps({"ok": False, "url": a.url, "reason": str(e).splitlines()[0], "page_error_text": err, "errors": errors[:5]}, indent=2)); b.close(); return 1
        wall_load = time.time() - t0
        pg.mouse.click(a.width // 2, a.height // 2); pg.keyboard.down("w")
        samples: list[float] = []; end = time.time() + a.seconds
        while time.time() < end:
            time.sleep(0.5); s = pg.evaluate("window.__nammaStats"); samples.append(float(s["fps"])) if s and s["fps"] > 0 else None
        pg.keyboard.up("w")
        stats = pg.evaluate("window.__nammaStats"); pos = pg.evaluate("(() => { const c = window.nammaSpace?.controls; return c ? [c.x, c.z] : null })()")
        if a.screenshot:
            try: pg.screenshot(path=a.screenshot, timeout=90000)
            except PWError as e: errors_note = f"screenshot failed: {str(e).splitlines()[0]}"; print("[!]", errors_note)
        b.close()
    avg = sum(samples) / len(samples) if samples else 0.0
    res = {"ok": not errors and avg >= a.min_fps and bool(samples), "url": a.url, "load_seconds_wall": round(wall_load, 2),
           "load_ms_app": round(stats["loadMs"]), "avg_fps": round(avg, 1), "min_fps": round(min(samples), 1) if samples else 0,
           "gaussians": stats["gaussians"], "pixel_ratio": stats["pixelRatio"], "moved_to": pos, "errors": errors[:10]}
    print(json.dumps(res, indent=2)); return 0 if res["ok"] else 1

if __name__ == "__main__":
    sys.exit(main())
