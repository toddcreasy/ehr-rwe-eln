import contextlib
import importlib

import pytest
from fastapi.testclient import TestClient
from psycopg.rows import dict_row

from ehr_rwe_eln.synth.bayes_net import plan, synthesize
from ehr_rwe_eln.synth.fidelity import fidelity_report
from ehr_rwe_eln.synth.release import save_release, save_report

from .test_synth import AGE, DRUG, FLAG, spec, toy


@pytest.fixture
def client(pg, dq_schema, monkeypatch):
    monkeypatch.setenv("DB_HOST", "localhost")
    monkeypatch.setenv("DB_PASSWORD", "unused")
    main = importlib.reload(importlib.import_module("ehr_rwe_eln.api.main"))

    def connect():
        pg.row_factory = dict_row
        return contextlib.nullcontext(pg)

    monkeypatch.setattr(main.synth, "connect", connect)
    return TestClient(main.app)


def test_releases_carry_headline_numbers_and_detail_has_the_card(pg, client):
    s = spec(AGE, FLAG, DRUG)
    train, holdout = toy(2000, 1), toy(1000, 2)
    out, measurements = synthesize(train, s, s.releases[0])
    evaluated = save_release(pg, s, s.releases[0], plan(measurements), out, len(train), 1000)
    fidelity = fidelity_report(train, out, s.columns)
    fidelity["noise_floor"] = fidelity_report(train, holdout, s.columns)["summary"]
    save_report(pg, evaluated, "fidelity", fidelity)
    bare = save_release(pg, s, s.releases[0], plan(measurements), out, len(train), 1000)

    listed = {r["release_id"]: r for r in client.get("/api/synth/releases").json()}
    assert listed[evaluated]["pair_tvd_mean"] == pytest.approx(fidelity["summary"]["pair_tvd_mean"])
    assert listed[evaluated]["pair_tvd_floor"] is not None
    assert listed[bare]["pair_tvd_mean"] is None  # not evaluated yet
    assert listed[bare]["membership_auc"] is None

    card = client.get(f"/api/synth/releases/{evaluated}").json()["card"]
    assert card.startswith(f"# Data card: synthetic release {evaluated}")
    assert "## Fidelity" in card


def test_unknown_release_is_404(client):
    assert client.get("/api/synth/releases/999999").status_code == 404


def test_monitor_reports_the_latest_check(pg, client):
    assert client.get("/api/synth/monitor").json() is None
    pg.execute(
        "INSERT INTO synth.monitor_run (started_at, finished_at, fingerprints, skipped,"
        " releases_checked, flags) VALUES (now(), now(), '{}', false, 3, '[]'),"
        " (now(), now(), '{}', true, 0, '[]')"
    )
    found = client.get("/api/synth/monitor").json()
    assert found["latest"]["skipped"] is True
    assert found["last_evaluated"]["releases_checked"] == 3
