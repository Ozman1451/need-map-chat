import pytest

from app.config import settings


@pytest.fixture(autouse=True)
def offline(monkeypatch, tmp_path):
    """No network in tests: mock LLM + throwaway cache dir."""
    monkeypatch.setenv("MOCK_LLM", "1")
    monkeypatch.setattr(settings, "cache_root", str(tmp_path / "cache"))
    monkeypatch.setattr(settings, "gemini_batch_model", "test-batch")
    monkeypatch.setattr(settings, "gemini_embed_model", "test-embed")


@pytest.fixture(scope="session")
def sample_artifacts(tmp_path_factory):
    """Run the full mocked pipeline on data/sample once → artifacts root (…/artifacts)."""
    import os
    import subprocess
    import sys
    from pathlib import Path
    out = tmp_path_factory.mktemp("pipe")
    pipe = Path(__file__).resolve().parents[2] / "pipeline" / "run_all.py"
    env = {**os.environ, "MOCK_LLM": "1", "PIPELINE_OUT": str(out), "CACHE_ROOT": str(out / "c")}
    r = subprocess.run([sys.executable, str(pipe), "--dataset", "sample"],
                       capture_output=True, text=True, timeout=300, env=env)
    assert r.returncode == 0, r.stderr[-2000:]
    return out / "artifacts"


@pytest.fixture
def loaded_store(sample_artifacts):
    from app.store import store
    root = store.root
    store.load("sample", root=sample_artifacts)
    yield store
    store.dataset, store.root = None, root
