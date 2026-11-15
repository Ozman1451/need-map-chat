import os
import subprocess
import sys
from pathlib import Path

import pytest

PIPE = Path(__file__).resolve().parents[2] / "pipeline"
# seed_synthetic is covered by test_seed.py (it would overwrite data/raw/synthetic)
SCRIPTS = sorted(p for p in PIPE.glob("*.py") if not p.name.startswith("_") and p.name != "seed_synthetic.py")


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_script_runs(script):
    r = subprocess.run([sys.executable, str(script), "--dataset", "synthetic"],
                       capture_output=True, text=True, timeout=60,
                       env={**os.environ, "MOCK_LLM": "1"})
    assert r.returncode == 0, r.stderr
