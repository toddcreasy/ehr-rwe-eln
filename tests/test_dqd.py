import json

import pytest

from ehr_rwe_eln.dq.dqd import _seconds, read_dqd, save_dqd, save_dqd_data_api


def result(check_id, name, *, failed=0, na=0, error=None, **extra):
    return {
        "checkId": check_id,
        "checkName": name,
        "checkLevel": "FIELD",
        "checkDescription": f"{name} description",
        "cdmTableName": "PERSON",
        "category": "Plausibility",
        "subcategory": "Atemporal",
        "context": "Verification",
        "numViolatedRows": 3 if failed else 0,
        "pctViolatedRows": 0.03 if failed else 0,
        "numDenominatorRows": 100,
        "failed": failed,
        "passed": int(not failed and not na and error is None),
        "isError": int(error is not None),
        "notApplicable": na,
        "executionTime": "5.985009 secs",
        "queryText": "SELECT 1",
        **({"error": error} if error else {}),
        **extra,
    }


@pytest.fixture
def dqd_json(tmp_path):
    data = {
        "startTimestamp": ["2026-11-20 19:37:19"],
        "endTimestamp": ["2026-11-20 19:39:36"],
        "Metadata": [{"cdmSourceName": "test", "cdmReleaseDate": "", "vocabularyVersion": "v5"}],
        "Overview": {"countTotal": [4], "countOverallFailed": [2], "percentPassed": [50]},
        "CheckResults": [
            result("a", "plausibleGender", failed=1, conceptId=200962, thresholdValue=5),
            result("b", "cdmTable"),
            result("c", "measureValueCompleteness", na=1, notApplicableReason="empty table"),
            result("d", "isRequired", failed=1, error="relation does not exist"),
        ],
    }
    path = tmp_path / "dqd.json"
    path.write_text(json.dumps(data))
    return path


def test_read_dqd_fills_severity_and_the_strict_pass_rate(dqd_json):
    run = read_dqd(dqd_json)
    assert run.cdm_source_name == "test" and run.cdm_release_date is None
    by_id = {r["check_id"]: r for r in run.results}
    # The results JSON leaves severity out; DQD's check descriptions supply it.
    assert by_id["b"]["severity"] == "fatal"
    assert by_id["a"]["concept_id"] == "200962" and by_id["a"]["threshold_value"] == 5
    assert by_id["d"]["is_error"] and by_id["d"]["error"] == "relation does not exist"
    assert by_id["c"]["not_applicable_reason"] == "empty table"
    # DQD's one-element lists are unwrapped, and the page's three fields are added: of the 3
    # applicable checks, 1 passed.
    assert run.overview["countTotal"] == 4
    assert run.overview["countNotApplicable"] == 1
    assert run.overview["countIsError"] == 1
    assert run.overview["strictPercentPassed"] == pytest.approx(33.33)


def test_execution_time_parses_seconds_and_minutes():
    assert _seconds("5.985009 secs") == pytest.approx(5.985009)
    assert _seconds("1.5 mins") == pytest.approx(90)
    assert _seconds(None) == 0.0


def test_save_dqd_writes_the_run_and_every_check(pg, dq_schema, dqd_json):
    run_id = save_dqd(pg, read_dqd(dqd_json))
    rows = pg.execute(
        "SELECT check_id, failed, not_applicable, severity FROM dq.result WHERE run_id = %s"
        " ORDER BY check_id",
        [run_id],
    ).fetchall()
    assert rows == [
        ("a", True, False, "characterization"),
        ("b", False, False, "fatal"),
        ("c", False, True, "characterization"),
        ("d", True, False, "fatal"),
    ]
    overview = pg.execute("SELECT overview FROM dq.run WHERE run_id = %s", [run_id]).fetchone()[0]
    assert overview["strictPercentPassed"] == pytest.approx(33.33)


class FakeDataApi:
    def __init__(self):
        self.calls = []

    def begin_transaction(self, **kw):
        self.calls.append(("begin", kw))
        return {"transactionId": "tx"}

    def execute_statement(self, **kw):
        self.calls.append(("execute", kw))
        return {"records": [[{"longValue": 7}]]}

    def batch_execute_statement(self, **kw):
        self.calls.append(("batch", kw))
        return {}

    def commit_transaction(self, **kw):
        self.calls.append(("commit", kw))

    def rollback_transaction(self, **kw):
        self.calls.append(("rollback", kw))


def test_save_through_the_data_api_is_one_transaction_in_batches(dqd_json):
    run = read_dqd(dqd_json)
    run.results = run.results * 101  # 404 rows: two full batches of 200 and one of 4
    api = FakeDataApi()
    assert save_dqd_data_api(api, "cluster", "secret", "db", run) == 7
    kinds = [kind for kind, _ in api.calls]
    assert kinds == ["begin", "execute", "batch", "batch", "batch", "commit"]
    assert all(kw.get("transactionId") == "tx" for kind, kw in api.calls if kind != "begin")
    assert [len(kw["parameterSets"]) for kind, kw in api.calls if kind == "batch"] == [200, 200, 4]
    assert "RETURNING run_id" in api.calls[1][1]["sql"]


class DatabaseResumingException(Exception):
    pass


def test_data_api_waits_while_aurora_resumes(dqd_json, monkeypatch):
    monkeypatch.setattr("ehr_rwe_eln.dq.dqd.time.sleep", lambda s: None)
    api = FakeDataApi()
    begin = api.begin_transaction
    failures = iter([True, True, False])

    def resuming_then_ready(**kw):
        if next(failures):
            raise DatabaseResumingException("resuming after being auto-paused")
        return begin(**kw)

    api.begin_transaction = resuming_then_ready
    assert save_dqd_data_api(api, "cluster", "secret", "db", read_dqd(dqd_json)) == 7
