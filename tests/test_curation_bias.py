import json

from ehr_rwe_eln.curation.bias import SKIPS, as_assessments, read_output, vcf, vep_key
from ehr_rwe_eln.curation.curate import score
from ehr_rwe_eln.curation.erepo import score_criteria

HEADER = [
    "chromosome", "position", "refAllele", "altAllele", "variantType", "consequence",
    "acmgClassification", "alleleFreq", "hgvsg", "hgvsc", "hgvsp", "aaChange", "geneName",
    "pubmedIds", "associatedDiseases", "dbSnpids", "transcript", "rationale",
]  # fmt: skip


def row(chromosome, position, ref, alt, classification, rationale):
    cells = [chromosome, str(position), ref, alt, "SNV", "x", classification]
    return "\t".join(cells + [""] * 10 + [json.dumps(rationale)])


def test_skip_lists_grow_from_none_to_every_clinvar_code():
    assert SKIPS["all_codes"] == []
    assert set(SKIPS["no_clinvar_per_variant"]) == {"PP5", "BP6", "PS1", "PM5", "PS4"}
    assert set(SKIPS["no_clinvar"]) == set(SKIPS["no_clinvar_per_variant"]) | {"PM1", "PP2", "BP1"}


def test_vcf_in_chromosome_then_position_order_with_ids():
    text = vcf(["chrX:5:A:G", "chr17:20:C:T", "chr2:9:G:A", "chr17:3:T:C"])
    rows = [line.split("\t") for line in text.splitlines()[2:]]
    assert [r[2] for r in rows] == ["chr2:9:G:A", "chr17:3:T:C", "chr17:20:C:T", "chrX:5:A:G"]
    assert rows[0][:5] == ["chr2", "9", "chr2:9:G:A", "G", "A"]


def test_vep_key_drops_the_shared_base_of_an_indel_only():
    assert vep_key("chr5:100:AATAG:A") == ("chr5", 101, "ATAG", "-")
    assert vep_key("chr5:100:A:AT") == ("chr5", 101, "-", "T")
    assert vep_key("chr1:171605477:GTC:A") == ("chr1", 171605477, "GTC", "A")
    assert vep_key("chr2:9:G:A") == ("chr2", 9, "G", "A")


def test_output_gives_class_and_codes_met_with_strength_from_the_level():
    text = "\t".join(HEADER) + "\n"
    text += row(
        "chr5", 101, "ATAG", "-", "likely pathogenic",
        {
            "pvs": {"pvs1": [3, "PVS1_strong: Null variant"]},
            "ps": {"ps4": [1, "PS4_supporting: 2 ClinVar submitters"], "ps1": [0, ""]},
            "pm": {"pm2": [2, "PM2: absent from gnomAD"]},
        },
    ) + "\n"  # fmt: skip
    found = read_output(text)[("chr5", 101, "ATAG", "-")]
    assert found["classification"] == "Likely pathogenic"
    assert found["met"] == [
        {"code": "PVS1", "strength": "strong", "label": "PVS1_strong"},
        {"code": "PS4", "strength": "supporting", "label": "PS4_supporting"},
        {"code": "PM2", "strength": "moderate", "label": "PM2"},
    ]


def test_results_take_our_variants_genes_and_panel_codes_and_score_the_same_way():
    expert = {"met": ["PVS1", "PM2_Supporting"], "not_met": ["BA1"], "pmids": []}
    ours = [
        {"variant_id": "chr5:100:AATAG:A", "gene": "APC", "expected": "Pathogenic",
         "evidence": {"expert": expert}},
        {"variant_id": "chr5:200:G:A", "gene": "APC", "expected": "Benign",
         "evidence": {"expert": None}},
    ]  # fmt: skip
    bias = {
        ("chr5", 101, "ATAG", "-"): {
            "classification": "Likely pathogenic",
            "met": [{"code": "PVS1", "strength": "very_strong", "label": "PVS1"}],
        }
    }
    found, missing = as_assessments(ours, bias)
    assert missing == ["chr5:200:G:A"]
    assert found[0]["gene"] == "APC" and found[0]["evidence"]["expert"] == expert
    assert score(found)["agreement"] == 1.0
    criteria = score_criteria(found, ["PVS1", "PM2"])
    assert criteria["PVS1"]["agreed"] == 1 and criteria["PVS1"]["same_strength"] == 1
    assert criteria["PM2"]["missed"] == 1
