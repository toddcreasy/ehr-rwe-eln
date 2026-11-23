"""The ClinGen Evidence Repository: expert panel curations with every criterion they applied.

ClinVar shows an expert panel's classification; the Evidence Repository (ERepo) also shows how
the panel got there, criterion by criterion, as "Met" and "Not Met" codes with their strength
(PVS1, PM2_Supporting, BS3, and so on), and the papers cited. That makes it the reference for
scoring rules one criterion at a time, not only by the final class. ClinGen releases it as one
tab-separated export, CC0 1.0.
"""

import csv
from collections import Counter
from pathlib import Path

from ehr_rwe_eln.curation.rules import DEFAULT

URL = "https://erepo.clinicalgenome.org/evrepo/api/classifications/all?format=tabbed"
# The criteria the rules can apply, and so the ones scored.
SCORED = ["BA1", "BS1", "PM2", "PVS1", "PM5", "PS3", "BS3"]
SUFFIX = {
    "Supporting": "supporting",
    "Moderate": "moderate",
    "Strong": "strong",
    "VeryStrong": "very_strong",
    "Very Strong": "very_strong",
    "Stand Alone": "stand_alone",
}


def parse_code(label: str) -> tuple[str, str | None]:
    """'PM2_Supporting' -> ('PM2', 'supporting'); 'PVS1' -> ('PVS1', 'very_strong')."""
    code, _, suffix = label.strip().partition("_")
    return code, SUFFIX.get(suffix) if suffix else DEFAULT.get(code)


def read_erepo(path: Path, genes: set[str]) -> dict[int, dict]:
    """Curations in genes, by ClinVar variation id; retracted ones are left out."""
    out = {}
    with path.open(newline="") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            if row["HGNC Gene Symbol"] not in genes or row["Retracted"] == "true":
                continue
            if not row["ClinVar Variation Id"].isdigit():
                continue
            split = lambda s: [c.strip() for c in s.split(",") if c.strip()]  # noqa: E731
            out[int(row["ClinVar Variation Id"])] = {
                "gene": row["HGNC Gene Symbol"],
                "assertion": row["Assertion"],
                "met": split(row["Applied Evidence Codes (Met)"]),
                "not_met": split(row["Applied Evidence Codes (Not Met)"]),
                "pmids": split(row["PubMed Articles"]),
                "guideline": row["Guideline"],
            }
    return out


def score_criteria(assessments: list[dict], codes: list[str] = SCORED) -> dict:
    """Per criterion, against the panel's codes (in each assessment's evidence["expert"]):
    agreed (both met), extra (the rules met it, the panel did not: split by whether the panel
    marked it not met or did not list it), missed (the panel met it, the rules did not), and
    among agreed, how often the strength matches too. codes: which criteria to score."""
    counts = {code: Counter() for code in codes}
    for a in assessments:
        expert = a["evidence"].get("expert")
        if not expert:
            continue
        theirs = dict(parse_code(c) for c in expert["met"])
        not_met = {parse_code(c)[0] for c in expert["not_met"]}
        ours = {c["code"]: c["strength"] for c in a["met"]}
        for code in codes:
            c = counts[code]
            if code in ours and code in theirs:
                c["agreed"] += 1
                c["same_strength"] += ours[code] == theirs[code]
            elif code in ours:
                c["extra_marked_not_met" if code in not_met else "extra_not_listed"] += 1
            elif code in theirs:
                c["missed"] += 1
    out = {}
    for code, c in counts.items():
        extra = c["extra_marked_not_met"] + c["extra_not_listed"]
        out[code] = dict(c) | {
            "precision": c["agreed"] / (c["agreed"] + extra) if c["agreed"] + extra else None,
            "recall": c["agreed"] / (c["agreed"] + c["missed"])
            if c["agreed"] + c["missed"]
            else None,
        }
    return out
