"""Synthetic ELN entries with known answers.

Each entry is free text a bench scientist might write after running assays on study specimens,
generated from templates with a seeded random generator. Because the generator decides what goes
in, it also knows the correct extraction (the ground truth), so the eval needs no hand labeling.

Entries vary the way real notebooks do: prose, tables, or lists; analyte aliases; unit and date
spellings. Some carry traps an extraction must skip: QC material, reagent lots and plate ids, and
a failed run whose value is replaced by a repeat.

Synthetic only: subject codes map to Synthea persons, never to real people.
"""

import random
from dataclasses import dataclass
from datetime import date, timedelta

from ehr_rwe_eln.eln.models import Extraction, Result, Sample


@dataclass(frozen=True)
class UnitSpec:
    code: str
    spellings: tuple[str, ...]
    low: float
    high: float
    decimals: int


@dataclass(frozen=True)
class AnalyteSpec:
    aliases: tuple[str, ...]
    units: tuple[UnitSpec, ...]
    specimen_types: tuple[str, ...]


ANALYTES = {
    "creatinine": AnalyteSpec(
        ("creatinine", "Crea", "serum creatinine", "CREA"),
        (
            UnitSpec("mg/dL", ("mg/dL", "mg/dl"), 0.6, 2.5, 2),
            UnitSpec("umol/L", ("µmol/L", "umol/L", "umol/l"), 50, 220, 0),
        ),
        ("serum", "plasma"),
    ),
    "hba1c": AnalyteSpec(
        ("HbA1c", "A1c", "hemoglobin A1c", "glycated hemoglobin"),
        (UnitSpec("%", ("%",), 4.8, 10.5, 1), UnitSpec("mmol/mol", ("mmol/mol",), 29, 91, 0)),
        ("whole blood",),
    ),
    "crp": AnalyteSpec(
        ("CRP", "C-reactive protein"),
        (UnitSpec("mg/L", ("mg/L", "mg/l"), 1, 80, 1),),
        ("serum", "plasma"),
    ),
    "hs_crp": AnalyteSpec(
        ("hsCRP", "hs-CRP", "high-sensitivity CRP"),
        (UnitSpec("mg/L", ("mg/L", "mg/l"), 0.2, 9.9, 2),),
        ("serum", "plasma"),
    ),
    "il6": AnalyteSpec(
        ("IL-6", "IL6", "interleukin-6"),
        (UnitSpec("pg/mL", ("pg/mL", "pg/ml"), 0.8, 40, 1),),
        ("serum", "plasma"),
    ),
    "nt_probnp": AnalyteSpec(
        ("NT-proBNP", "NTproBNP"),
        (UnitSpec("pg/mL", ("pg/mL", "pg/ml"), 20, 3500, 0),),
        ("serum", "plasma"),
    ),
}

SERUM_PANELS = [["creatinine"], ["crp"], ["hs_crp", "il6"], ["nt_probnp"], ["creatinine", "crp"]]
SERUM_PANELS += [["il6", "crp", "nt_probnp"]]
SPECIMEN_WORDS = {
    "serum": ("serum", "SST serum"),
    "plasma": ("EDTA plasma", "plasma"),
    "whole blood": ("whole blood", "EDTA whole blood"),
}
AUTHORS = ("Analyst A", "Analyst B", "Analyst C")


@dataclass
class Entry:
    entry_id: str
    title: str
    author: str
    created: date
    body: str
    truth: Extraction


def subject_registry(person_ids: list[int], prefix: str = "HTN") -> dict[str, int]:
    """Study subject codes for the given persons, in order: HTN-0001, HTN-0002, ..."""
    return {f"{prefix}-{i:04d}": person_id for i, person_id in enumerate(person_ids, start=1)}


def _date_text(rng: random.Random, day: date) -> str:
    style = rng.choice(["iso", "dmy", "mdy"])
    if style == "iso":
        return day.isoformat()
    if style == "dmy":
        return f"{day.day} {day:%b %Y}"
    return f"{day:%B} {day.day}, {day.year}"


def _value(rng: random.Random, unit: UnitSpec) -> float:
    return round(rng.uniform(unit.low, unit.high), unit.decimals)


def _number(value: float, decimals: int) -> str:
    return f"{value:.{decimals}f}"


def generate_entry(
    rng: random.Random,
    number: int,
    subjects: dict[str, tuple[date, date]],
    visits: dict[str, int],
) -> Entry:
    """One entry on 1 to 4 subjects, each with one new specimen and the same assay panel.
    subjects maps each code to the window its specimens may be collected in (its observation
    period). visits counts each subject's specimens so far, so sample ids never repeat."""
    if rng.random() < 0.2:
        panel, specimen_type = ["hba1c"], "whole blood"
    else:
        panel, specimen_type = rng.choice(SERUM_PANELS), rng.choice(["serum", "plasma"])
    units = {a: rng.choice(ANALYTES[a].units) for a in panel}
    aliases = {a: rng.choice(ANALYTES[a].aliases) for a in panel}
    spellings = {a: rng.choice(units[a].spellings) for a in panel}
    specimen_word = rng.choice(SPECIMEN_WORDS[specimen_type])

    while True:
        collected = date(2015, 1, 1) + timedelta(days=rng.randrange(0, 3650))
        eligible = sorted(c for c, (start, end) in subjects.items() if start <= collected <= end)
        if eligible:
            break
    show_dates = rng.random() < 0.8
    run_day = collected + timedelta(days=rng.randrange(1, 60))

    samples, results, lines = [], [], []
    for subject in rng.sample(eligible, min(len(eligible), rng.randint(1, 4))):
        visits[subject] = visits.get(subject, 0) + 1
        sample_id = f"S-{subject.split('-')[1]}-{visits[subject]:02d}"
        samples.append(
            Sample(
                sample_id=sample_id,
                subject_id=subject,
                specimen_type=specimen_type,
                collection_date=collected if show_dates else None,
            )
        )
        values = {a: _value(rng, units[a]) for a in panel}
        results += [
            Result(sample_id=sample_id, analyte=a, value=values[a], unit=units[a].code)
            for a in panel
        ]
        lines.append((subject, sample_id, values))

    style = rng.choice(["prose", "table", "list"])
    assays = ", ".join(aliases[a] for a in panel)
    header = f"Ran {assays} on {specimen_word} specimens."
    if show_dates:
        header += f" All specimens collected {_date_text(rng, collected)}."
    out = [header]
    if rng.random() < 0.5:
        lot = f"{rng.randint(1000, 9999)}{rng.choice('ABCD')}"
        out.append(f"Reagent lot {lot}, plate P-{rng.randint(1, 40)}.")

    def value_text(a: str, values: dict[str, float]) -> str:
        return f"{aliases[a]} {_number(values[a], units[a].decimals)} {spellings[a]}"

    if style == "table":
        columns = ["Subject", "Sample"] + [f"{aliases[a]} ({spellings[a]})" for a in panel]
        out.append("| " + " | ".join(columns) + " |")
        out.append("|" + "---|" * len(columns))
        for subject, sample_id, values in lines:
            cells = [_number(values[a], units[a].decimals) for a in panel]
            out.append("| " + " | ".join([subject, sample_id, *cells]) + " |")
    elif style == "list":
        for subject, sample_id, values in lines:
            out.append(
                f"- {sample_id} ({subject}): " + "; ".join(value_text(a, values) for a in panel)
            )
    else:
        for subject, sample_id, values in lines:
            readings = " and ".join(value_text(a, values) for a in panel)
            out.append(f"Subject {subject}, sample {sample_id}: {readings}.")

    if rng.random() < 0.3:
        # A failed first run: the entry gives a value, then replaces it. Truth keeps the repeat.
        a = panel[0]
        target = rng.choice(samples).sample_id
        first = _value(rng, units[a])
        out.append(
            f"Note: first run of {aliases[a]} on {target} read"
            f" {_number(first, units[a].decimals)} {spellings[a]} but failed QC; repeated,"
            f" the value above is the repeat."
        )
    if rng.random() < 0.5:
        a = panel[0]
        qc = _value(rng, units[a])
        out.append(
            f"QC level {rng.randint(1, 3)}: {aliases[a]} {_number(qc, units[a].decimals)}"
            f" {spellings[a]}, within range."
        )

    title = f"{assays} on {specimen_type} specimens"
    truth = Extraction(samples=samples, results=results)
    return Entry(f"ELN-{number:05d}", title, rng.choice(AUTHORS), run_day, "\n".join(out), truth)


def generate_entries(subjects: dict[str, tuple[date, date]], n: int, seed: int = 0) -> list[Entry]:
    rng, visits = random.Random(seed), {}
    return [generate_entry(rng, number, subjects, visits) for number in range(1, n + 1)]
