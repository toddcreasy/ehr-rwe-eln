"""Add a clinical sequencing panel to the genomics study: real ClinVar variants at their real
GRCh38 positions, planted in the study's synthetic subjects (src/ehr_rwe_eln/genomics/panel.py).

Usage: uv run python scripts/generate_panel.py   (after scripts/generate_genomics.py)

Downloads the ClinVar release named in panel.yaml to data/reference/clinvar/ if it is not
there, and checks it against NCBI's md5. Looks up gnomAD frequencies for the candidate
variants through gnomAD's public API, cached in data/reference/gnomad/, so a rerun makes no
requests. Writes data/genomics/panel.vcf.gz and panel_truth.json. The same spec and study
always give the same files.

ClinVar is NCBI data with no restrictions on use; gnomAD's data are CC0. This tool includes
data from the gnomAD v4 release (https://gnomad.broadinstitute.org).
"""

import hashlib
import time
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

from ehr_rwe_eln.cohort.lake import connect_omop
from ehr_rwe_eln.genomics.clinvar import URL, read_clinvar
from ehr_rwe_eln.genomics.gnomad import frequencies
from ehr_rwe_eln.genomics.panel import (
    candidates,
    finalize,
    genotype_panel,
    load_panel_spec,
    panel_truth,
    write_panel,
)
from ehr_rwe_eln.tte.cohort import ids

DATA = Path(__file__).resolve().parent.parent / "data"
STUDY = DATA / "genomics"
REGISTRY = DATA / "registry" / "genomics_subjects.tsv"
REFERENCE = DATA / "reference"

FLAGS_SQL = """
SELECT DISTINCT co.person_id
FROM {cdm}.condition_occurrence co
JOIN {cdm}.concept_ancestor ca ON ca.descendant_concept_id = co.condition_concept_id
WHERE ca.ancestor_concept_id = {concept} AND co.person_id IN ({people})
"""


def fetch_clinvar(release: str) -> Path:
    path = REFERENCE / "clinvar" / f"clinvar_{release}.vcf.gz"
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    url = URL.format(release=release)
    print(f"downloading {url}")
    urllib.request.urlretrieve(url, path)  # noqa: S310  (fixed https URL)
    with urllib.request.urlopen(url + ".md5") as response:  # noqa: S310  (fixed https URL)
        expected = response.read().decode().split()[0]
    digest = hashlib.md5(path.read_bytes(), usedforsecurity=False).hexdigest()
    if digest != expected:
        path.unlink()
        raise SystemExit(f"{path.name}: md5 {digest} does not match NCBI's {expected}")
    return path


def main() -> None:
    spec = load_panel_spec()
    start = time.time()
    clinvar = read_clinvar(fetch_clinvar(spec.clinvar_release), spec.genes)
    rng = np.random.default_rng(spec.seed)
    chosen = candidates(clinvar, spec, rng)
    cache = REFERENCE / "gnomad" / f"{spec.gnomad_dataset}.json"
    variants = finalize(
        chosen, frequencies(chosen["gnomad_id"].to_list(), cache, spec.gnomad_dataset), spec
    )

    mapping = pd.read_csv(STUDY / "subject_sample_mapping.tsv", sep="\t")
    registry = pd.read_csv(REGISTRY, sep="\t").set_index("subject_id")["person_id"]
    person_ids = registry.loc[mapping["subject_id"]].to_numpy()
    flags = pd.DataFrame(index=mapping["subject_id"])
    omop, cdm = connect_omop()
    with omop:
        for condition in spec.conditions:
            query = FLAGS_SQL.format(
                cdm=cdm, concept=int(condition.concept_id), people=ids(person_ids.tolist())
            )
            found = {r[0] for r in omop.execute(query).fetchall()}
            flags[condition.name] = [int(p in found) for p in person_ids]

    dosage = genotype_panel(flags, variants, spec, rng)
    truth = panel_truth(variants, dosage, mapping["subject_id"].tolist(), flags, spec)
    write_panel(STUDY, variants, dosage, mapping["sample_id"].tolist(), truth)

    print(
        f"{len(variants)} variants in {len(spec.genes)} genes for {len(mapping):,} subjects"
        f" in {time.time() - start:.0f}s (ClinVar {spec.clinvar_release}, {spec.gnomad_dataset})"
    )
    for name, c in truth["conditions"].items():
        print(
            f"  {name}: {c['people_with']} people with it; pathogenic carriers"
            f" {c['carriers_with']} with, {c['carriers_without']} without"
        )
    for role in ("pathogenic", "benign", "uncertain"):
        rows = [v for v in truth["variants"] if v["role"] == role]
        print(f"  {role}: {len(rows)} variants, {sum(v['carriers'] for v in rows)} carriers")
    print(f"written to {STUDY / 'panel.vcf.gz'} and panel_truth.json")


if __name__ == "__main__":
    main()
