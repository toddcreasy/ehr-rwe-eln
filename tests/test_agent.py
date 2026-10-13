from types import SimpleNamespace

from ehr_rwe_eln.agents import app
from ehr_rwe_eln.agents.hello import HelloReply, check_database_health


class FakeAgent:
    def __init__(self, result, messages):
        self.result = result
        self.messages = messages

    def __call__(self, *args, **kwargs):
        return self.result


def test_invoke_returns_typed_reply_and_tools_called(monkeypatch):
    result = SimpleNamespace(
        structured_output=HelloReply(reply="It is noon.", utc_time="2026-10-12T12:00:00+00:00"),
        metrics=SimpleNamespace(accumulated_usage={"inputTokens": 10}, cycle_count=2),
    )
    messages = [{"content": [{"toolUse": {"name": "current_time"}}, {"text": "..."}]}]
    monkeypatch.setattr(app, "build_agent", lambda *args: FakeAgent(result, messages))

    response = app.invoke(app.AgentRequest(prompt="What time is it?"))

    assert response["output"]["reply"] == "It is noon."
    assert response["usage"]["tools_called"] == ["current_time"]
    assert response["usage"]["input_tokens"] == 10


def test_database_health_tool(database, monkeypatch):
    assert check_database_health() == "reachable"
    # Nothing listens on port 1.
    monkeypatch.setenv("DB_PORT", "1")
    assert check_database_health() == "unreachable"
