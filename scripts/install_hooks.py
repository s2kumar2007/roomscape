"""install_hooks.py: Installs git pre-push hook to run check_all.py --quick."""
from pathlib import Path
import os
import stat
import sys

def main() -> int:
    root = Path(__file__).resolve().parent.parent
    hooks_dir = root / ".git" / "hooks"
    if not hooks_dir.exists():
        print(f"[!] .git/hooks directory not found at {hooks_dir}")
        return 1

    pre_push_path = hooks_dir / "pre-push"
    hook_content = """#!/bin/sh
echo "Running pre-push check (quick mode)..."
python scripts/check_all.py --quick
if [ $? -ne 0 ]; then
    echo "pre-push check failed. Push aborted."
    exit 1
fi
exit 0
"""
    pre_push_path.write_text(hook_content, encoding="utf-8")
    try:
        current_stat = os.stat(pre_push_path)
        os.chmod(pre_push_path, current_stat.st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    except Exception:
        pass
    print(f"[✓] Installed pre-push hook at {pre_push_path}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
