import contextlib
import importlib

import pytest
from fastapi.testclient import TestClient

from ehr_rwe_eln.api import limits

USAGE = {
    "input_tokens": 100,
    "output_tokens": 20,
    "cache_read": 5,
    "cache_write": 0,
    "total_tokens": 125,
}


@pytest.fixture
def app_with_limit(pg, dq_schema, monkeypatch):
    """Builds the app with a given daily token limit, on the rolled-back test connection, with
    the model call stubbed out."""

    def build(limit: int):
        monkeypatch.setenv("DB_HOST", "localhost")
        monkeypatch.setenv("DB_PASSWORD", "unused")
        monkeypatch.setenv("DAILY_TOKEN_LIMIT", str(limit))
        main = importlib.reload(importlib.import_module("ehr_rwe_eln.api.main"))
        monkeypatch.setattr(main, "connect", lambda: contextlib.nullcontext(pg))
        monkeypatch.setattr(main, "invoke", lambda request: {"output": {}, "usage": USAGE})
        limits._calls.clear()
        return TestClient(main.app)

    return build


def test_agent_records_tokens_and_stops_at_the_daily_limit(app_with_limit):
    client = app_with_limit(300)
    # 125 tokens a call against a limit of 300: the third call is allowed (250 < 300), the
    # fourth is refused because today's total (375) has reached the limit.
    for n in range(3):
        assert client.post("/api/agent", json={"prompt": "hi"}).status_code == 200, n
    refused = client.post("/api/agent", json={"prompt": "hi"})
    assert refused.status_code == 429
    assert "resets at midnight" in refused.json()["detail"]
    usage = client.get("/api/usage").json()
    assert (usage["limit"], usage["used"], usage["remaining"]) == (300, 375, 0)


def test_agent_per_address_limit_uses_the_last_forwarded_address(app_with_limit):
    client = app_with_limit(1_000_000)
    first = {"x-forwarded-for": "1.2.3.4, 203.0.113.9"}
    for _ in range(limits.CALLS_PER_ADDRESS_PER_HOUR):
        assert client.post("/api/agent", json={"prompt": "hi"}, headers=first).status_code == 200
    # A caller can change the first entry but not the last, which the load balancer appends.
    spoofed = {"x-forwarded-for": "9.9.9.9, 203.0.113.9"}
    assert client.post("/api/agent", json={"prompt": "hi"}, headers=spoofed).status_code == 429
    other = {"x-forwarded-for": "1.2.3.4, 198.51.100.7"}
    assert client.post("/api/agent", json={"prompt": "hi"}, headers=other).status_code == 200


def test_public_demo_blocks_curator_decisions(monkeypatch):
    monkeypatch.setenv("PUBLIC_DEMO", "true")
    from ehr_rwe_eln.api.main import app

    response = TestClient(app).post("/api/curation/decisions", json={})
    assert response.status_code == 403
    assert "public demo" in response.json()["detail"]


def test_without_public_demo_decisions_get_past_the_guard(monkeypatch):
    monkeypatch.setenv("PUBLIC_DEMO", "false")
    from ehr_rwe_eln.api.main import app

    # The empty body fails validation (422), which proves the request got past the guard.
    assert TestClient(app).post("/api/curation/decisions", json={}).status_code == 422
