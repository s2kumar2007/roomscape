"""check_submission.py: Guard against submitting mock or synthetic demo scenes.

Fails if:
  - viewer/public/scene/meta.json has "mock": true
  - viewer/public/scene/SYNTHETIC_DEMO.txt exists
  - report.json exists and says status "mock" or matcher "mock"
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

def main() -> int:
    root = Path(__file__).resolve().parent.parent
    scene_dir = root / "viewer" / "public" / "scene"
    meta_file = scene_dir / "meta.json"
    demo_marker = scene_dir / "SYNTHETIC_DEMO.txt"
    report_file = root / "report.json"

    violations: list[str] = []

    if demo_marker.exists():
        violations.append(f"Synthetic demo marker found: {demo_marker}")

    if meta_file.exists():
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
            if meta.get("mock") is True:
                violations.append(f"meta.json contains 'mock': true ({meta_file})")
        except Exception as e:
            violations.append(f"Failed to read/parse meta.json: {e}")
    else:
        violations.append(f"Scene metadata missing: {meta_file}")

    if report_file.exists():
        try:
            rep = json.loads(report_file.read_text(encoding="utf-8"))
            if rep.get("status") == "mock":
                violations.append(f"report.json has status: 'mock'")
            if rep.get("matcher") == "mock":
                violations.append(f"report.json has matcher: 'mock'")
        except Exception as e:
            violations.append(f"Failed to read/parse report.json: {e}")

    print("=======================================")
    print("Roomscape Submission Guard")
    print("=======================================")

    if violations:
        print("[FAIL] Submission guard check failed with the following issues:")
        for v in violations:
            print(f"  - {v}")
        print("\nFix: Reconstruct a real room scene using Nerfstudio/COLMAP before submitting.")
        return 1

    print("[PASS] Submission guard clean: Real scene ready for submission.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
