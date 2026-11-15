from fastapi.testclient import TestClient

from app.main import app


def test_health():
    r = TestClient(app).get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_default_dataset_prefers_real(tmp_path, monkeypatch):
    from app.config import settings
    from app.store import FILES, Store
    monkeypatch.setattr(settings, "dataset", "")
    s = Store()
    for name in ["synthetic", "real"]:
        (tmp_path / name).mkdir()
    for f in FILES:
        (tmp_path / "synthetic" / f).touch()
    assert s.default_dataset(tmp_path) == "synthetic"  # real incomplete
    for f in FILES:
        (tmp_path / "real" / f).touch()
    assert s.default_dataset(tmp_path) == "real"
    monkeypatch.setattr(settings, "dataset", "synthetic")
    assert s.default_dataset(tmp_path) == "synthetic"  # explicit DATASET wins
