import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    for name, value in {
        "DB_HOST": "localhost",
        "DB_PASSWORD": "unused",
        "COGNITO_USER_POOL_ID": "us-east-1_test",
        "COGNITO_CLIENT_ID": "test-client",
    }.items():
        monkeypatch.setenv(name, value)
    main = importlib.reload(importlib.import_module("ehr_rwe_eln.api.main"))
    return TestClient(main.app)


def test_me_without_token_is_401(client):
    assert client.get("/me").status_code == 401


def test_me_with_malformed_token_is_401(client):
    response = client.get("/me", headers={"Authorization": "Bearer not-a-jwt"})
    assert response.status_code == 401
