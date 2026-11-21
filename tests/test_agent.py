import contextlib
import json
from types import SimpleNamespace

from ehr_rwe_eln.agents import app, omop_tools, workbench
from ehr_rwe_eln.agents.workbench import AgentReply


def response(content, parsed_output=None, **usage):
    usage = {"input_tokens": 0, "output_tokens": 0} | usage
    usage.setdefault("cache_read_input_tokens", None)
    usage.setdefault("cache_creation_input_tokens", None)
    return SimpleNamespace(
        content=content, parsed_output=parsed_output, usage=SimpleNamespace(**usage)
    )


def test_invoke_returns_typed_reply_and_tools_called(monkeypatch):
    reply = AgentReply(reply="8,612 people have essential hypertension.")
    responses = [
        response([SimpleNamespace(type="tool_use", name="omop_concept_search")], input_tokens=10),
        response([SimpleNamespace(type="text")], reply, input_tokens=5, cache_read_input_tokens=3),
    ]
    monkeypatch.setattr(app, "run_agent", lambda *args: responses)

    result = app.invoke(app.AgentRequest(prompt="How many people have essential hypertension?"))

    assert result["output"]["reply"] == "8,612 people have essential hypertension."
    assert result["usage"]["tools_called"] == ["omop_concept_search"]
    assert result["usage"]["input_tokens"] == 15
    assert result["usage"]["cache_read"] == 3
    assert result["usage"]["model_calls"] == 2
    assert result["usage"]["total_tokens"] == 15 + 3


def test_invoke_returns_no_output_when_the_call_cap_cuts_the_run(monkeypatch):
    tool_call = [SimpleNamespace(type="tool_use", name="omop_concept_search")]
    responses = [response(tool_call, input_tokens=10) for _ in range(workbench.MAX_MODEL_CALLS)]
    monkeypatch.setattr(app, "run_agent", lambda *args: responses)

    result = app.invoke(app.AgentRequest(prompt="Search 20 times."))

    assert result["output"] is None
    assert result["usage"]["total_tokens"] == 40


def test_tool_wrapper_returns_json_and_turns_bad_input_into_a_message(monkeypatch):
    monkeypatch.setattr(
        workbench.DatabaseSettings,
        "connect",
        lambda self, **kwargs: contextlib.nullcontext("con"),
        raising=False,
    )
    monkeypatch.setenv("DB_HOST", "unused")
    monkeypatch.setenv("DB_PASSWORD", "unused")

    def found(con, text):
        assert con == "con"
        return [omop_tools.Arm(name=text, persons=12, events=3)]

    def bad(con):
        raise omop_tools.ToolInputError("search text must be 2 to 100 characters")

    assert json.loads(workbench._call(found, "a")) == [{"name": "a", "persons": 12, "events": 3}]
    assert json.loads(workbench._call(bad)) == {"error": "search text must be 2 to 100 characters"}
    assert json.loads(workbench._call(lambda con: None)) == {"result": None}
