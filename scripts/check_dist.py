"""Fail if any file in viewer/dist exceeds the Cloudflare Pages 25 MiB per-file limit (docs: Pages > Limits)."""
from __future__ import annotations
import sys
from pathlib import Path

LIMIT = 25 * 1024 * 1024

def main(dist: str = "viewer/dist") -> int:
    d = Path(dist)
    if not d.is_dir():
        print(f"[!] {d} not found. Run: cd viewer && npm run build"); return 2
    files = [p for p in d.rglob("*") if p.is_file()]
    big = [(p, p.stat().st_size) for p in files if p.stat().st_size > LIMIT]
    print(f"{len(files)} files, total {sum(p.stat().st_size for p in files) / 1e6:.1f} MB; largest: "
          f"{max(files, key=lambda p: p.stat().st_size).name}")
    for p, s in big:
        print(f"[!] {p.relative_to(d)} is {s / 2**20:.1f} MiB > 25 MiB Pages limit. Host it on R2 and set VITE_SCENE_BASE or use ?scene=<url> (docs/DEPLOY.md).")
    if not (d / "_headers").exists(): print("[!] dist/_headers missing (headers/caching/CORS will not apply).")
    return 1 if big else 0

if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:2]))
