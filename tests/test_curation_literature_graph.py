import json
from datetime import UTC, datetime

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.postgres.base import BasePostgresSaver
from langgraph.types import Command
from psycopg.types.json import Jsonb

import ehr_rwe_eln.curation.literature as literature
from ehr_rwe_eln.curation import literature_graph
from ehr_rwe_eln.curation.literature import Claim, Proposals
from ehr_rwe_eln.curation.literature_graph import Deps, build, config

V = "chr17:43057062:C:T"
QUOTE = "The R1699Q variant abolished transcriptional activity in our assay."
START = {"variant_id": V, "gene": "BRCA1", "hgvsc": "c.5096G>A", "hgvsp": "p.Arg1699Gln"}


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    monkeypatch.setattr(literature.time, "sleep", lambda s: None)


def ncbi(pmids: list[str], text: str):
    """LitVar2 and PubTator3 as fakes: one variant, and one passage per PMID."""

    def get(url):
        if "autocomplete" in url:
            body = [{"_id": "litvar@x", "gene": ["BRCA1"], "hgvs": "p.R1699Q", "rsid": None}]
        elif "publications" in url and "litvar" in url:
            body = {"pmids": pmids}
        else:
            body = {
                "PubTator3": [
                    {"id": p, "date": "2020", "passages": [{"text": text, "infons": {}}]}
                    for p in pmids
                ]
            }
        return json.dumps(body).encode()

    return get


def claude(claims: list[Claim], calls: list):
    def propose(text, client=None, model=None):
        calls.append(text)
        return Proposals(claims=claims), {"input": 10, "output": 5}

    return propose


def new_run(pg, sources: dict) -> int:
    return pg.execute(
        "INSERT INTO curation.run (created_at, variant_set, sources, summary)"
        " VALUES (%s, 'erepo', %s, '{}') RETURNING run_id",
        [datetime.now(UTC), Jsonb(sources)],
    ).fetchone()[0]


@pytest.fixture
def rules_run(pg, dq_schema):
    """The rules run whose assessment a decision is about."""
    run_id = new_run(pg, {"gnomad": "gnomad_r4"})
    pg.execute(
        "INSERT INTO curation.assessment (run_id, variant_id, gene, hgvsc, evidence, met,"
        " not_assessed, points, classification) VALUES (%s, %s, 'BRCA1', 'c.5096G>A', '{}',"
        " '[]', '[]', 0, 'Uncertain significance')",
        [run_id, V],
    )
    return run_id


@pytest.fixture
def run_id(pg, rules_run):
    """The literature run the graph files proposals under."""
    return new_run(pg, {"literature": {}})


def decision(rules_run: int, classification: str) -> dict:
    return {
        "run_id": rules_run,
        "variant_id": V,
        "curator": "Curator A",
        "accepted": [],
        "criteria": [],
        "points": 0,
        "computed": "Uncertain significance",
        "classification": classification,
        "note": None if classification == "Uncertain significance" else "curator's reason",
    }


def test_a_run_stores_verified_and_rejected_claims_then_waits_for_each_decision(
    pg, rules_run, run_id, tmp_path, monkeypatch
):
    calls = []
    monkeypatch.setattr(
        literature,
        "propose",
        claude(
            [
                Claim(criterion="PS3", strength="strong", pmid="1", quote=QUOTE, rationale="r"),
                Claim(criterion="PS4", strength="moderate", pmid="9", quote=QUOTE, rationale="r"),
            ],
            calls,
        ),
    )
    graph = build(InMemorySaver())
    deps = Deps(con=pg, reference=tmp_path, get=ncbi(["1"], QUOTE))
    cfg = config(run_id, V)

    state = graph.invoke({"run_id": run_id, **START}, cfg, context=deps)
    assert len(calls) == 1 and "R1699Q" in calls[0]
    assert [c["criterion"] for c in state["verified"]] == ["PS3"]
    assert state["rejected"][0]["why"] == "PMID was not among the passages sent"
    assert graph.get_state(cfg).next == ("curator",)
    stored = pg.execute(
        "SELECT criterion, verified FROM curation.proposal WHERE run_id = %s ORDER BY 1",
        [run_id],
    ).fetchall()
    assert stored == [("PS3", True), ("PS4", False)]

    for cls in ("Uncertain significance", "Likely pathogenic"):
        state = graph.invoke(Command(resume=decision(rules_run, cls)), cfg, context=deps)
        assert graph.get_state(cfg).next == ("curator",)  # waiting again: decisions keep history
    assert [d["classification"] for d in state["decisions"]] == [
        "Uncertain significance",
        "Likely pathogenic",
    ]
    assert len(calls) == 1  # resuming never calls Claude again
    assert pg.execute(
        "SELECT count(*) FROM curation.decision WHERE variant_id = %s", [V]
    ).fetchone() == (2,)


def test_a_variant_no_passage_names_ends_without_calling_claude(pg, run_id, tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(literature, "propose", claude([], calls))
    graph = build(InMemorySaver())
    cfg = config(run_id, V)
    deps = Deps(con=pg, reference=tmp_path, get=ncbi(["1"], "A paper about another variant."))
    state = graph.invoke({"run_id": run_id, **START}, cfg, context=deps)
    assert state["passages"] == [] and calls == []
    assert graph.get_state(cfg).next == ()


def test_postgres_checkpoints_resume_on_a_new_connection(
    pg, rules_run, run_id, tmp_path, monkeypatch
):
    monkeypatch.setenv("DB_NAME", "ehr_rwe_eln_test")
    monkeypatch.setattr(literature, "propose", claude([], []))
    deps = Deps(con=pg, reference=tmp_path, get=ncbi(["1"], QUOTE))
    cfg = config(run_id, V)
    with literature_graph.checkpointer() as saver:
        # Migration 021 made the library's own tables: setup() has nothing left to apply.
        saver.setup()
        found = saver.conn.execute("SELECT max(v) AS v FROM checkpoint_migrations").fetchone()
        assert found["v"] == len(BasePostgresSaver.MIGRATIONS) - 1
        build(saver).invoke({"run_id": run_id, **START}, cfg, context=deps)
    try:
        with literature_graph.checkpointer() as saver:
            graph = build(saver)
            assert graph.get_state(cfg).next == ("curator",)
            state = graph.invoke(Command(resume=decision(rules_run, "Benign")), cfg, context=deps)
            assert state["decisions"][-1]["classification"] == "Benign"
    finally:
        with literature_graph.checkpointer() as saver:
            saver.delete_thread(cfg["configurable"]["thread_id"])
