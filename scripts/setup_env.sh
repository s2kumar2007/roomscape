#!/usr/bin/env bash
set -euo pipefail
conda env create -f environment.yml || conda env update -f environment.yml
echo "Next: conda activate namma-space && python scripts/check_gpu.py"
