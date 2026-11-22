import io
import zipfile

import numpy as np
import yaml

from ehr_rwe_eln.curation.exomiser import (
    ANALYSIS,
    check_planted,
    phenotype_auc,
    rank,
    read_gene_results,
    vcf,
    write_inputs,
)

PEOPLE = [
    {"sample_id": "S1", "sex": "female", "hpo_release": "2026-09-01", "hpo_ids": ["HP:0003002"]},
    {"sample_id": "S2", "sex": "male", "hpo_release": "2026-09-01", "hpo_ids": []},
    {"sample_id": "S3", "sex": "male", "hpo_release": "2026-09-01", "hpo_ids": ["HP:0003124"]},
]
GENOTYPES = [
    ("chr17:43091012:C:T", "S1", "0/1"),
    ("chr13:32319077:G:A", "S1", "1/1"),
    ("chr19:11102657:G:A", "S2", "0/1"),
]


def test_analysis_leaves_out_spliceai_cadd_and_remm():
    assert not {"SPLICE_AI", "CADD", "REMM"} & set(ANALYSIS["pathogenicitySources"])
    assert ANALYSIS["analysisMode"] == "FULL"


def test_vcf_is_single_sample_in_position_order():
    text = vcf("S1", [("chr17:43091012:C:T", "0/1"), ("chr13:32319077:G:A", "1/1")])
    rows = [line.split("\t") for line in text.splitlines() if not line.startswith("##")]
    assert rows[0][-1] == "S1"
    assert [r[0] for r in rows[1:]] == ["chr13", "chr17"]
    assert rows[1][3:5] == ["G", "A"] and rows[1][9] == "1/1"


def test_inputs_one_sample_file_vcf_and_batch_line_per_person_with_calls():
    data, counts = write_inputs(PEOPLE, GENOTYPES, "2609")
    assert counts == {"people": 2, "no_calls": 1, "no_hpo_terms": 1}
    z = zipfile.ZipFile(io.BytesIO(data))
    names = set(z.namelist())
    assert {"samples/S1.yml", "vcf/S1.vcf", "samples/S2.yml", "vcf/S2.vcf"} <= names
    assert "samples/S3.yml" not in names
    packet = yaml.safe_load(z.read("samples/S1.yml"))
    assert packet["subject"] == {"id": "S1", "sex": "FEMALE"}
    assert packet["phenotypicFeatures"] == [{"type": {"id": "HP:0003002"}}]
    batch = z.read("batch.txt").decode().splitlines()
    assert len(batch) == 2 and "--output-filename S1 " in batch[0] and "--assembly hg38" in batch[0]


def genes_tsv(rows):
    header = "#RANK\tID\tGENE_SYMBOL\tENTREZ_GENE_ID\tMOI\tP-VALUE\tEXOMISER_GENE_COMBINED_SCORE"
    header += "\tEXOMISER_GENE_PHENO_SCORE\tEXOMISER_GENE_VARIANT_SCORE"
    body = [f"{i}\tx\t{g}\t1\t{m}\t0.1\t{c}\t{p}\t{v}" for i, (g, m, c, p, v) in enumerate(rows)]
    return "\n".join([header, *body]) + "\n"


def test_results_keep_each_genes_best_mode_and_rank_by_each_score():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        z.writestr(
            "S1.genes.tsv",
            genes_tsv(
                [
                    ("BRCA2", "AD", 0.9, 0.3, 0.95),
                    ("BRCA1", "AD", 0.6, 0.7, 0.5),
                    ("BRCA1", "AR", 0.2, 0.7, 0.1),
                ]
            ),
        )
        z.writestr("S1.variants.tsv", "ignored\n")
    results = read_gene_results(zipfile.ZipFile(buffer))
    assert results["S1"]["BRCA1"] == {"combined": 0.6, "phenotype": 0.7, "variant": 0.5}
    genes = results["S1"]
    assert rank(genes, "BRCA1", "combined") == 2
    assert rank(genes, "BRCA1", "phenotype") == 1
    assert rank(genes, "LDLR", "combined") is None
    check = check_planted(results, {"S1": {"BRCA1"}, "S9": {"LDLR"}})
    assert check["combined"] == {"carriers": 2, "first": 0, "not_scored": 1}
    assert check["phenotype"] == {"carriers": 2, "first": 1, "not_scored": 1}
    # A person with two planted genes counts once, as first if either one comes first.
    both = check_planted(results, {"S1": {"BRCA1", "BRCA2"}})
    assert both["combined"] == {"carriers": 1, "first": 1, "not_scored": 0}


def test_phenotype_auc_compares_both_scores_on_the_people_exomiser_scored():
    scored = {"combined": 0.0, "variant": 0.0}
    results = {
        "S1": {"LDLR": {**scored, "phenotype": 0.9}},
        "S2": {"LDLR": {**scored, "phenotype": 0.2}},
        "S3": {"LDLR": {**scored, "phenotype": 0.4}, "APC": {**scored, "phenotype": 0.5}},
        "S4": {"APC": {**scored, "phenotype": 0.5}},
    }
    resnik = {
        "S1": {"LDLR": -1.0},
        "S2": {"LDLR": 2.0},
        "S3": {"LDLR": 0.0, "APC": 0.0},
        "S4": {"APC": 0.0},
    }
    out = phenotype_auc(results, {"S1": {"LDLR"}}, resnik, np.random.default_rng(0), n=50)
    # APC has no pathogenic carrier among the people scored for it, so no AUC.
    assert set(out) == {"LDLR"}
    assert out["LDLR"]["people"] == 3 and out["LDLR"]["carriers"] == 1
    assert out["LDLR"]["exomiser"]["auc"] == 1.0
    assert out["LDLR"]["resnik"]["auc"] == 0.0
