"""ClinVar records for a set of genes, read from NCBI's dated GRCh38 VCF.

ClinVar is NCBI's public archive of what labs and expert panels have concluded about human
variants. Each record has an aggregate classification (CLNSIG: pathogenic, benign, uncertain
significance, and so on) and a review status (CLNREVSTAT), which ClinVar shows as stars: one
for a single submitter with criteria, two for several submitters who agree, three for an expert
panel, four for a practice guideline. Only records whose position, reference, and alternate
allele are given precisely are in the VCF, which suits planting them in genotypes.

The release is fixed by its file name (clinvar_YYYYMMDD.vcf.gz), so the same release always
gives the same records.
"""

import gzip
from pathlib import Path

import polars as pl

URL = "https://ftp.ncbi.nlm.nih.gov/pub/clinvar/vcf_GRCh38/clinvar_{release}.vcf.gz"
STARS = {
    "practice_guideline": 4,
    "reviewed_by_expert_panel": 3,
    "criteria_provided,_multiple_submitters,_no_conflicts": 2,
    "criteria_provided,_conflicting_classifications": 1,
    "criteria_provided,_single_submitter": 1,
}


def read_clinvar(path: Path, genes: set[str]) -> pl.DataFrame:
    """One row per ClinVar record in exactly one of genes, with a classification."""
    rows = []
    with gzip.open(path, "rt") as f:
        for line in f:
            if line.startswith("#"):
                continue
            chrom, pos, variation_id, ref, alt, _, _, info = line.rstrip("\n").split("\t")[:8]
            fields = dict(kv.split("=", 1) for kv in info.split(";") if "=" in kv)
            symbols = {g.split(":")[0] for g in fields.get("GENEINFO", "").split("|")} & genes
            if len(symbols) != 1 or "CLNSIG" not in fields or alt == ".":
                continue
            review = fields.get("CLNREVSTAT", "")
            rows.append(
                {
                    "chromosome": "chr" + chrom,
                    "position": int(pos),
                    "ref": ref,
                    "alt": alt,
                    "variation_id": int(variation_id),
                    "gene": symbols.pop(),
                    "classification": fields["CLNSIG"],
                    "review_status": review,
                    "stars": STARS.get(review, 0),
                    # Sequence Ontology terms, such as nonsense or missense_variant.
                    "consequence": ",".join(
                        mc.split("|")[1] for mc in fields.get("MC", "").split(",") if "|" in mc
                    ),
                    "af_exac": float(fields.get("AF_EXAC", "nan")),
                    "af_tgp": float(fields.get("AF_TGP", "nan")),
                }
            )
    return pl.DataFrame(rows)
