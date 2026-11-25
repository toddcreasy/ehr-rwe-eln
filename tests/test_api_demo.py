import contextlib
import importlib

import pytest
from fastapi import Request
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

    def build(limit: int, enabled: bool = True, complete: bool = True):
        monkeypatch.setenv("DB_HOST", "localhost")
        monkeypatch.setenv("DB_PASSWORD", "unused")
        monkeypatch.setenv("DAILY_TOKEN_LIMIT", str(limit))
        monkeypatch.setenv("AGENT_ENABLED", str(enabled).lower())
        main = importlib.reload(importlib.import_module("ehr_rwe_eln.api.main"))
        monkeypatch.setattr(main, "connect", lambda: contextlib.nullcontext(pg))
        monkeypatch.setattr(
            main, "invoke", lambda request: {"output": {} if complete else None, "usage": USAGE}
        )
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


SECRET = "test-origin-secret"  # noqa: S105  # gitleaks:allow


def request_with(headers: dict[str, str], client: str = "10.0.0.5") -> Request:
    return Request(
        {
            "type": "http",
            "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
            "client": (client, 50000),
        }
    )


def test_client_address_trusts_cloudfront_only_with_the_secret():
    through_cloudfront = {
        "x-origin-verify": SECRET,  # gitleaks:allow
        "cloudfront-viewer-address": "198.51.100.10:46532",
        "x-forwarded-for": "198.51.100.10, 130.176.1.1",
    }
    assert limits.client_address(request_with(through_cloudfront), SECRET) == "198.51.100.10"
    # A caller on the Express URL can send the viewer header, but not the secret.
    spoofed = {"cloudfront-viewer-address": "9.9.9.9:1", "x-forwarded-for": "203.0.113.9"}
    assert limits.client_address(request_with(spoofed), SECRET) == "203.0.113.9"
    wrong = {**spoofed, "x-origin-verify": "guess"}  # gitleaks:allow
    assert limits.client_address(request_with(wrong), SECRET) == "203.0.113.9"
    # Without a configured secret (locally) the viewer header is never read.
    assert limits.client_address(request_with(through_cloudfront), None) == "130.176.1.1"


@pytest.mark.parametrize(
    ("value", "ip"),
    [
        ("198.51.100.10:46532", "198.51.100.10"),
        ("2001:db8:85a3::8a2e:370:7334:46532", "2001:db8:85a3::8a2e:370:7334"),
        ("[2001:db8::1]:443", "2001:db8::1"),
        ("198.51.100.10", "198.51.100.10"),
        ("", None),
        ("not-an-address:1", None),
    ],
)
def test_viewer_ip_drops_the_port(value, ip):
    assert limits.viewer_ip(value) == ip


@pytest.mark.parametrize(
    ("address", "key"),
    [
        ("198.51.100.10", "198.51.100.10"),
        ("2001:db8:85a3:1:8a2e:370:7334:1", "2001:db8:85a3:1::/64"),
        ("2001:db8:85a3:1::ffff", "2001:db8:85a3:1::/64"),
        ("unknown", "unknown"),
    ],
)
def test_limit_key_groups_an_ipv6_host_by_its_64(address, key):
    assert limits.limit_key(address) == key


def test_agent_per_address_limit_counts_an_ipv6_64_once(app_with_limit, monkeypatch):
    monkeypatch.setenv("ORIGIN_VERIFY_SECRET", SECRET)
    client = app_with_limit(1_000_000)
    edge = {"x-origin-verify": SECRET, "x-forwarded-for": "130.176.1.1"}  # gitleaks:allow
    # A new address in the same /64 for every call.
    for n in range(limits.CALLS_PER_ADDRESS_PER_HOUR):
        rotated = {**edge, "cloudfront-viewer-address": f"[2001:db8:1:2::{n + 1:x}]:443"}
        assert client.post("/api/agent", json={"prompt": "hi"}, headers=rotated).status_code == 200
    rotated = {**edge, "cloudfront-viewer-address": "[2001:db8:1:2::ffff]:443"}
    assert client.post("/api/agent", json={"prompt": "hi"}, headers=rotated).status_code == 429
    other = {**edge, "cloudfront-viewer-address": "[2001:db8:1:3::1]:443"}
    assert client.post("/api/agent", json={"prompt": "hi"}, headers=other).status_code == 200


def test_agent_per_address_limit_follows_the_cloudfront_viewer(app_with_limit, monkeypatch):
    monkeypatch.setenv("ORIGIN_VERIFY_SECRET", SECRET)
    client = app_with_limit(1_000_000)
    # Every call reaches the load balancer from the same CloudFront server.
    edge = {"x-origin-verify": SECRET, "x-forwarded-for": "130.176.1.1"}  # gitleaks:allow
    first = {**edge, "cloudfront-viewer-address": "198.51.100.10:1111"}
    for _ in range(limits.CALLS_PER_ADDRESS_PER_HOUR):
        assert client.post("/api/agent", json={"prompt": "hi"}, headers=first).status_code == 200
    same_viewer = {**edge, "cloudfront-viewer-address": "198.51.100.10:2222"}
    assert client.post("/api/agent", json={"prompt": "hi"}, headers=same_viewer).status_code == 429
    other = {**edge, "cloudfront-viewer-address": "198.51.100.11:1111"}
    assert client.post("/api/agent", json={"prompt": "hi"}, headers=other).status_code == 200


def test_agent_switch_off_refuses_before_the_model(app_with_limit):
    client = app_with_limit(1_000_000, enabled=False)
    refused = client.post("/api/agent", json={"prompt": "hi"})
    assert refused.status_code == 503
    assert "turned off" in refused.json()["detail"]
    assert client.get("/api/usage").json()["used"] == 0


def test_agent_cut_short_by_the_call_cap_still_counts_its_tokens(app_with_limit):
    client = app_with_limit(1_000_000, complete=False)
    assert client.post("/api/agent", json={"prompt": "hi"}).status_code == 502
    assert client.get("/api/usage").json()["used"] == USAGE["total_tokens"]


def test_public_demo_blocks_curator_decisions(monkeypatch):
    monkeypatch.setenv("PUBLIC_DEMO", "true")
    from ehr_rwe_eln.api.main import app

    response = TestClient(app).post("/api/curation/decisions", json={})
    assert response.status_code == 403
    assert "public demo" in response.json()["detail"]
    assert TestClient(app).get("/api/curation/decisions/enabled").json() is False


def test_without_public_demo_decisions_get_past_the_guard(monkeypatch):
    monkeypatch.setenv("PUBLIC_DEMO", "false")
    from ehr_rwe_eln.api.main import app

    # The empty body fails validation (422), which proves the request got past the guard.
    assert TestClient(app).post("/api/curation/decisions", json={}).status_code == 422
    assert TestClient(app).get("/api/curation/decisions/enabled").json() is True
