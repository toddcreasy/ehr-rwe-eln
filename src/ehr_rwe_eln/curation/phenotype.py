"""Phenotype matching with the Human Phenotype Ontology (HPO): each person's OMOP conditions as
HPO terms, scored against each gene's HPO annotations.

This service/product is using the Human Phenotype Ontology (release named in the run). Find
out more at http://www.human-phenotype-ontology.org. HPO files are read, never changed.
"""

import csv
import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import yaml

CONDITIONS = Path(__file__).parent / "hpo_conditions.yaml"
SYNONYM = re.compile(r'^synonym: "(.*)" EXACT')


@dataclass
class Ontology:
    release: str
    names: dict[str, str] = field(default_factory=dict)
    parents: dict[str, list[str]] = field(default_factory=dict)
    synonyms: dict[str, list[str]] = field(default_factory=dict)
    alt: dict[str, str] = field(default_factory=dict)  # retired id -> current id
    obsolete: set[str] = field(default_factory=set)
    _ancestors: dict[str, frozenset[str]] = field(default_factory=dict, repr=False)

    def ancestors(self, term: str) -> frozenset[str]:
        """The term and every term above it on is_a links."""
        found = self._ancestors.get(term)
        if found is None:
            found = frozenset({term}).union(*(self.ancestors(p) for p in self.parents[term]))
            self._ancestors[term] = found
        return found

    def current(self, term: str) -> str | None:
        term = self.alt.get(term, term)
        return term if term in self.names and term not in self.obsolete else None


def read_obo(path: Path) -> Ontology:
    ont, term, in_term = Ontology(release=""), None, False
    for line in path.open(encoding="utf-8"):
        line = line.rstrip("\n")
        if line.startswith("data-version: "):
            ont.release = line.removeprefix("data-version: ").removeprefix("hp/releases/")
        elif line.startswith("["):
            in_term, term = line == "[Term]", None
        elif not in_term:
            continue
        elif line.startswith("id: HP:"):
            term = line[4:]
            ont.parents[term] = []
        elif term is None:
            continue
        elif line.startswith("name: "):
            ont.names[term] = line[6:]
        elif line.startswith("is_a: HP:"):
            ont.parents[term].append(line[6:16])
        elif line.startswith("alt_id: HP:"):
            ont.alt[line[8:]] = term
        elif line == "is_obsolete: true":
            ont.obsolete.add(term)
        elif m := SYNONYM.match(line):
            ont.synonyms.setdefault(term, []).append(m.group(1))
    return ont


def read_gene_terms(path: Path, ont: Ontology) -> dict[str, set[str]]:
    """genes_to_phenotype.txt: each gene's HPO terms, over all its diseases."""
    out: dict[str, set[str]] = defaultdict(set)
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            if term := ont.current(row["hpo_id"]):
                out[row["gene_symbol"]].add(term)
    return dict(out)


def information_content(ont: Ontology, gene_terms: dict[str, set[str]]) -> dict[str, float]:
    """IC(t) = -ln(share of genes annotated to t or a term below it). A term every gene has
    scores 0; a term one gene has scores highest."""
    counts: dict[str, int] = defaultdict(int)
    for terms in gene_terms.values():
        for t in set().union(*(ont.ancestors(t) for t in terms)):
            counts[t] += 1
    n = len(gene_terms)
    return {t: -math.log(c / n) for t, c in counts.items()}


def similarity(
    person: set[str],
    gene: set[str],
    ont: Ontology,
    ic: dict[str, float],
    aggregate: Literal["mean", "max"] = "mean",
) -> float:
    """Resnik best match from the person's side: for each of the person's terms, the IC of the
    most informative ancestor it shares with any of the gene's terms; then the mean over the
    person's terms (best match average, as Phenomizer does), or the single best. The best
    shared ancestor over all the gene's terms is the best one in the union of their ancestors,
    so that union is built once."""
    if not person:
        return 0.0
    above = set().union(*(ont.ancestors(t) for t in gene))
    best = [max((ic.get(a, 0.0) for a in ont.ancestors(t) & above), default=0.0) for t in person]
    return sum(best) / len(best) if aggregate == "mean" else max(best)


def normalize(name: str) -> str:
    name = re.sub(r"\(.*?\)", " ", name.lower())
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", name)).strip()


def map_conditions(
    concepts: dict[int, str],
    ancestors: dict[int, list[int]],
    ont: Ontology,
    manual: dict[int, str],
) -> dict[int, dict]:
    """OMOP condition concepts to HPO terms. In order: the hand-written table; an HPO term whose
    name or exact synonym equals the concept's name; the term of the nearest ancestor concept
    mapped either way (ancestors listed nearest first). Unmapped concepts are left out."""
    by_name: dict[str, set[str]] = defaultdict(set)
    for term, name in ont.names.items():
        if term not in ont.obsolete:
            for n in [name, *ont.synonyms.get(term, [])]:
                by_name[normalize(n)].add(term)
    direct: dict[int, dict] = {}
    for cid, name in concepts.items():
        if cid in manual:
            direct[cid] = {"hpo": manual[cid], "method": "table"}
        elif len(hits := by_name.get(normalize(name), set())) == 1:
            direct[cid] = {"hpo": next(iter(hits)), "method": "name"}
    out = dict(direct)
    for cid in concepts:
        if cid not in out:
            nearest = next((a for a in ancestors.get(cid, []) if a in direct), None)
            if nearest is not None:
                out[cid] = {"hpo": direct[nearest]["hpo"], "method": "ancestor", "via": nearest}
    return out


def load_manual(ont: Ontology, path: Path = CONDITIONS) -> dict[int, str]:
    """The hand-written table, checked against the release: every term must exist and not be
    obsolete, and its name must be the one written next to it."""
    table = yaml.safe_load(path.read_text())
    out = {}
    for cid, entry in table["concepts"].items():
        term = ont.current(entry["hpo"])
        if term is None or ont.names[term] != entry["hpo_name"]:
            raise ValueError(f"{cid}: {entry['hpo']} is not '{entry['hpo_name']}' in {ont.release}")
        out[int(cid)] = term
    return out
