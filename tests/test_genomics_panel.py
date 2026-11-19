import gzip
import json

import numpy as np
import pandas as pd
import pytest

from ehr_rwe_eln.genomics.clinvar import read_clinvar
from ehr_rwe_eln.genomics.gnomad import frequencies
from ehr_rwe_eln.genomics.panel import (
    PanelSpec,
    candidates,
    finalize,
    genotype_panel,
    panel_truth,
    read_panel_carriers,
    write_panel,
)

GENES = {"BRCA1": ("17", 43_000_000), "LDLR": ("19", 11_000_000)}
EXPERT = "reviewed_by_expert_panel"
AGREE = "criteria_provided,_multiple_submitters,_no_conflicts"
SINGLE = "criteria_provided,_single_submitter"


def record(chrom, pos, vid, ref, alt, gene, sig, review, mc="SO:0001587|nonsense", af=None):
    info = [f"GENEINFO={gene}:1", f"CLNSIG={sig}", f"CLNREVSTAT={review}", f"MC={mc}"]
    if af is not None:
        info.append(f"AF_EXAC={af}")
    return "\t".join([chrom, str(pos), str(vid), ref, alt, ".", ".", ";".join(info)])


@pytest.fixture
def clinvar_vcf(tmp_path):
    lines, vid = ["##fileformat=VCFv4.1", "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO"], 0
    for gene, (chrom, base) in GENES.items():
        rows = (
            [("Pathogenic", EXPERT, None)] * 4
            + [("Pathogenic", SINGLE, None)]  # one star: not trusted
            + [("Uncertain_significance", AGREE, None)] * 3
            + [("Benign", EXPERT, 0.2)] * 6
            + [("Benign", EXPERT, 0.001)]  # too rare to plant as common
        )
        for sig, review, af in rows:
            vid += 1
            lines.append(record(chrom, base + vid * 10, vid, "C", "T", gene, sig, review, af=af))
        vid += 1  # a structural-size insertion, too long for a short-variant panel
        lines.append(
            record(chrom, base + vid * 10, vid, "G", "G" + "A" * 60, gene, "Pathogenic", EXPERT)
        )
    # Overlapping a gene off the panel: still a BRCA1 variant. Two panel genes: ambiguous, dropped.
    lines.append(record("17", 43_100_000, 900, "A", "G", "BRCA1:1|NBR2", "Pathogenic", EXPERT))
    lines.append(record("17", 43_100_005, 902, "A", "G", "BRCA1:1|LDLR", "Pathogenic", EXPERT))
    lines.append("17\t43100010\t901\tA\tG\t.\t.\tGENEINFO=BRCA1:1")  # no classification
    path = tmp_path / "clinvar_20260101.vcf.gz"
    with gzip.open(path, "wt") as f:
        f.write("\n".join(lines) + "\n")
    return path


def spec(**fields) -> PanelSpec:
    base = {
        "clinvar_release": "20260101",
        "gnomad_dataset": "gnomad_r4",
        "seed": 0,
        "pathogenic_per_gene": 2,
        "benign_per_gene": 2,
        "uncertain_per_gene": 1,
        "min_stars": 2,
        "benign_min_frequency": 0.01,
        "uncertain_carriers": 0.01,
        "conditions": [
            {
                "name": "breast_cancer",
                "concept_id": 4112853,
                "genes": ["BRCA1"],
                "carriers_with": 0.5,
                "carriers_without": 0.01,
            },
            {
                "name": "hyperlipidemia",
                "concept_id": 432867,
                "genes": ["LDLR"],
                "carriers_with": 0.3,
                "carriers_without": 0.02,
            },
        ],
    }
    return PanelSpec.model_validate(base | fields)


def fake_gnomad(rare=()):
    """A stand-in for the gnomAD API: benign candidates common, the rest absent, except the
    ids in rare, which gnomAD reports at 0.001."""
    calls = []

    def post(query, variables):
        calls.append(variables)
        data = {}
        for name, variant_id in variables.items():
            if variant_id in rare:
                data[name] = {"exome": {"ac": 1, "an": 1000}, "genome": None}
            elif variant_id.endswith("-C-T"):
                data[name] = {"exome": {"ac": 150, "an": 1000}, "genome": {"ac": 50, "an": 1000}}
            else:
                data[name] = None
        errors = [{"message": "Variant not found"}] if None in data.values() else []
        return {"data": data, "errors": errors}

    return post, calls


def test_read_clinvar_keeps_classified_single_gene_records(clinvar_vcf):
    table = read_clinvar(clinvar_vcf, set(GENES))
    assert len(table) == 2 * 16 + 1  # plus BRCA1|NBR2; BRCA1|LDLR and the unclassified dropped
    assert 900 in table["variation_id"].to_list() and 902 not in table["variation_id"].to_list()
    assert set(table["chromosome"]) == {"chr17", "chr19"}
    stars = dict(zip(table["review_status"], table["stars"], strict=False))
    assert stars == {EXPERT: 3, AGREE: 2, SINGLE: 1}
    assert set(table["consequence"]) == {"nonsense"}


def test_gnomad_batches_caches_and_records_absent_variants(tmp_path):
    post, calls = fake_gnomad()
    ids = [f"17-{p}-C-T" for p in range(23)] + ["17-99-G-A"]
    cache = tmp_path / "gnomad.json"
    found = frequencies(ids, cache, post=post, wait=0)
    assert len(calls) == 3  # 24 variants, 10 per request
    assert found["17-0-C-T"] == {"ac": 200, "an": 2000, "af": 0.1}
    assert found["17-99-G-A"] is None  # absent from gnomAD, and cached as such
    assert frequencies(ids, cache, post=post, wait=0) == found
    assert len(calls) == 3  # the second call is answered from the cache


def test_gnomad_errors_other_than_not_found_are_never_cached(tmp_path, monkeypatch):
    import ehr_rwe_eln.genomics.gnomad as gnomad

    monkeypatch.setattr(gnomad.time, "sleep", lambda s: None)  # retried, then raised

    def limited(query, variables):
        return {"data": None, "errors": [{"message": "Rate limit exceeded"}]}

    cache = tmp_path / "gnomad.json"
    with pytest.raises(RuntimeError, match="Rate limit"):
        frequencies(["17-1-C-T"], cache, post=limited, wait=0)
    assert not cache.exists()

    def broken(query, variables):  # not transient: raised at once
        return {"data": None, "errors": [{"message": "Cannot query field"}]}

    calls = []
    with pytest.raises(RuntimeError, match="Cannot query field"):
        frequencies(["17-1-C-T"], cache, post=lambda q, v: calls.append(1) or broken(q, v), wait=0)
    assert len(calls) == 1


def test_gnomad_retries_an_overloaded_service_and_caches_only_answers(tmp_path, monkeypatch):
    import ehr_rwe_eln.genomics.gnomad as gnomad

    monkeypatch.setattr(gnomad.time, "sleep", lambda s: None)
    answers = iter(
        [
            {"data": None, "errors": [{"message": "Service overloaded"}]},
            {"data": {"v0": {"exome": {"ac": 1, "an": 10}, "genome": None}}},
        ]
    )
    found = frequencies(["17-1-C-T"], tmp_path / "g.json", post=lambda q, v: next(answers), wait=0)
    assert found["17-1-C-T"]["ac"] == 1
    always_busy = lambda q, v: {"data": None, "errors": [{"message": "Service overloaded"}]}  # noqa: E731
    with pytest.raises(RuntimeError, match="overloaded"):
        frequencies(["17-2-C-T"], tmp_path / "g.json", post=always_busy, wait=0)
    assert "17-2-C-T" not in json.loads((tmp_path / "g.json").read_text())


def chosen_variants(clinvar_vcf, tmp_path, s):
    clinvar = read_clinvar(clinvar_vcf, set(GENES))
    picked = candidates(clinvar, s, np.random.default_rng(s.seed))
    benign = picked.filter(picked["role"] == "benign")["gnomad_id"].to_list()
    post, _ = fake_gnomad(rare=set(benign[:1]))  # gnomAD says the first is rare after all
    found = frequencies(picked["gnomad_id"].to_list(), tmp_path / "g.json", post=post, wait=0)
    return finalize(picked, found, s), benign[0]


def test_panel_plants_trusted_short_variants(clinvar_vcf, tmp_path):
    s = spec()
    variants, rare = chosen_variants(clinvar_vcf, tmp_path, s)
    counts = variants.group_by("gene", "role").len().sort("gene", "role").rows()
    assert counts == [
        ("BRCA1", "benign", 2),
        ("BRCA1", "pathogenic", 2),
        ("BRCA1", "uncertain", 1),
        ("LDLR", "benign", 2),
        ("LDLR", "pathogenic", 2),
        ("LDLR", "uncertain", 1),
    ]
    assert variants["stars"].min() >= 2
    assert variants["alt"].str.len_chars().max() < 50
    assert rare not in variants["gnomad_id"].to_list()  # gnomAD, not ClinVar, decides common
    assert variants["position"].is_sorted() or variants["chromosome"].n_unique() > 1
    again, _ = chosen_variants(clinvar_vcf, tmp_path / "again", s)
    assert again["gnomad_id"].to_list() == variants["gnomad_id"].to_list()


def test_too_few_pathogenic_variants_is_an_error(clinvar_vcf):
    clinvar = read_clinvar(clinvar_vcf, set(GENES))
    with pytest.raises(ValueError, match="pathogenic variants qualify"):
        candidates(clinvar, spec(pathogenic_per_gene=5), np.random.default_rng(0))


def test_carriers_follow_the_condition_and_frequencies_follow_gnomad(clinvar_vcf, tmp_path):
    s = spec()
    variants, _ = chosen_variants(clinvar_vcf, tmp_path, s)
    rng = np.random.default_rng(1)
    n = 20_000
    flags = pd.DataFrame(
        {"breast_cancer": (rng.random(n) < 0.3).astype(int), "hyperlipidemia": rng.random(n) < 0.3}
    ).astype(int)
    dosage = genotype_panel(flags, variants, s, np.random.default_rng(2))
    roles, genes = variants["role"].to_numpy(), variants["gene"].to_numpy()
    for condition in s.conditions:
        has = flags[condition.name].to_numpy() == 1
        carrier = dosage[(roles == "pathogenic") & np.isin(genes, condition.genes)].sum(0) > 0
        for rate, group in ((condition.carriers_with, has), (condition.carriers_without, ~has)):
            se = np.sqrt(rate * (1 - rate) / group.sum())
            assert abs(carrier[group].mean() - rate) < 4 * se
    assert dosage[roles == "pathogenic"].max() == 1  # heterozygous only
    benign = roles == "benign"
    assert np.allclose(
        dosage[benign].mean(1) / 2, variants["gnomad_af"].to_numpy()[benign], atol=0.01
    )
    uncertain = dosage[roles == "uncertain"].mean(1)
    assert np.allclose(uncertain, s.uncertain_carriers, atol=0.003)


def test_vcf_has_real_coordinates_and_the_truth_has_the_answers(clinvar_vcf, tmp_path):
    s = spec()
    variants, _ = chosen_variants(clinvar_vcf, tmp_path, s)
    flags = pd.DataFrame({"breast_cancer": [1, 0, 1, 0] * 50, "hyperlipidemia": [0, 1] * 100})
    dosage = genotype_panel(flags, variants, s, np.random.default_rng(3))
    subjects = [f"SUBJ-{i:05d}" for i in range(1, 201)]
    samples = [f"SAMP-{i:05d}" for i in range(1, 201)]
    truth = panel_truth(variants, dosage, subjects, flags, s)
    write_panel(tmp_path, variants, dosage, samples, truth)

    with gzip.open(tmp_path / "panel.vcf.gz", "rt") as f:
        lines = f.read().splitlines()
    assert "##reference=GRCh38" in lines
    assert "##contig=<ID=chr17,length=83257441,assembly=GRCh38>" in lines
    body = [line.split("\t") for line in lines if not line.startswith("#")]
    assert [(r[0], int(r[1])) for r in body] == list(
        zip(variants["chromosome"], variants["position"], strict=True)
    )
    assert {r[7] for r in body} == {"."}  # no classification in the VCF
    assert not any("Pathogenic" in line or "Benign" in line for line in lines)
    carriers_of = read_panel_carriers(tmp_path / "panel.vcf.gz")
    assert list(carriers_of) == [r[2] for r in body]
    for v, variant_id in enumerate(carriers_of):
        assert carriers_of[variant_id] == [samples[i] for i in np.flatnonzero(dosage[v])]

    saved = json.loads((tmp_path / "panel_truth.json").read_text())
    assert saved == json.loads(json.dumps(truth))
    for v, entry in enumerate(saved["variants"]):
        carriers = [subjects[i] for i in np.flatnonzero(dosage[v])]
        assert entry["carriers"] == len(carriers)
        if entry["role"] != "benign":
            assert entry["carrier_subjects"] == carriers
    breast = saved["conditions"]["breast_cancer"]
    assert breast["people_with"] == 100
    assert breast["carriers_with"] + breast["carriers_without"] > 0
