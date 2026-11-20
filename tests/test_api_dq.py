import contextlib
import datetime
import importlib

import pytest
from fastapi.testclient import TestClient
from psycopg.rows import dict_row

from ehr_rwe_eln.dq.dqd import RESULT_COLUMNS, DqdRun, save_dqd


@pytest.fixture
def client(pg, dq_schema, monkeypatch):
    monkeypatch.setenv("DB_HOST", "localhost")
    monkeypatch.setenv("DB_PASSWORD", "unused")
    main = importlib.reload(importlib.import_module("ehr_rwe_eln.api.main"))

    def connect():
        # The routes read rows by column name; save_dqd in the test reads them by position.
        pg.row_factory = dict_row
        return contextlib.nullcontext(pg)

    monkeypatch.setattr(main.dq, "connect", connect)
    return TestClient(main.app)


def check(check_id: str, failed: bool) -> dict:
    return {c: None for c in RESULT_COLUMNS} | {
        "check_id": check_id,
        "check_name": "isRequired",
        "check_level": "FIELD",
        "check_description": "required",
        "cdm_table_name": "PERSON",
        "category": "Conformance",
        "context": "Validation",
        "severity": "fatal",
        "failed": failed,
        "passed": not failed,
        "is_error": False,
        "not_applicable": False,
        "execution_seconds": 0.1,
        "query_text": "q",
    }


def test_runs_list_newest_first_and_detail_has_results(pg, client):
    now = datetime.datetime.now(datetime.UTC)
    run = DqdRun(
        now, now, "test", None, None, {"countTotal": 2}, [check("b", True), check("a", False)]
    )
    first, second = save_dqd(pg, run), save_dqd(pg, run)

    listed = client.get("/api/dq/runs").json()
    assert [r["run_id"] for r in listed][:2] == [second, first]
    assert listed[0]["overview"]["countTotal"] == 2

    detail = client.get(f"/api/dq/runs/{first}").json()
    assert detail["run"]["run_id"] == first
    assert [r["check_id"] for r in detail["results"]] == ["a", "b"]
    assert "query_text" not in detail["results"][0]


def test_unknown_run_is_404(client):
    assert client.get("/api/dq/runs/999999").status_code == 404
