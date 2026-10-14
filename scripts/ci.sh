#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2
python -m pytest -q
python scripts/heldout_tatqa_eval.py ci
python - <<'CHECK'
import json
from pathlib import Path
actual = json.loads(Path('results/heldout_tatqa_ci.json').read_text())
expected = json.loads(Path('results/heldout_tatqa_after.json').read_text())
assert actual == expected, 'Detector benchmark changed; review before updating the baseline'
CHECK
