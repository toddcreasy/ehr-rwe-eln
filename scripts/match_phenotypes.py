"""Score each genomics study subject's phenotype against the panel genes with the Human Phenotype
Ontology, and check the scores against the panel's answer key.

Usage: uv run python scripts/match_phenotypes.py   (after scripts/generate_panel.py)

Downloads the HPO release named below to data/reference/hpo/<release>/ the first time, and
never changes it. Each subject's OMOP conditions become HPO terms (src/ehr_rwe_eln/curation/
phenotype.py); each gene gets a Resnik similarity score. Writes data/genomics/phenotype_scores.tsv
(by subject_id; the OMOP person_id stays in the registry) and phenotype_eval.json: per gene, how
well the score ranks the gene's pathogenic carriers above everyone else (AUC), next to the most
any phenotype could do here, the AUC of knowing who has the gene's condition.

This service/product is using the Human Phenotype Ontology (release 2026-09-01). Find out more
at http://www.human-phenotype-ontology.org
"""

import json
import urllib.request
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

from ehr_rwe_eln.config import DatabaseSettings
from ehr_rwe_eln.curation.phenotype import (
    information_content,
    load_manual,
    map_conditions,
    read_gene_terms,
    read_obo,
    similarity,
)
from ehr_rwe_eln.genomics.panel import load_panel_spec

RELEASE = "2026-09-01"
FILES = ["hp.obo", "genes_to_phenotype.txt"]
URL = "https://github.com/obophenotype/human-phenotype-ontology/releases/download/v{release}/{name}"
DATA = Path(__file__).resolve().parent.parent / "data"
HPO = DATA / "reference" / "hpo" / RELEASE
STUDY = DATA / "genomics"
REGISTRY = DATA / "registry" / "genomics_subjects.tsv"

CONDITIONS_SQL = """
SELECT DISTINCT person_id, condition_concept_id FROM cdm.condition_occurrence
WHERE person_id = ANY(%s) AND condition_concept_id <> 0
"""
# Each concept and its ancestors, nearest first, with names, so a concept with no HPO match
# can take its nearest mapped ancestor's term.
ANCESTORS_SQL = """
SELECT ca.descendant_concept_id, ca.ancestor_concept_id, c.concept_name
FROM cdm.concept_ancestor ca JOIN cdm.concept c ON c.concept_id = ca.ancestor_concept_id
WHERE ca.descendant_concept_id = ANY(%s)
ORDER BY ca.descendant_concept_id, ca.min_levels_of_separation
"""
FLAGS_SQL = """
SELECT DISTINCT co.person_id
FROM cdm.condition_occurrence co
JOIN cdm.concept_ancestor ca ON ca.descendant_concept_id = co.condition_concept_id
WHERE ca.ancestor_concept_id = %s AND co.person_id = ANY(%s)
"""


def fetch() -> None:
    HPO.mkdir(parents=True, exist_ok=True)
    for name in FILES:
        if not (HPO / name).exists():
            url = URL.format(release=RELEASE, name=name)
            print(f"downloading {url}")
            urllib.request.urlretrieve(url, HPO / name)  # noqa: S310  (fixed https URL)


def auc(y: np.ndarray, score: np.ndarray, rng: np.random.Generator, n: int = 1000) -> dict:
    """AUC with a 95% bootstrap interval: resample people with replacement, keep resamples
    that have both carriers and non-carriers, and take the 2.5th and 97.5th percentiles."""
    draws = []
    for _ in range(n):
        i = rng.integers(0, len(y), len(y))
        if 0 < y[i].sum() < len(i):
            draws.append(roc_auc_score(y[i], score[i]))
    low, high = np.percentile(draws, [2.5, 97.5])
    return {"auc": round(roc_auc_score(y, score), 3), "ci95": [round(low, 3), round(high, 3)]}


def main() -> None:
    fetch()
    ont = read_obo(HPO / "hp.obo")
    gene_terms = read_gene_terms(HPO / "genes_to_phenotype.txt", ont)
    ic = information_content(ont, gene_terms)
    spec = load_panel_spec()
    genes = list(spec.genes)

    mapping = pd.read_csv(STUDY / "subject_sample_mapping.tsv", sep="\t")
    registry = pd.read_csv(REGISTRY, sep="\t").set_index("subject_id")["person_id"]
    subjects = mapping["subject_id"].tolist()
    person_of = {s: int(registry.loc[s]) for s in subjects}
    people = list(person_of.values())

    with DatabaseSettings().connect() as con:
        rows = con.execute(CONDITIONS_SQL, [people]).fetchall()
        concept_ids = sorted({c for _, c in rows})
        names, ancestors = {}, defaultdict(list)
        for d, a, name in con.execute(ANCESTORS_SQL, [concept_ids]):
            names[a] = name
            if a != d:
                ancestors[d].append(a)
        flags = {
            c.name: {r[0] for r in con.execute(FLAGS_SQL, [c.concept_id, people])}
            for c in spec.conditions
        }

    mapped = map_conditions(names, ancestors, ont, load_manual(ont))
    terms: dict[int, set[str]] = defaultdict(set)
    for person, concept in rows:
        if concept in mapped:
            terms[person].add(mapped[concept]["hpo"])

    truth = json.loads((STUDY / "panel_truth.json").read_text())
    carriers = defaultdict(set)
    for v in truth["variants"]:
        if v["role"] == "pathogenic":
            carriers[v["gene"]].update(v["carrier_subjects"])
    has = {
        name: np.array([person_of[s] in found for s in subjects]) for name, found in flags.items()
    }
    groups = {c.name: list(c.genes) for c in spec.conditions}
    rng = np.random.default_rng(0)

    out = pd.DataFrame({"subject_id": subjects})
    out["hpo_terms"] = [len(terms[person_of[s]]) for s in subjects]
    results = {}
    for aggregate in ("mean", "max"):
        raw = np.array(
            [
                [similarity(terms[person_of[s]], gene_terms[g], ont, ic, aggregate) for g in genes]
                for s in subjects
            ]
        )
        # Raw scores are not comparable across genes (a gene annotated with common conditions
        # scores high for everyone), so each gene's score is standardized over the study.
        z = (raw - raw.mean(axis=0)) / raw.std(axis=0)
        if aggregate == "mean":
            for j, g in enumerate(genes):
                out[g] = z[:, j].round(3)
        score = dict(zip(genes, z.T, strict=True))
        by_gene = {}
        for g in genes:
            y = np.isin(subjects, list(carriers[g]))
            by_gene[g] = {"carriers": int(y.sum()), **auc(y, score[g], rng)}
        by_group = {}
        top = z.argmax(axis=1)
        for name, members in groups.items():
            y = np.isin(subjects, list(set().union(*(carriers[g] for g in members))))
            with_condition = np.flatnonzero(y & has[name])
            by_group[name] = {
                "carriers": int(y.sum()),
                "carriers_with_condition": len(with_condition),
                **auc(y, np.max([score[g] for g in members], axis=0), rng),
                "condition_auc": round(roc_auc_score(y, has[name]), 3),
                "top_gene_in_group": int(sum(genes[top[i]] in members for i in with_condition)),
            }
        results[aggregate] = {"genes": by_gene, "groups": by_group}
    out.to_csv(STUDY / "phenotype_scores.tsv", sep="\t", index=False)

    seen = {c for _, c in rows}
    summary = {
        "hpo_release": ont.release,
        "subjects": len(subjects),
        "condition_concepts": len(seen),
        "concepts_mapped": {
            m: sum(1 for c in seen if mapped.get(c, {}).get("method") == m)
            for m in ("table", "name", "ancestor")
        },
        "person_conditions_mapped": round(sum(c in mapped for _, c in rows) / len(rows), 3),
        "median_terms_per_subject": float(out["hpo_terms"].median()),
        "score": "Resnik best match average, standardized per gene over the study",
        **results["mean"],
        "sensitivity_single_best_term": results["max"],
    }
    (STUDY / "phenotype_eval.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    print(
        "This service/product is using the Human Phenotype Ontology"
        f" (release {ont.release}). Find out more at http://www.human-phenotype-ontology.org"
    )


if __name__ == "__main__":
    main()
