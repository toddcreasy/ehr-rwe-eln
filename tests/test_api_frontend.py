import importlib
import logging

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


def test_page_views_log_the_visitor_and_assets_do_not(monkeypatch, tmp_path):
    (tmp_path / "index.html").write_text("<h1>ehr-rwe-eln</h1>")
    for name, value in {
        "DB_HOST": "localhost",
        "DB_PASSWORD": "unused",
        "FRONTEND_DIR": str(tmp_path),
    }.items():
        monkeypatch.setenv(name, value)
    main = importlib.reload(importlib.import_module("ehr_rwe_eln.api.main"))
    client = TestClient(main.app)
    # configure_logging replaces the root handlers (pytest's caplog too), so collect directly.
    records = []
    handler = logging.Handler()
    handler.emit = records.append
    logging.getLogger("ehr_rwe_eln.api").addHandler(handler)
    headers = {"X-Forwarded-For": "10.0.0.1, 203.0.113.7", "User-Agent": "Mozilla/5.0 test"}

    client.get("/", headers=headers)
    client.get("/api/health", headers=headers)
    client.get("/favicon.ico", headers=headers)

    logging.getLogger("ehr_rwe_eln.api").removeHandler(handler)
    fields = {r.fields["path"]: r.fields for r in records if hasattr(r, "fields")}
    assert fields["/"]["client"] == "203.0.113.7"
    assert fields["/"]["user_agent"] == "Mozilla/5.0 test"
    assert "client" not in fields["/api/health"]
    assert "client" not in fields["/favicon.ico"]
