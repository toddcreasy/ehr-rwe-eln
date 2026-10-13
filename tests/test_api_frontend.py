import importlib

from fastapi.testclient import TestClient


def test_frontend_served_at_root_beside_api(monkeypatch, tmp_path):
    (tmp_path / "index.html").write_text("<h1>ehr-rwe-eln</h1>")
    for name, value in {
        "DB_HOST": "localhost",
        "DB_PASSWORD": "unused",
        "FRONTEND_DIR": str(tmp_path),
    }.items():
        monkeypatch.setenv(name, value)
    main = importlib.reload(importlib.import_module("ehr_rwe_eln.api.main"))
    client = TestClient(main.app)

    assert "ehr-rwe-eln" in client.get("/").text
    assert client.get("/api/health").json() == {"status": "ok"}
