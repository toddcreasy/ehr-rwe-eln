import contextlib
import datetime
import importlib

import pytest
from fastapi.testclient import TestClient
from psycopg.rows import dict_row

from ehr_rwe_eln.cohort.cdm import create_cdm
from ehr_rwe_eln.dq.checks import load_checks
from ehr_rwe_eln.dq.run import save_run
from ehr_rwe_eln.dq.scoring import Result, evaluate


@pytest.fixture
def client(pg, dq_schema, monkeypatch):
    monkeypatch.setenv("DB_HOST", "localhost")
    monkeypatch.setenv("DB_PASSWORD", "unused")
    main = importlib.reload(importlib.import_module("ehr_rwe_eln.api.main"))

    def connect():
        # The routes read rows by column name; save_run in the test reads them by position.
        pg.row_factory = dict_row
        return contextlib.nullcontext(pg)

    monkeypatch.setattr(main.dq, "connect", connect)
    return TestClient(main.app)


def test_runs_list_newest_first_and_detail_has_results(pg, client):
    create_cdm(pg)
    checks = load_checks()[:2]
    results = [Result(checks[0], 0, 5, None, 0.1, "q"), Result(checks[1], 2, 5, None, 0.1, "q")]
    evaluate(results)
    now = datetime.datetime.now(datetime.UTC)
    first, second = save_run(pg, results, now), save_run(pg, results, now)

    listed = client.get("/api/dq/runs").json()
    assert [r["run_id"] for r in listed][:2] == [second, first]
    assert listed[0]["overview"]["countTotal"] == 2

    detail = client.get(f"/api/dq/runs/{first}").json()
    assert detail["run"]["run_id"] == first
    assert [r["check_id"] for r in detail["results"]] == sorted(c.check_id for c in checks)
    assert "query_text" not in detail["results"][0]


def test_unknown_run_is_404(client):
    assert client.get("/api/dq/runs/999999").status_code == 404
