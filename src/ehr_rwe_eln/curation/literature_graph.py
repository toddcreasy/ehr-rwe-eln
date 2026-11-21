"""Literature curation as a LangGraph graph: the steps in curation/literature.py, plus the pause
for the curator.

    retrieve -> (no passage names the variant: end)
       |
    propose -> verify -> store -> curator <-+
                                     |      |
                                     +------+  one loop per decision

Each node is a plain function over State. After every node LangGraph saves State as a checkpoint
(Postgres, the langgraph schema, migration 021) under the run's thread ID, one thread per
literature run and variant. The curator node pauses the run with interrupt() until a curator
decides on /curation/; the decisions route resumes it with the decision, the node records it,
and the run pauses again, since a variant can be decided more than once (curation.decision keeps
the history).

Nodes never commit: the caller owns the database transaction. Claude is called once, in propose,
through propose() and claude_client(), the same call the eval scores.
"""

import operator
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, TypedDict

import anthropic
import psycopg
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import interrupt
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from ehr_rwe_eln.config import DatabaseSettings
from ehr_rwe_eln.curation import literature
from ehr_rwe_eln.curation.literature import Proposals


class State(TypedDict, total=False):
    run_id: int  # the literature run, in curation.run
    variant_id: str
    gene: str
    hgvsc: str | None
    hgvsp: str | None
    litvar: dict | None  # the LitVar2 record: id, rsid, PMIDs
    passages: list[dict]  # what Claude was sent, kept so the curator judges the same text
    claims: list[dict]  # Claude's proposals, before verification
    usage: dict
    verified: list[dict]
    rejected: list[dict]
    proposal_ids: list[int]
    decisions: Annotated[list[dict], operator.add]  # every decision recorded, in order


@dataclass
class Deps:
    """What the nodes need that isn't state: passed to each invoke, never checkpointed."""

    con: psycopg.Connection
    reference: Path = Path("data/reference")
    client: anthropic.AnthropicBedrock | None = None
    model: str | None = None
    get: Callable = field(default=literature._get)


def thread_id(run_id: int, variant_id: str) -> str:
    return f"literature-{run_id}-{variant_id}"


def config(run_id: int, variant_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id(run_id, variant_id)}}


def retrieve(state: State, runtime: Runtime[Deps]) -> dict:
    deps, gene = runtime.context, state["gene"]
    hgvsc, hgvsp = state.get("hgvsc"), state.get("hgvsp")
    found = literature.find_variant(
        gene, hgvsc, hgvsp, deps.reference / "litvar" / "variants.json", deps.get
    )
    if found is None:
        return {"litvar": None, "passages": []}
    text = literature.passages(
        found["pmids"],
        literature.names(gene, hgvsc, hgvsp, found["rsid"]),
        f"{gene}|{hgvsc}|{hgvsp}",
        deps.reference / "pubtator" / "passages.json",
        deps.get,
    )
    return {"litvar": found, "passages": text}


def after_retrieve(state: State) -> str:
    return "propose" if state["passages"] else END


def propose(state: State, runtime: Runtime[Deps]) -> dict:
    deps = runtime.context
    text = literature.prompt(
        state["gene"], state.get("hgvsc"), state.get("hgvsp"), state["passages"]
    )
    proposals, usage = literature.propose(text, deps.client, deps.model)
    return {"claims": proposals.model_dump()["claims"], "usage": usage}


def verify(state: State) -> dict:
    verified, rejected = literature.verify(
        Proposals.model_validate({"claims": state["claims"]}), state["passages"]
    )
    return {"verified": verified, "rejected": rejected}


def store(state: State, runtime: Runtime[Deps]) -> dict:
    """Every claim to curation.proposal, verified or not, as the UI and the decisions route read
    them there."""
    claims = [(c, True) for c in state["verified"]] + [(c, False) for c in state["rejected"]]
    ids = [
        runtime.context.con.execute(
            "INSERT INTO curation.proposal (run_id, variant_id, gene, criterion, strength,"
            " pmid, quote, rationale, verified, rejected_why)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING proposal_id",
            [
                state["run_id"],
                state["variant_id"],
                state["gene"],
                c["criterion"],
                c["strength"],
                c["pmid"],
                c["quote"],
                c["rationale"],
                ok,
                c.get("why"),
            ],
        ).fetchone()[0]
        for c, ok in claims
    ]
    return {"proposal_ids": ids}


DECISION_SQL = """
INSERT INTO curation.decision (run_id, variant_id, curator, accepted, criteria, points, computed,
    classification, note)
VALUES (%(run_id)s, %(variant_id)s, %(curator)s, %(accepted)s, %(criteria)s, %(points)s,
    %(computed)s, %(classification)s, %(note)s)
RETURNING *
"""


def record_decision(con: psycopg.Connection, decision: dict) -> dict:
    """One curator decision into curation.decision, as a dict whatever the connection's rows."""
    with con.cursor(row_factory=dict_row) as cur:
        return cur.execute(
            DECISION_SQL, decision | {"criteria": Jsonb(decision["criteria"])}
        ).fetchone()


def curator(state: State, runtime: Runtime[Deps]) -> dict:
    """Pause until a curator decides, then record the decision. On resume LangGraph runs this
    node again from the top and interrupt() returns the decision instead of pausing."""
    decision = interrupt({"variant_id": state["variant_id"], "proposal_ids": state["proposal_ids"]})
    return {"decisions": [record_decision(runtime.context.con, decision)]}


def build(checkpointer: BaseCheckpointSaver):
    graph = StateGraph(State, context_schema=Deps)
    graph.add_node("retrieve", retrieve)
    graph.add_node("propose", propose)
    graph.add_node("verify", verify)
    graph.add_node("store", store)
    graph.add_node("curator", curator)
    graph.add_edge(START, "retrieve")
    graph.add_conditional_edges("retrieve", after_retrieve, ["propose", END])
    graph.add_edge("propose", "verify")
    graph.add_edge("verify", "store")
    graph.add_edge("store", "curator")
    graph.add_edge("curator", "curator")
    return graph.compile(checkpointer=checkpointer)


@contextmanager
def checkpointer() -> Iterator[PostgresSaver]:
    """Checkpoints in the app database's langgraph schema, on their own connection: the saver
    commits each checkpoint as it writes it (autocommit), apart from the caller's transaction."""
    with DatabaseSettings().connect(
        autocommit=True,
        prepare_threshold=0,
        row_factory=dict_row,
        options="-c search_path=langgraph",
    ) as con:
        yield PostgresSaver(con)
