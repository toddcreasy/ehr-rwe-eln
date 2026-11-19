"""The ACMG/AMP criteria that data alone can decide, with each gene's expert-panel thresholds,
combined into a classification on the Bayesian points scale.

ACMG/AMP (American College of Medical Genetics and Genomics, Association for Molecular
Pathology) criteria are pieces of evidence, each pathogenic (P) or benign (B) at a strength.
Here, from data:

- BA1 (stand-alone benign): too common in gnomAD to cause the disease.
- BS1 (benign): more common than the disease allows.
- PM2 (pathogenic): absent or extremely rare in gnomAD.
- PVS1 (pathogenic, very strong by default): a null variant (nonsense, frameshift, canonical
  splice site) in a gene where loss of function causes the disease, as all six here do.

Points (Tavtigian et al. 2020, Hum Mutat 41:1734): supporting 1, moderate 2, strong 4, very
strong 8; benign evidence counts against. 10 or more is pathogenic, 6 to 9 likely pathogenic,
0 to 5 uncertain significance, -1 to -6 likely benign, -7 or less benign. BA1 is benign on its
own.

What a rule cannot decide is listed as not assessed, with the reason, for the curator.
Nothing here reads the variant's ClinVar classification.
"""

import csv
import re
from functools import cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import Field

from ehr_rwe_eln.cohort.spec import Strict

RULES = Path(__file__).parent / "rules.yaml"
# ENIGMA's PVS1 decision table for BRCA1 and BRCA2 (scripts/import_enigma_pvs1.py).
ENIGMA = Path(__file__).parent / "enigma_pvs1.yaml"
# ENIGMA's calibrated functional assay results, PS3 and BS3 (scripts/import_enigma_functional.py).
FUNCTIONAL = Path(__file__).parent / "enigma_functional.tsv"
Strength = Literal["stand_alone", "very_strong", "strong", "moderate", "supporting"]
POINTS = {"very_strong": 8, "strong": 4, "moderate": 2, "supporting": 1}
# Each code's strength as originally defined; a different strength is written CODE_Strength.
DEFAULT = {
    "BA1": "stand_alone",
    "BS1": "strong",
    "PM2": "moderate",
    "PVS1": "very_strong",
    "PM5": "moderate",
    "PS3": "strong",
    "BS3": "strong",
}
BENIGN = {"BA1", "BS1", "BS3"}
CLASSES = [
    (10, "Pathogenic"),
    (6, "Likely pathogenic"),
    (0, "Uncertain significance"),
    (-6, "Likely benign"),
]
TRUNCATING = {"stop_gained", "frameshift_variant"}
SPLICE = {"splice_donor_variant", "splice_acceptor_variant"}
PTC = re.compile(r"^p\.[A-Z][a-z]{2}(\d+)(?:[A-Z][a-z]{2})?(?:fsTer(\d+)|Ter)$")
FIRST_CODON = re.compile(r"^p\.[A-Z][a-z]{2}(\d+)")
DELETED_SITE = re.compile(r"^(c\.-?\d+[+-][12])del$")


class Band(Strict):
    strength: Strength
    measure: Literal["faf95", "af", "grpmax_af", "absent"]
    above: float | None = None
    at_least: float | None = None
    below: float | None = None
    at_most: float | None = None
    ac_above: int | None = None
    ac_at_most: int | None = None

    def met(self, frequency: dict | None) -> bool:
        ac = (frequency or {}).get("ac", 0)
        if self.measure == "absent":
            return ac == 0
        # No call, or no frequency reported (gnomAD gives no FAF for a single observation),
        # counts as frequency 0: it meets "rare" bands and fails "common" ones.
        value = (frequency or {}).get(self.measure) or 0.0
        return (
            (self.above is None or value > self.above)
            and (self.at_least is None or value >= self.at_least)
            and (self.below is None or value < self.below)
            and (self.at_most is None or value <= self.at_most)
            and (self.ac_above is None or ac > self.ac_above)
            and (self.ac_at_most is None or ac <= self.ac_at_most)
        )


class Codons(Strict):
    strength: Strength
    at_least: int = 1
    at_most: int


class Window(Strict):
    first: int
    last: int


class GeneRules(Strict):
    panel: str
    cspec: str = Field(pattern=r"^GN\d{3}$")
    version: str
    ba1: list[Band]
    bs1: list[Band]
    pm2: list[Band]
    # PVS1, by the first rule that is set: the panel's own table (ENIGMA, BRCA1 and BRCA2);
    # codon cut-offs for the premature stop (InSiGHT, MLH1 and MSH2); a window of codons where
    # truncations count whatever the exon (InSiGHT, APC). Otherwise the NMD rule.
    pvs1_table: Literal["enigma"] | None = None
    # PS3 and BS3 from the panel's table of calibrated functional assays (ENIGMA Table 9).
    functional_table: Literal["enigma"] | None = None
    ptc_codons: list[Codons] = []
    ptc_window: Window | None = None
    splice_to_curator: bool = False
    notes: str = ""


class Rules(Strict):
    genes: dict[str, GeneRules]


def load_rules(path: Path = RULES) -> Rules:
    return Rules.model_validate(yaml.safe_load(path.read_text()))


def label(code: str, strength: str) -> str:
    if strength == DEFAULT[code]:
        return code
    return f"{code}_" + strength.replace("_", " ").title().replace(" ", "")


def _criterion(code: str, strength: str, reason: str) -> dict:
    return {"code": code, "label": label(code, strength), "strength": strength, "reason": reason}


def _frequency_text(frequency: dict | None) -> str:
    if not frequency or frequency["ac"] == 0:
        return "absent from gnomAD v4"
    faf = frequency.get("faf95")
    faf_text = f"FAF95 {faf:.2e} ({frequency.get('faf95_group')})" if faf else "no FAF95"
    return f"gnomAD v4 AC {frequency['ac']}, AF {frequency['af']:.2e}, {faf_text}"


def _not(reason: str, decided: bool = False) -> dict:
    """PVS1 not applied: decided (the panel's rules say it does not apply) or left to the
    curator (the rules cannot tell)."""
    return {"code": "PVS1", "reason": reason, "decided": decided}


@cache
def _functional_table() -> dict[tuple[str, str], dict]:
    with FUNCTIONAL.open() as f:
        lines = [line for line in f if not line.startswith("#")]
    return {(r["gene"], r["hgvsc"]): r for r in csv.DictReader(lines, delimiter="\t")}


def _functional(gene: str, vep: dict) -> tuple[list[dict], dict | None]:
    """PS3 or BS3 from ENIGMA Table 9, or a decided note when its assays were inconclusive."""
    row = _functional_table().get((gene, vep.get("hgvsc")))
    if row is None:
        return [], None
    if row["code"] in ("PS3", "BS3") and row["strength"]:
        return [_criterion(row["code"], row["strength"], f"ENIGMA Table 9: {row['text']}")], None
    return [], {
        "code": "PS3/BS3",
        "reason": f"ENIGMA Table 9: no code from calibrated assays. {row['text']}",
        "decided": True,
    }


@cache
def _enigma_table() -> dict:
    return yaml.safe_load(ENIGMA.read_text())["genes"]


def ptc_codon(hgvsp: str | None) -> int | None:
    """The codon of the premature stop: p.Arg1443Ter gives 1443; p.Gly324AlafsTer46, a
    frameshift whose new reading frame stops 46 codons on, gives 324 + 46 - 1 = 369."""
    found = PTC.match(hgvsp or "")
    if not found:
        return None
    start, shift = int(found[1]), found[2]
    return start + int(shift) - 1 if shift else start


def _deleted_site(entry: dict, hgvsc: str | None) -> dict | None:
    """Table 4 lists substitutions at the canonical +1, +2, -1, -2 positions. Deleting that
    base breaks the site as surely, so a one-base deletion there takes the table's strength
    when every substitution it lists at the position has the same one; otherwise None."""
    found = DELETED_SITE.match(hgvsc or "")
    if not found:
        return None
    sites = [v for k, v in entry["splice"].items() if k[:-3] == found[1]]
    strengths = {s["strength"] for s in sites}
    if not sites or len(strengths) != 1:
        return None
    codes = sorted({s["code"] for s in sites})
    return {
        "code": "/".join(codes),
        "strength": strengths.pop(),
        "note": f"one-base deletion; every substitution at {found[1]} is {', '.join(codes)}",
    }


def _enigma(gene: str, vep: dict, table: dict) -> tuple[list[dict], dict | None]:
    """PVS1 (and PM5_PTC) from ENIGMA's Specifications Table 4."""
    entry, consequences = table[gene], set(vep["consequences"])
    if consequences & TRUNCATING:
        number = int(vep["exon"].split("/")[0]) if vep.get("exon") else None
        codon = ptc_codon(vep.get("hgvsp"))
        rows = entry["exons"].get(number, [])
        row = next(
            (
                r
                for r in rows
                if ("before_codon" not in r or (codon is not None and codon < r["before_codon"]))
                and ("after_codon" not in r or (codon is not None and codon > r["after_codon"]))
            ),
            None,
        )
        if row is None:
            return [], _not(f"{vep.get('hgvsp')} in exon {number}: no ENIGMA Table 4 row matches")
        where = f"{vep['hgvsp']}, premature stop in exon {number}"
        if row["pvs1"]["strength"] is None:
            return [], _not(f"ENIGMA Table 4: {row['pvs1']['code']} for {where}", decided=True)
        met = [_criterion("PVS1", row["pvs1"]["strength"], f"ENIGMA Table 4: {where}")]
        if row["pm5_ptc"]["strength"]:
            met.append(
                _criterion(
                    "PM5",
                    row["pm5_ptc"]["strength"],
                    f"ENIGMA Table 4: {row['pm5_ptc']['code']}, proven pathogenic PTCs in exon"
                    f" {number}",
                )
            )
        return met, None
    if consequences & SPLICE:
        site = entry["splice"].get(vep.get("hgvsc")) or _deleted_site(entry, vep.get("hgvsc"))
        if site is None:
            return [], _not(f"{vep.get('hgvsc')} is not in ENIGMA Table 4; for the curator")
        why = f"ENIGMA Table 4: {site['code']} for {vep['hgvsc']}" + (
            f" ({site['note']})" if site.get("note") else ""
        )
        if site["strength"] is None:
            return [], _not(why, decided=True)
        return [_criterion("PVS1", site["strength"], why)], None
    return [], None


def _pvs1(
    gene: str, rules: GeneRules, vep: dict, exon_lengths: list[int]
) -> tuple[list[dict], dict | None]:
    """The criteria PVS1 adds (with PM5_PTC for ENIGMA), and a note when PVS1 is not applied
    to a null variant; ([], None) if the variant is not a null variant at all."""
    if rules.pvs1_table == "enigma":
        return _enigma(gene, vep, _enigma_table())
    consequences = set(vep["consequences"])
    if consequences & TRUNCATING:
        if rules.ptc_window:
            # Truncations in APC's last exon escape NMD but still cause FAP, so the panel sets
            # PVS1 by where the truncation starts, not by exon.
            found = FIRST_CODON.match(vep.get("hgvsp") or "")
            if not found:
                return [], _not(f"no protein position in {vep.get('hgvsp')}")
            codon, window = int(found[1]), rules.ptc_window
            if window.first <= codon <= window.last:
                return [
                    _criterion(
                        "PVS1",
                        "very_strong",
                        f"{vep['hgvsp']}: codon {codon}, within the panel's PVS1 boundaries"
                        f" ({window.first} to {window.last})",
                    )
                ], None
            return [], _not(
                f"{vep['hgvsp']}: codon {codon}, outside the panel's PVS1 boundaries"
                f" ({window.first} to {window.last})",
                decided=True,
            )
        codon = ptc_codon(vep.get("hgvsp"))
        if rules.ptc_codons:
            if codon is None:
                return [], _not(f"no premature stop codon in {vep.get('hgvsp')}")
            for band in rules.ptc_codons:
                if band.at_least <= codon <= band.at_most:
                    return [
                        _criterion("PVS1", band.strength, f"premature stop at codon {codon}")
                    ], None
            return [], _not(
                f"premature stop at codon {codon}, past the panel's PVS1 cut-offs", decided=True
            )
        number, total = map(int, vep["exon"].split("/")) if vep.get("exon") else (0, 0)
        if number and number == total:
            return [], _not(
                "truncation in the last exon escapes NMD; PVS1 strength is for the curator"
            )
        return [
            _criterion(
                "PVS1", "very_strong", f"{vep['hgvsp']} in exon {vep['exon']}, NMD predicted"
            )
        ], None
    if consequences & SPLICE:
        if rules.splice_to_curator:
            return [], _not(
                f"{vep.get('hgvsc')}: the panel grades splice sites from splicing predictions and"
                " RNA data; for the curator"
            )
        if not vep.get("intron"):
            return [], _not(f"{vep.get('hgvsc')}: no intron number")
        intron, _ = map(int, vep["intron"].split("/"))
        # A donor (+1, +2) site loss skips the exon before the intron; an acceptor (-1, -2)
        # site loss skips the exon after it.
        skipped = intron if "splice_donor_variant" in consequences else intron + 1
        if skipped in (1, len(exon_lengths)):
            return [], _not(f"splice site of exon {skipped}, the first or last; for the curator")
        length = exon_lengths[skipped - 1]
        if length % 3:
            return [
                _criterion(
                    "PVS1",
                    "very_strong",
                    f"{vep['hgvsc']}: skipping exon {skipped} ({length} nt) shifts the frame,"
                    " NMD predicted",
                )
            ], None
        return [], _not(
            f"{vep['hgvsc']}: skipping exon {skipped} ({length} nt) keeps the frame; whether the"
            " lost region is critical is for the curator"
        )
    return [], None


def assess(
    gene: str,
    rules: GeneRules,
    frequency: dict | None,
    vep: dict | None,
    exon_lengths: list[int],
) -> dict:
    met, not_assessed = [], []
    text = _frequency_text(frequency)
    for code, bands in (("BA1", rules.ba1), ("BS1", rules.bs1), ("PM2", rules.pm2)):
        if code == "BS1" and met:
            continue  # BA1 stands alone; BS1 adds nothing to it
        for band in bands:
            if band.met(frequency):
                met.append(_criterion(code, band.strength, text))
                break
    if vep is None:
        not_assessed.append(_not("no MANE Select consequence"))
    else:
        criteria, note = _pvs1(gene, rules, vep, exon_lengths)
        met += criteria
        if note:
            not_assessed.append(note)
        if rules.functional_table == "enigma":
            criteria, note = _functional(gene, vep)
            met += criteria
            if note:
                not_assessed.append(note)
    return {"met": met, "not_assessed": not_assessed} | classify(met)


def classify(met: list[dict]) -> dict:
    if any(c["code"] == "BA1" for c in met):
        return {"points": None, "classification": "Benign"}
    points = sum(
        -POINTS[c["strength"]] if c["code"] in BENIGN else POINTS[c["strength"]] for c in met
    )
    classification = next((name for floor, name in CLASSES if points >= floor), "Benign")
    return {"points": points, "classification": classification}
