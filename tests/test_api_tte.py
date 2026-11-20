import contextlib
import datetime
import importlib
import json

import pytest
from fastapi.testclient import TestClient
from psycopg.rows import dict_row

from ehr_rwe_eln.cohort.cdm import create_cdm
from ehr_rwe_eln.tte.propensity import fit_propensity
from ehr_rwe_eln.tte.report import (
    Arm,
    NegativeControl,
    Report,
    omop_summary,
    report_json,
    save_run,
)
from ehr_rwe_eln.tte.survival import analyze

from .test_tte_survival import confounded, protocol


@pytest.fixture
def client(pg, dq_schema, monkeypatch):
    monkeypatch.setenv("DB_HOST", "localhost")
    monkeypatch.setenv("DB_PASSWORD", "unused")
    main = importlib.reload(importlib.import_module("ehr_rwe_eln.api.main"))

    def connect():
        pg.row_factory = dict_row
        return contextlib.nullcontext(pg)

    monkeypatch.setattr(main.tte, "connect", connect)
    return TestClient(main.app)


def full_report() -> Report:
    table, p = confounded(), protocol(5)
    return Report(
        p,
        [("first use of either strategy", len(table))],
        [Arm("a", int(table.arm.sum()), int(table.event[table.arm == 1].sum()), 1825.0)],
        propensity=fit_propensity(table, p),
        survival=analyze(table, p),
        negative_controls=[NegativeControl("nc", 100, 10, 1.2, (1.05, 1.4))],
    )


def test_report_json_is_plain_json_with_every_section():
    out = report_json(full_report())
    assert json.loads(json.dumps(out)) == json.loads(json.dumps(out, allow_nan=False))
    assert out["survival"]["hazard_ratio"] == pytest.approx(0.5, abs=0.08)
    assert set(out["survival"]["bootstrap_ci"]["hazard_ratio"]) == {"low", "high"}
    assert {b["covariate"] for b in out["balance"]} == {"age", "male"}
    assert out["negative_controls"][0]["excludes_null"] is True


def test_runs_list_newest_first_and_detail_has_reports(pg, client):
    create_cdm(pg)
    stopped = Report(protocol(0).model_copy(update={"id": 2}), [], [], not_estimable="no overlap")
    now = datetime.datetime.now(datetime.UTC)
    source, persons = omop_summary(pg)
    first = save_run(pg, [stopped, full_report()], now, source, persons)
    second = save_run(pg, [stopped], now, source, persons)

    listed = client.get("/api/tte/runs").json()
    assert [r["run_id"] for r in listed][:2] == [second, first]
    assert listed[0]["persons"] == 0

    detail = client.get(f"/api/tte/runs/{first}").json()
    assert [r["protocol"]["id"] for r in detail["reports"]] == [1, 2]
    assert detail["reports"][1]["not_estimable"] == "no overlap"
    assert detail["reports"][1]["survival"] is None


def test_unknown_run_is_404(client):
    assert client.get("/api/tte/runs/999999").status_code == 404
