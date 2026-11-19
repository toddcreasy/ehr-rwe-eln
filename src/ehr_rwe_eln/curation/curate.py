"""Curate a set of variants with the rules, score an eval run, and store a run.

An eval run scores the rules against ClinVar expert-panel classifications in three tiers:
pathogenic or likely pathogenic, uncertain significance, benign or likely benign. The number
that matters most is reversals: a variant the panel calls pathogenic that the rules call
benign, or the other way round. Calling a pathogenic variant uncertain is a miss a curator
can fix with more evidence; a reversal is an error.
"""

import hashlib
from collections import Counter
from datetime import UTC, datetime

import psycopg
from psycopg.types.json import Jsonb

from ehr_rwe_eln.curation.rules import RULES, Rules, assess
from ehr_rwe_eln.synth.release import code_version

TIERS = {
    "Pathogenic": "P/LP",
    "Likely pathogenic": "P/LP",
    "Likely_pathogenic": "P/LP",
    "Pathogenic/Likely_pathogenic": "P/LP",
    "Uncertain significance": "VUS",
    "Uncertain_significance": "VUS",
    "Likely benign": "B/LB",
    "Likely_benign": "B/LB",
    "Benign": "B/LB",
    "Benign/Likely_benign": "B/LB",
}
ORDER = ["P/LP", "VUS", "B/LB"]


def curate(
    variants: list[dict],
    rules: Rules,
    frequencies: dict[str, dict | None],
    consequences: dict[str, dict | None],
    exon_lengths: dict[str, list[int]],
) -> list[dict]:
    """variants: dicts with id (chr:pos:ref:alt), gnomad_id, and for eval runs expected.
    Variants VEP places in none of the rules' genes are skipped."""
    out = []
    for v in variants:
        vep = consequences[v["gnomad_id"]]
        if vep is None or vep["gene"] not in rules.genes:
            continue
        frequency = frequencies[v["gnomad_id"]]
        result = assess(
            rules.genes[vep["gene"]], frequency, vep, exon_lengths.get(vep["transcript"], [])
        )
        out.append(
            {
                "variant_id": v["id"],
                "gene": vep["gene"],
                "hgvsc": vep["hgvsc"],
                "hgvsp": vep["hgvsp"],
                "evidence": {"gnomad": frequency, "vep": vep},
                "expected": v.get("expected"),
            }
            | result
        )
    return out


def score(assessments: list[dict]) -> dict:
    """Agreement with the expected classification, overall and per gene, in three tiers."""
    scored = [a for a in assessments if a.get("expected") in TIERS]
    pairs = [(TIERS[a["expected"]], TIERS[a["classification"]]) for a in scored]

    def summary(rows: list[tuple[str, str]]) -> dict:
        confusion = Counter(rows)
        return {
            "variants": len(rows),
            "agreement": sum(e == c for e, c in rows) / len(rows) if rows else None,
            "reversals": confusion[("P/LP", "B/LB")] + confusion[("B/LB", "P/LP")],
            "confusion": {e: {c: confusion[(e, c)] for c in ORDER} for e in ORDER},
        }

    genes = sorted({a["gene"] for a in scored})
    return summary(pairs) | {
        "by_gene": {
            g: summary([p for a, p in zip(scored, pairs, strict=True) if a["gene"] == g])
            for g in genes
        },
        "criteria": dict(Counter(c["label"] for a in scored for c in a["met"]).most_common()),
    }


def sources(rules: Rules, gnomad_dataset: str, ensembl: int, clinvar: str | None) -> dict:
    return {
        "gnomad": gnomad_dataset,
        "ensembl": ensembl,
        "clinvar": clinvar,
        "rules_sha256": hashlib.sha256(RULES.read_bytes()).hexdigest()[:16],
        "cspec": {g: f"{r.cspec} v{r.version}" for g, r in rules.genes.items()},
    }


def save_run(
    con: psycopg.Connection,
    variant_set: str,
    run_sources: dict,
    assessments: list[dict],
    summary: dict,
) -> int:
    run_id = con.execute(
        "INSERT INTO curation.run (created_at, variant_set, sources, code_version, summary)"
        " VALUES (%s, %s, %s, %s, %s) RETURNING run_id",
        [datetime.now(UTC), variant_set, Jsonb(run_sources), code_version(), Jsonb(summary)],
    ).fetchone()[0]
    with con.cursor() as cur:
        cur.executemany(
            "INSERT INTO curation.assessment (run_id, variant_id, gene, hgvsc, hgvsp, evidence,"
            " met, not_assessed, points, classification, expected)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            [
                [
                    run_id,
                    a["variant_id"],
                    a["gene"],
                    a["hgvsc"],
                    a["hgvsp"],
                    Jsonb(a["evidence"]),
                    Jsonb(a["met"]),
                    Jsonb(a["not_assessed"]),
                    a["points"],
                    a["classification"],
                    a.get("expected"),
                ]
                for a in assessments
            ],
        )
    return run_id
