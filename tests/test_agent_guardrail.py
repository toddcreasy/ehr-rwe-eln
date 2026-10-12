from types import SimpleNamespace

from ehr_rwe_eln.agents import app

BLOCKED = "This is a research tool on synthetic data and cannot help with that request."


class BlockedResult(SimpleNamespace):
    def __str__(self) -> str:
        return BLOCKED


class FakeAgent:
    messages: list = []

    def __init__(self, result):
        self.result = result

    def __call__(self, *args, **kwargs):
        return self.result


def test_guardrail_block_returns_reply_not_error(monkeypatch):
    result = BlockedResult(
        structured_output=None,
        stop_reason="guardrail_intervened",
        metrics=SimpleNamespace(accumulated_usage={}, cycle_count=1),
    )
    monkeypatch.setattr(app, "build_agent", lambda *args: FakeAgent(result))

    response = app.invoke({"prompt": "What dose should I give my patient?"})

    assert response["output"]["reply"] == BLOCKED
    assert response["usage"]["guardrail_intervened"] is True
