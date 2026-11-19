import contextlib
import importlib
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

V = "chr17:1:A:G"


@pytest.fixture
def client(pg, dq_schema, monkeypatch):
    monkeypatch.setenv("DB_HOST", "localhost")
    monkeypatch.setenv("DB_PASSWORD", "unused")
    main = importlib.reload(importlib.import_module("ehr_rwe_eln.api.main"))

    def connect():
        pg.row_factory = dict_row
        return contextlib.nullcontext(pg)

    monkeypatch.setattr(main.curation, "connect", connect)
    return TestClient(main.app)


def run(pg, sources: dict) -> int:
    return pg.execute(
        "INSERT INTO curation.run (created_at, variant_set, sources, summary)"
        " VALUES (%s, 'erepo', %s, '{}') RETURNING run_id",
        [datetime.now(UTC), Jsonb(sources)],
    ).fetchone()[0]


def proposal(pg, run_id, criterion, strength, verified=True) -> int:
    return pg.execute(
        "INSERT INTO curation.proposal (run_id, variant_id, gene, criterion, strength, pmid,"
        " quote, rationale, verified) VALUES (%s, %s, 'BRCA1', %s, %s, '1', 'q', 'r', %s)"
        " RETURNING proposal_id",
        [run_id, V, criterion, strength, verified],
    ).fetchone()[0]


@pytest.fixture
def curated(pg, dq_schema):
    rules = run(pg, {"gnomad": "gnomad_r4"})
    pm2 = {"code": "PM2", "label": "PM2_Supporting", "strength": "supporting", "reason": "absent"}
    ps3 = {"code": "PS3", "label": "PS3", "strength": "strong", "reason": "ENIGMA table"}
    pg.execute(
        "INSERT INTO curation.assessment (run_id, variant_id, gene, hgvsc, evidence, met,"
        " not_assessed, points, classification, expected)"
        " VALUES (%s, %s, 'BRCA1', 'c.1A>G', '{}', %s, '[]', 5, 'Uncertain significance',"
        " 'Pathogenic')",
        [rules, V, Jsonb([pm2, ps3])],
    )
    old = run(pg, {"literature": {}})
    proposal(pg, old, "PS4", "strong")  # superseded by the later literature run
    lit = run(pg, {"literature": {}})
    ids = {
        "ps4": proposal(pg, lit, "PS4", "moderate"),
        "ps4_strong": proposal(pg, lit, "PS4", "strong"),
        "pp1": proposal(pg, lit, "PP1", "supporting"),
        "ps3": proposal(pg, lit, "PS3", "strong"),
        "rejected": proposal(pg, lit, "PP1", "strong", verified=False),
    }
    return rules, ids


def test_sets_list_rules_runs_only_and_variants_count_the_latest_proposals(client, curated):
    rules, _ = curated
    sets = client.get("/api/curation/sets").json()
    assert [(s["variant_set"], s["run_id"], s["variants"]) for s in sets] == [("erepo", rules, 1)]
    [row] = client.get(f"/api/curation/runs/{rules}/variants").json()
    assert row["proposals"] == 4 and row["decision"] is None
    detail = client.get(f"/api/curation/runs/{rules}/variants/{V}").json()
    assert len(detail["proposals"]) == 5 and detail["sources"] == {"gnomad": "gnomad_r4"}
    assert client.get(f"/api/curation/runs/{rules}/variants/nope").status_code == 404


def test_accepted_proposals_add_points_once_each(client, curated):
    rules, ids = curated
    draft = {"run_id": rules, "variant_id": V, "accepted": [ids["ps4"], ids["ps4_strong"]]}
    scored = client.post("/api/curation/score", json=draft).json()
    assert [c["label"] for c in scored["criteria"]] == ["PM2_Supporting", "PS3", "PS4"]
    assert (scored["points"], scored["classification"]) == (9, "Likely pathogenic")
    draft["accepted"].append(ids["pp1"])
    assert client.post("/api/curation/score", json=draft).json()["classification"] == "Pathogenic"


@pytest.mark.parametrize(
    "key, why", [("ps3", "already met by the rules"), ("rejected", "not a verified proposal")]
)
def test_a_proposal_cannot_double_count_or_be_unverified(client, curated, key, why):
    rules, ids = curated
    res = client.post(
        "/api/curation/score", json={"run_id": rules, "variant_id": V, "accepted": [ids[key]]}
    )
    assert res.status_code == 422 and why in res.json()["detail"]


def test_decisions_record_who_and_when_and_keep_history(client, curated):
    rules, ids = curated
    base = {"run_id": rules, "variant_id": V, "curator": " Curator A "}
    first = client.post(
        "/api/curation/decisions", json=base | {"classification": "Uncertain significance"}
    )
    assert first.status_code == 201
    assert first.json()["curator"] == "Curator A" and first.json()["decided_at"]
    second = client.post(
        "/api/curation/decisions",
        json=base | {"accepted": [ids["ps4_strong"]], "classification": "Likely pathogenic"},
    ).json()
    assert second["accepted"] == [ids["ps4_strong"]] and second["computed"] == "Likely pathogenic"
    [row] = client.get(f"/api/curation/runs/{rules}/variants").json()
    assert row["decision"] == "Likely pathogenic"
    history = client.get(f"/api/curation/runs/{rules}/variants/{V}").json()["decisions"]
    assert [d["classification"] for d in history] == ["Likely pathogenic", "Uncertain significance"]
    assert client.get("/api/curation/sets").json()[0]["decided"] == 1


def test_a_class_other_than_the_score_needs_a_note_and_a_name(client, curated):
    rules, _ = curated
    base = {"run_id": rules, "variant_id": V, "classification": "Likely benign"}
    res = client.post("/api/curation/decisions", json=base | {"curator": "A"})
    assert res.status_code == 422 and "needs a note" in res.json()["detail"]
    ok = client.post("/api/curation/decisions", json=base | {"curator": "A", "note": "segregation"})
    assert ok.status_code == 201 and ok.json()["computed"] == "Uncertain significance"
    nameless = client.post("/api/curation/decisions", json=base | {"curator": "  ", "note": "n"})
    assert nameless.status_code == 422
