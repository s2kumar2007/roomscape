"""Verify CUDA, COLMAP, ffmpeg and print fix instructions."""
from __future__ import annotations
import shutil, subprocess, sys

def sh(cmd: list[str]) -> str:
    try: return subprocess.run(cmd, capture_output=True, text=True, timeout=20).stdout.strip()
    except Exception: return ""

def main() -> int:
    ok = True
    print(f"Python {sys.version.split()[0]}")
    smi = shutil.which("nvidia-smi")
    if smi:
        print("GPU:", sh([smi, "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader"]))
    else:
        ok = False
        print("[!] nvidia-smi not found. Install an NVIDIA driver, or use notebooks/colab_reconstruct.ipynb.")
    try:
        import torch
        print("torch", torch.__version__, "| CUDA available:", torch.cuda.is_available())
        if not torch.cuda.is_available():
            ok = False; print("[!] Install a CUDA build of PyTorch: https://pytorch.org/get-started/locally/")
    except ImportError:
        ok = False; print("[!] PyTorch missing: see README (CUDA-specific install)")
    for tool, fix in (("colmap", "conda install -c conda-forge colmap  (or apt/brew install colmap)"),
                      ("ffmpeg", "conda install -c conda-forge ffmpeg  (or apt/brew install ffmpeg)")):
        p = shutil.which(tool)
        print(f"{tool}: {p}" if p else f"[!] {tool} not found -> {fix}")
        ok = ok and bool(p)
    print("\nRESULT:", "ready" if ok else "NOT ready (see [!] lines above)")
    return 0 if ok else 1

if __name__ == "__main__":
    sys.exit(main())
