import contextlib
import importlib
from datetime import date

import pytest
from fastapi.testclient import TestClient
from psycopg.rows import dict_row

from ehr_rwe_eln.eln.models import Extraction, Result, Sample
from ehr_rwe_eln.eln.store import load_entries, load_subjects, save_extraction


@pytest.fixture
def client(pg, dq_schema, monkeypatch):
    monkeypatch.setenv("DB_HOST", "localhost")
    monkeypatch.setenv("DB_PASSWORD", "unused")
    main = importlib.reload(importlib.import_module("ehr_rwe_eln.api.main"))

    def connect():
        pg.row_factory = dict_row
        return contextlib.nullcontext(pg)

    monkeypatch.setattr(main.eln, "connect", connect)
    return TestClient(main.app)


@pytest.fixture
def entries(pg, dq_schema):
    load_subjects(pg, {"HTN-0001": 4242})
    load_entries(
        pg, [(f"E{i}", f"title {i}", "a", date(2020, 1, i), f"body {i}") for i in (1, 2, 3)]
    )
    good = Extraction(
        samples=[
            Sample(sample_id="S-1", subject_id="HTN-0001", specimen_type="serum"),
            Sample(sample_id="S-2", subject_id="HTN-9999", specimen_type="serum"),
        ],
        results=[Result(sample_id="S-1", analyte="crp", value=2.2, unit="mg/L")],
    )
    save_extraction(pg, "E1", "claude-opus-5-5", None, good, None)
    save_extraction(pg, "E2", "claude-opus-5-5", None, None, "stop_reason max_tokens")


def test_summary_and_list_count_each_status(client, entries):
    summary = client.get("/api/eln/summary").json()
    assert {k: summary[k] for k in ("entries", "extracted", "failed", "samples", "results")} == {
        "entries": 3,
        "extracted": 1,
        "failed": 1,
        "samples": 2,
        "results": 1,
    }
    assert summary["models"] == ["claude-opus-5-5"]
    listed = {e["entry_id"]: e for e in client.get("/api/eln/entries").json()}
    assert [listed[i]["status"] for i in ("E1", "E2", "E3")] == ["extracted", "failed", "pending"]
    assert listed["E1"]["samples"] == 2 and listed["E3"]["samples"] is None


def test_entry_says_which_subjects_link_without_the_person_id(client, entries):
    detail = client.get("/api/eln/entries/E1").json()
    assert detail["body"] == "body 1"
    assert detail["subjects"] == [
        {"subject_id": "HTN-0001", "linked": True},
        {"subject_id": "HTN-9999", "linked": False},
    ]
    assert "4242" not in str(detail)
    failed = client.get("/api/eln/entries/E2").json()
    assert failed["error"] == "stop_reason max_tokens" and failed["subjects"] == []


def test_unknown_entry_is_404(client):
    assert client.get("/api/eln/entries/nope").status_code == 404
