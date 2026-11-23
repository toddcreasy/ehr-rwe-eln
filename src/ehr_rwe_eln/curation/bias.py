"""BIAS-2015 as a baseline: an open automated ACMG classifier, on the Evidence Repository set.

BIAS-2015 (Bitscopic, https://github.com/bitscopic/BIAS-2015, AGPL for non-commercial academic
use; Eisenhart et al., Genome Med 2025) applies 19 of the 28 ACMG/AMP codes from an annotated
VCF. It runs on AWS (scripts/run_bias.py) on Ensembl VEP 115 annotations; this module writes its
input, reads its output, and puts it in the shape our assessments have, so the same scoring
(curate.score, erepo.score_criteria) applies to both.

Eight of its codes read ClinVar, and the expert panel classes it is scored against are in
ClinVar, so it runs three times: with every code, without the codes that read the variant's own
ClinVar record or near neighbours (per variant), and without those and the gene and domain
tables built from all of ClinVar (no ClinVar).
"""

import csv
import io
import json

PER_VARIANT = ["PP5", "BP6", "PS1", "PM5", "PS4"]
SKIPS = {
    "all_codes": [],
    "no_clinvar_per_variant": PER_VARIANT,
    "no_clinvar": [*PER_VARIANT, "PM1", "PP2", "BP1"],
}
CLASS = {
    "pathogenic": "Pathogenic",
    "likely pathogenic": "Likely pathogenic",
    "uncertain": "Uncertain significance",
    "likely benign": "Likely benign",
    "benign": "Benign",
}
# The value BIAS gives each code is its strength (constants.score_to_hum_readable); 0 is not met.
LEVEL = {1: "supporting", 2: "moderate", 3: "strong", 4: "very_strong", 5: "stand_alone"}


def vcf(variant_ids: list[str]) -> str:
    """A sites-only VCF of chrN:pos:ref:alt IDs, in position order, each ID in the ID column."""
    lines = ["##fileformat=VCFv4.2", "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO"]

    def order(v: str) -> tuple:
        chromosome, position, _, _ = v.split(":")
        name = chromosome.removeprefix("chr")
        return (int(name) if name.isdigit() else 100 + ord(name[0]), int(position))

    for v in sorted(variant_ids, key=order):
        chromosome, position, ref, alt = v.split(":")
        lines.append("\t".join([chromosome, position, v, ref, alt, ".", ".", "."]))
    return "\n".join(lines) + "\n"


def vep_key(variant_id: str) -> tuple[str, int, str, str]:
    """How VEP, and so BIAS, names a VCF variant: an indel loses the base it shares with the
    other allele, and an empty allele is '-'. chr5:100:AATAG:A -> ('chr5', 101, 'ATAG', '-')."""
    chromosome, position, ref, alt = variant_id.split(":")
    pos = int(position)
    if len(ref) != len(alt) and ref[0] == alt[0]:
        ref, alt, pos = ref[1:] or "-", alt[1:] or "-", pos + 1
    return chromosome, pos, ref, alt


def read_output(text: str) -> dict[tuple[str, int, str, str], dict]:
    """BIAS's TSV by VEP key: the class in our names and the codes met, each with its strength
    and BIAS's label for it (e.g. 'PS4_supporting')."""
    out = {}
    for row in csv.DictReader(io.StringIO(text), delimiter="\t"):
        met = []
        for codes in json.loads(row["rationale"]).values():
            for code, (value, reason) in codes.items():
                if value:
                    label = reason.split(":", 1)[0].strip() or code.upper()
                    met.append({"code": code.upper(), "strength": LEVEL[value], "label": label})
        key = (row["chromosome"], int(row["position"]), row["refAllele"], row["altAllele"])
        out[key] = {"classification": CLASS[row["acmgClassification"]], "met": met}
    return out


def as_assessments(ours: list[dict], bias: dict[tuple, dict]) -> tuple[list[dict], list[str]]:
    """BIAS's results for our assessments' variants, shaped like them (gene, expected, the
    panel's codes kept), and the variant IDs BIAS returned nothing for."""
    out, missing = [], []
    for a in ours:
        found = bias.get(vep_key(a["variant_id"]))
        if found is None:
            missing.append(a["variant_id"])
            continue
        out.append(
            {
                "variant_id": a["variant_id"],
                "gene": a["gene"],
                "expected": a["expected"],
                "evidence": {"expert": a["evidence"].get("expert")},
                **found,
            }
        )
    return out, missing
