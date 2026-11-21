from types import SimpleNamespace

from ehr_rwe_eln.agents import app
from ehr_rwe_eln.agents.hello import HelloReply, check_database_health


def response(content, parsed_output=None, **usage):
    usage = {"input_tokens": 0, "output_tokens": 0} | usage
    usage.setdefault("cache_read_input_tokens", None)
    usage.setdefault("cache_creation_input_tokens", None)
    return SimpleNamespace(
        content=content, parsed_output=parsed_output, usage=SimpleNamespace(**usage)
    )


def test_invoke_returns_typed_reply_and_tools_called(monkeypatch):
    reply = HelloReply(reply="It is noon.", utc_time="2026-10-12T12:00:00+00:00")
    responses = [
        response([SimpleNamespace(type="tool_use", name="current_time")], input_tokens=10),
        response([SimpleNamespace(type="text")], reply, input_tokens=5, cache_read_input_tokens=3),
    ]
    monkeypatch.setattr(app, "run_agent", lambda *args: responses)

    result = app.invoke(app.AgentRequest(prompt="What time is it?"))

    assert result["output"]["reply"] == "It is noon."
    assert result["usage"]["tools_called"] == ["current_time"]
    assert result["usage"]["input_tokens"] == 15
    assert result["usage"]["cache_read"] == 3
    assert result["usage"]["model_calls"] == 2
    assert result["usage"]["total_tokens"] == 15 + 3


def test_invoke_returns_no_output_when_the_call_cap_cuts_the_run(monkeypatch):
    tool_call = [SimpleNamespace(type="tool_use", name="check_database_health")]
    responses = [response(tool_call, input_tokens=10) for _ in range(4)]
    monkeypatch.setattr(app, "run_agent", lambda *args: responses)

    result = app.invoke(app.AgentRequest(prompt="Check the database 20 times."))

    assert result["output"] is None
    assert result["usage"]["total_tokens"] == 40


def test_database_health_tool(database, monkeypatch):
    assert check_database_health() == "reachable"
    # Nothing listens on port 1.
    monkeypatch.setenv("DB_PORT", "1")
    assert check_database_health() == "unreachable"
