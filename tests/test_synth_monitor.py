import pytest

from ehr_rwe_eln.synth import monitor
from ehr_rwe_eln.synth.bayes_net import plan, synthesize
from ehr_rwe_eln.synth.release import save_release
from ehr_rwe_eln.synth.spec import Spec

from .test_synth import AGE, DRUG, FLAG, spec, toy

TRAIN, HOLDOUT = toy(1500, 1), toy(700, 2)


@pytest.fixture
def source(monkeypatch):
    """The monitor reads sources from OMOP; here every spec's source is the toy tables."""
    tables = {"train": TRAIN, "holdout": HOLDOUT}
    monkeypatch.setattr(monitor, "build_source", lambda con, spec: None)
    monkeypatch.setattr(monitor, "split", lambda table, spec: (tables["train"], tables["holdout"]))
    return tables


def release(pg, s: Spec, rows=None) -> int:
    out, measurements = synthesize(TRAIN, s, s.releases[0])
    rows = out if rows is None else rows
    return save_release(pg, s, s.releases[0], plan(measurements), rows, len(TRAIN), len(HOLDOUT))


def test_a_check_runs_once_per_change(pg, dq_schema, source):
    release(pg, spec(AGE, FLAG, DRUG))
    first = monitor.run_once(pg)
    assert not first["skipped"] and first["releases_checked"] == 1 and first["flags"] == []
    assert pg.execute("SELECT count(*) FROM synth.report WHERE kind = 'privacy'").fetchone()[0] == 1
    # Same data, same code: the seeded attacks would give the same answer, so skip.
    assert monitor.run_once(pg)["skipped"]
    source["train"] = toy(1500, 3)  # the source changed (new lab results, a rebuild)
    assert not monitor.run_once(pg)["skipped"]


def test_a_copy_of_the_training_data_is_flagged(pg, dq_schema, source):
    copied = release(pg, spec(AGE, FLAG, DRUG), rows=TRAIN)
    run = monitor.run_once(pg)
    assert {f["release_id"] for f in run["flags"]} == {copied}
    assert any(f["flag"].startswith("membership inference AUC") for f in run["flags"])
    stored = pg.execute(
        "SELECT flags FROM synth.monitor_run WHERE run_id = %s", [run["run_id"]]
    ).fetchone()[0]
    assert stored == run["flags"]


def test_a_controlled_source_without_approval_is_not_attacked(pg, dq_schema, source):
    fields = spec(AGE, FLAG, DRUG).model_dump()
    controlled = Spec(
        **fields | {"source_access": "controlled", "seed": None, "approved_users": ["A"]}
    )
    release(pg, controlled)
    run = monitor.run_once(pg)
    assert run["releases_checked"] == 0 and not run["skipped"]
    assert pg.execute("SELECT count(*) FROM synth.report").fetchone()[0] == 0
