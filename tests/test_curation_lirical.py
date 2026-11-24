import io
import zipfile

import numpy as np

from ehr_rwe_eln.curation.lirical import (
    check_planted,
    gene_auc,
    rank,
    read_disease_genes,
    read_ranks,
    read_results,
)

DISEASE_GENES = {"OMIM:143890": {"LDLR"}, "OMIM:604370": {"BRCA1"}, "OMIM:612555": {"BRCA2"}}
TSV = """! LIRICAL TSV Output (2.4.2)
! Sample: subject
rank\tdiseaseName\tdiseaseCurie\tpretestprob\tposttestprob\tcompositeLR
1\tSomething else\tOMIM:256040\t1/8525\t94.57%\t5.172
2\tHypercholesterolemia, familial, 1\tOMIM:143890\t1/8525\t0.04%\t0.563
3\tBreast-ovarian cancer, familial, 1\tOMIM:604370\t1/8525\t0.00%\t-3.12
8,525\tBreast-ovarian cancer, familial, 2\tOMIM:612555\t1/8525\t0.00%\t-∞
"""


def test_read_disease_genes_keeps_omim_and_the_genes_asked(tmp_path):
    path = tmp_path / "genes_to_phenotype.txt"
    path.write_text(
        "ncbi_gene_id\tgene_symbol\thpo_id\thpo_name\tfrequency\tdisease_id\n"
        "3949\tLDLR\tHP:0003124\tHypercholesterolemia\t-\tOMIM:143890\n"
        "3949\tLDLR\tHP:0001677\tCoronary artery disease\t-\tOMIM:143890\n"
        "3949\tLDLR\tHP:0003124\tHypercholesterolemia\t-\tORPHA:406\n"
        "10\tNAT2\tHP:0000007\tAutosomal recessive inheritance\t-\tOMIM:243400\n"
    )
    assert read_disease_genes(path, {"LDLR", "BRCA1"}) == {"OMIM:143890": {"LDLR"}}


def test_read_ranks_takes_each_genes_disease_and_reads_commas():
    assert read_ranks(TSV, DISEASE_GENES) == {"LDLR": 2, "BRCA1": 3, "BRCA2": 8525}


def test_read_ranks_keeps_a_genes_best_disease():
    two = {"OMIM:256040": {"LDLR"}, "OMIM:143890": {"LDLR"}}
    assert read_ranks(TSV, two) == {"LDLR": 1}


def test_read_results_by_sample():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        z.writestr("SAMP-00001.tsv", TSV)
        z.writestr("lirical.log", "not a result")
    with zipfile.ZipFile(buffer) as z:
        assert read_results(z, DISEASE_GENES) == {
            "SAMP-00001": {"LDLR": 2, "BRCA1": 3, "BRCA2": 8525}
        }


def test_rank_is_among_the_persons_genes_with_ties_sharing():
    ranks = {"LDLR": 9, "BRCA1": 4, "BRCA2": 9}
    assert rank(ranks, "BRCA1", {"LDLR", "BRCA1", "BRCA2"}) == 1
    assert rank(ranks, "LDLR", {"LDLR", "BRCA1", "BRCA2"}) == 2
    assert rank(ranks, "BRCA2", {"LDLR", "BRCA2"}) == 1
    assert rank(ranks, "APC", {"APC", "LDLR"}) is None
    assert rank(ranks, "LDLR", {"APC", "LDLR"}) == 1


def test_check_planted_counts_first_and_chance():
    results = {"S1": {"LDLR": 1, "BRCA1": 2}, "S2": {"LDLR": 1, "BRCA1": 2}}
    planted = {"S1": {"LDLR"}, "S2": {"BRCA1"}}
    genes_of = {"S1": {"LDLR", "BRCA1"}, "S2": {"LDLR", "BRCA1"}}
    assert check_planted(results, planted, genes_of) == {
        "carriers": 2,
        "first": 1,
        "not_scored": 0,
        "random": 1.0,
    }


def test_gene_auc_is_among_people_with_a_variant_in_the_gene():
    results = {f"S{i}": {"LDLR": 10 - i} for i in range(6)}
    genes_of = {f"S{i}": {"LDLR"} for i in range(5)} | {"S5": {"BRCA1"}}
    planted = {"S3": {"LDLR"}, "S4": {"LDLR"}}
    out = gene_auc(results, planted, genes_of, np.random.default_rng(0), n=50)
    assert out["LDLR"]["people"] == 5 and out["LDLR"]["carriers"] == 2
    assert out["LDLR"]["auc"] == 1.0
    assert "BRCA1" not in out
