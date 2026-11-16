"""check_all.py: Run all verification layers for Roomscape Round 2.

Order:
  1. pytest
  2. vitest
  3. tsc --noEmit
  4. npm run build
  5. Playwright e2e (scripts/e2e_round2.py)

Usage:
  python scripts/check_all.py [--quick] [--coverage]
"""
from __future__ import annotations
import argparse
import os
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

def find_repo_root() -> Path:
    # Anchor to directory containing this script
    script_dir = Path(__file__).resolve().parent
    root = script_dir.parent
    if (root / "pytest.ini").exists():
        return root
    # Fallback to current working directory
    cwd = Path.cwd()
    if (cwd / "pytest.ini").exists():
        return cwd
    if (cwd / "namma-space" / "pytest.ini").exists():
        return cwd / "namma-space"
    return root

def run_step(
    name: str,
    cmd: list[str] | str,
    cwd: Path,
    env: dict[str, str] | None = None,
    shell: bool = False,
) -> tuple[bool, float, str, str]:
    t0 = time.time()
    try:
        final_cmd = cmd
        if shell and isinstance(cmd, list):
            if sys.platform == "win32":
                final_cmd = subprocess.list2cmdline(cmd)
            else:
                final_cmd = shlex.join(cmd)
        proc = subprocess.run(
            final_cmd,
            cwd=str(cwd),
            env=env,
            shell=shell,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        duration = time.time() - t0
        output = proc.stdout + "\n" + proc.stderr
        ok = proc.returncode == 0
        return ok, duration, output, ""
    except Exception as ex:
        duration = time.time() - t0
        return False, duration, "", str(ex)

def main() -> int:
    parser = argparse.ArgumentParser(description="Run all Roomscape test suites.")
    parser.add_argument("--quick", action="store_true", help="Skip browser e2e and full bundle build.")
    parser.add_argument("--coverage", action="store_true", help="Collect coverage metrics where available.")
    args = parser.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    root = find_repo_root()
    viewer_dir = root / "viewer"
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{root / 'pipeline'}{os.pathsep}{root / 'test'}{os.pathsep}{env.get('PYTHONPATH', '')}"

    rows: list[dict[str, str]] = []
    overall_ok = True

    print(f"\n=======================================================")
    print(f"Roomscape Round 2 Verification: {root.name}")
    print(f"Directory: {root}")
    print(f"Mode: {'QUICK' if args.quick else 'FULL'}")
    print(f"=======================================================\n")

    # 1. pytest
    print("-> Running pytest...")
    pytest_cmd = [sys.executable, "-m", "pytest"]
    if args.coverage:
        pytest_cmd.extend(["--cov=pipeline", "--cov-report=term-missing"])
    else:
        pytest_cmd.append("-q")
    ok, dur, out, err = run_step("pytest", pytest_cmd, cwd=root, env=env)
    detail = ""
    for line in out.splitlines():
        if "passed" in line or "failed" in line or "skipped" in line:
            detail = line.strip("= ").strip()
    if not detail and err:
        detail = err
    if not ok:
        overall_ok = False
        print(out)
    rows.append({
        "stage": "pytest",
        "status": "PASS" if ok else "FAIL",
        "duration": f"{dur:.2f}s",
        "details": detail or ("Tests passed" if ok else "Failed"),
    })

    # 2. vitest
    print("-> Running vitest...")
    npx_bin = shutil.which("npx") or "npx"
    vitest_cmd = [npx_bin, "vitest", "run"]
    if args.coverage:
        vitest_cmd.append("--coverage")
    ok, dur, out, err = run_step("vitest", vitest_cmd, cwd=viewer_dir, env=env, shell=True)
    detail = ""
    for line in out.splitlines():
        if "Tests" in line and ("passed" in line or "failed" in line):
            detail = " ".join(line.split())
    if not detail:
        for line in out.splitlines():
            if "passed" in line:
                detail = " ".join(line.split())
    if not ok:
        overall_ok = False
        print(out)
    rows.append({
        "stage": "vitest",
        "status": "PASS" if ok else "FAIL",
        "duration": f"{dur:.2f}s",
        "details": detail or ("Tests passed" if ok else "Failed"),
    })

    # 3. tsc --noEmit (stop early on type errors)
    print("-> Running tsc --noEmit...")
    ok, dur, out, err = run_step("tsc", [npx_bin, "tsc", "--noEmit"], cwd=viewer_dir, env=env, shell=True)
    detail = "Clean type check" if ok else "TypeScript errors found"
    rows.append({
        "stage": "tsc --noEmit",
        "status": "PASS" if ok else "FAIL",
        "duration": f"{dur:.2f}s",
        "details": detail,
    })
    if not ok:
        print(out)
        print("\n[!] TypeScript type errors detected. Stopping early.\n")
        print_table(rows)
        return 1

    # 4. npm run build
    if args.quick:
        rows.append({
            "stage": "npm run build",
            "status": "SKIPPED",
            "duration": "0.00s",
            "details": "Skipped in --quick mode",
        })
    else:
        print("-> Running npm run build...")
        npm_bin = shutil.which("npm") or "npm"
        ok, dur, out, err = run_step("build", [npm_bin, "run", "build"], cwd=viewer_dir, env=env, shell=True)
        detail = "Production bundle built" if ok else "Build failed"
        if not ok:
            overall_ok = False
            print(out)
        rows.append({
            "stage": "npm run build",
            "status": "PASS" if ok else "FAIL",
            "duration": f"{dur:.2f}s",
            "details": detail,
        })

    # 5. Playwright e2e
    e2e_script = root / "scripts" / "e2e_round2.py"
    if args.quick:
        rows.append({
            "stage": "Playwright e2e",
            "status": "SKIPPED",
            "duration": "0.00s",
            "details": "Skipped in --quick mode",
        })
    elif not e2e_script.exists():
        rows.append({
            "stage": "Playwright e2e",
            "status": "SKIPPED",
            "duration": "0.00s",
            "details": "scripts/e2e_round2.py not found (scheduled for Phase R2-G)",
        })
    else:
        print("-> Running Playwright e2e...")
        ok, dur, out, err = run_step("e2e", [sys.executable, str(e2e_script)], cwd=root, env=env)
        detail = ""
        for line in reversed(out.splitlines()):
            if "{" in line or "ok" in line or "passed" in line:
                detail = line.strip()
                break
        if not ok:
            overall_ok = False
            print(out)
        rows.append({
            "stage": "Playwright e2e",
            "status": "PASS" if ok else "FAIL",
            "duration": f"{dur:.2f}s",
            "details": detail or ("E2E passed" if ok else "E2E failed"),
        })

    print_table(rows)

    if overall_ok:
        print("[PASS] All executed verification stages PASSED.\n")
        return 0
    else:
        print("[FAIL] Some verification stages FAILED.\n")
        return 1

def print_table(rows: list[dict[str, str]]) -> None:
    headers = ["Stage", "Status", "Duration", "Details"]
    w_stage = max(len(headers[0]), max((len(r["stage"]) for r in rows), default=10))
    w_status = max(len(headers[1]), max((len(r["status"]) for r in rows), default=8))
    w_dur = max(len(headers[2]), max((len(r["duration"]) for r in rows), default=10))
    w_det = max(len(headers[3]), max((len(r["details"]) for r in rows), default=20))

    sep = f"+-{'-' * w_stage}-+-{'-' * w_status}-+-{'-' * w_dur}-+-{'-' * w_det}-+"
    header_line = f"| {headers[0].ljust(w_stage)} | {headers[1].ljust(w_status)} | {headers[2].ljust(w_dur)} | {headers[3].ljust(w_det)} |"

    print("\n" + sep)
    print(header_line)
    print(sep)
    for r in rows:
        print(f"| {r['stage'].ljust(w_stage)} | {r['status'].ljust(w_status)} | {r['duration'].ljust(w_dur)} | {r['details'].ljust(w_det)} |")
    print(sep + "\n")

if __name__ == "__main__":
    sys.exit(main())
