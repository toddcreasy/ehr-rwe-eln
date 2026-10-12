import importlib

import psycopg
from fastapi.testclient import TestClient


def test_health_db_unreachable_is_503_with_retry_hint(monkeypatch):
    for name, value in {
        "DB_HOST": "localhost",
        "DB_PASSWORD": "unused",
        "COGNITO_USER_POOL_ID": "us-east-1_test",
        "COGNITO_CLIENT_ID": "test-client",
    }.items():
        monkeypatch.setenv(name, value)
    main = importlib.reload(importlib.import_module("ehr_rwe_eln.api.main"))

    def refuse(**kwargs):
        raise psycopg.OperationalError("connection timeout expired")

    monkeypatch.setattr(main.psycopg, "connect", refuse)
    response = TestClient(main.app).get("/health/db")
    assert response.status_code == 503
    assert "resuming" in response.json()["detail"]
