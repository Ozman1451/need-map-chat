import subprocess
import sys
from pathlib import Path

import pytest

PIPE = Path(__file__).resolve().parents[2] / "pipeline"
SCRIPTS = sorted(p for p in PIPE.glob("*.py") if not p.name.startswith("_"))


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_script_runs(script):
    r = subprocess.run([sys.executable, str(script), "--dataset", "synthetic"],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
