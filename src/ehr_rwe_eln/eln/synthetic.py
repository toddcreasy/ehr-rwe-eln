"""Synthetic ELN entries with known answers.

Each entry is free text a bench scientist might write after running assays on study specimens,
generated from templates with a seeded random generator. Because the generator decides what goes
in, it also knows the correct extraction (the ground truth), so the eval needs no hand labeling.

Entries vary the way real notebooks do: prose, tables, or lists; analyte aliases; unit and date
spellings. Some carry traps an extraction must skip: QC material, reagent lots and plate ids, and
a failed run whose value is replaced by a repeat.

Hard entries (hard=True) add traps that need reading the whole entry: a sample manifest with a
collection date per sample and results keyed by sample id alone, units stated once, a rejected
sample with no results, a value corrected further down, a value read on a diluted specimen (the
result is the value times the dilution), and duplicate readings with their mean. The default
entries are unchanged: hard traps draw from the random generator only when hard is set.

Synthetic only: subject codes map to Synthea persons, never to real people.
"""

import random
from dataclasses import dataclass, field
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
    # The traps in this entry, so an eval can score each one.
    traps: list[str] = field(default_factory=list)


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
    hard: bool = False,
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
    manifest = hard and rng.random() < 0.4
    traps = ["manifest"] if manifest else []

    samples, lines = [], []
    for subject in rng.sample(eligible, min(len(eligible), rng.randint(1, 4))):
        visits[subject] = visits.get(subject, 0) + 1
        sample_id = f"S-{subject.split('-')[1]}-{visits[subject]:02d}"
        day = collected
        if manifest and show_dates:
            # Each sample its own day, up to two weeks before the first, inside its window.
            day = collected - timedelta(days=rng.randrange(0, 15))
            if day < subjects[subject][0]:
                day = collected
        samples.append(
            Sample(
                sample_id=sample_id,
                subject_id=subject,
                specimen_type=specimen_type,
                collection_date=day if show_dates else None,
            )
        )
        values = {a: _value(rng, units[a]) for a in panel}
        lines.append((subject, sample_id, values))

    style = "manifest" if manifest else rng.choice(["prose", "table", "list"])
    # How each value reads in the entry; hard traps change some.
    shown = {
        (sample_id, a): _number(values[a], units[a].decimals)
        for _, sample_id, values in lines
        for a in panel
    }
    # Text after the unit: a dilution or a duplicate's mean.
    marks = {key: "" for key in shown}
    notes, rejected = [], None
    units_once = hard and style in ("prose", "list", "manifest") and rng.random() < 0.4
    if units_once:
        traps.append("units_once")
    if hard and len(lines) >= 2 and rng.random() < 0.3:
        traps.append("rejected_sample")
        rejected = rng.choice(lines)[1]
    measured = [(sid, a) for _, sid, _ in lines if sid != rejected for a in panel]
    values_of = {sid: values for _, sid, values in lines}
    if hard:
        # Each trap takes its own value, so no value carries two.
        pool = rng.sample(measured, len(measured))
        if pool and rng.random() < 0.3:
            traps.append("correction")
            sid, a = pool.pop()
            wrong = _value(rng, units[a])
            while wrong == values_of[sid][a]:
                wrong = _value(rng, units[a])
            shown[(sid, a)] = _number(wrong, units[a].decimals)
            right = _number(values_of[sid][a], units[a].decimals)
            notes.append(
                f"Correction: {aliases[a]} for {sid} is {right}, not {shown[(sid, a)]}"
                f" (transcription error)."
            )
        if pool and rng.random() < 0.3:
            traps.append("dilution")
            sid, a = pool.pop()
            factor, d = rng.choice([2, 5, 10]), units[a].decimals
            raw = round(values_of[sid][a] / factor, d) or 10**-d
            values_of[sid][a] = round(raw * factor, d)
            shown[(sid, a)] = _number(raw, d)
            marks[(sid, a)] = f" (1:{factor} dilution)"
            notes.append(
                "Diluted specimens: values are as read on the dilution; multiply by the"
                " dilution factor for the specimen's concentration."
            )
        if pool and rng.random() < 0.3:
            traps.append("replicates")
            sid, a = pool.pop()
            d = units[a].decimals
            step = rng.randint(1, 5) * 10**-d
            v = values_of[sid][a]
            shown[(sid, a)] = f"{_number(v - step, d)}, {_number(v + step, d)}"
            marks[(sid, a)] = f" (duplicate; mean {_number(v, d)})"

    assays = ", ".join(aliases[a] for a in panel)
    header = f"Ran {assays} on {specimen_word} specimens."
    if show_dates and not manifest:
        header += f" All specimens collected {_date_text(rng, collected)}."
    out = [header]
    if rng.random() < 0.5:
        traps.append("reagent_lot")
        lot = f"{rng.randint(1000, 9999)}{rng.choice('ABCD')}"
        out.append(f"Reagent lot {lot}, plate P-{rng.randint(1, 40)}.")
    if units_once:
        out.append("Units: " + ", ".join(f"{aliases[a]} {spellings[a]}" for a in panel) + ".")

    def value_text(a: str, sample_id: str) -> str:
        unit = "" if units_once else f" {spellings[a]}"
        key = (sample_id, a)
        return f"{aliases[a]} {shown[key]}{unit}{marks[key]}"

    rejected_text = "hemolyzed, not assayed"
    if style == "table":
        columns = ["Subject", "Sample"] + [f"{aliases[a]} ({spellings[a]})" for a in panel]
        out.append("| " + " | ".join(columns) + " |")
        out.append("|" + "---|" * len(columns))
        for subject, sample_id, _ in lines:
            if sample_id == rejected:
                cells = ["hemolyzed"] * len(panel)
            else:
                cells = [shown[(sample_id, a)] + marks[(sample_id, a)] for a in panel]
            out.append("| " + " | ".join([subject, sample_id, *cells]) + " |")
    elif style == "manifest":
        out.append("Samples:")
        out.append("| Sample | Subject |" + (" Collected |" if show_dates else ""))
        out.append("|---|---|" + ("---|" if show_dates else ""))
        for sample in samples:
            row = f"| {sample.sample_id} | {sample.subject_id} |"
            if show_dates:
                row += f" {_date_text(rng, sample.collection_date)} |"
            out.append(row)
        out.append("Results:")
        for _, sample_id, _ in lines:
            if sample_id == rejected:
                out.append(f"- {sample_id}: {rejected_text}.")
            else:
                out.append(f"- {sample_id}: " + "; ".join(value_text(a, sample_id) for a in panel))
    elif style == "list":
        for subject, sample_id, _ in lines:
            if sample_id == rejected:
                out.append(f"- {sample_id} ({subject}): {rejected_text}.")
            else:
                readings = "; ".join(value_text(a, sample_id) for a in panel)
                out.append(f"- {sample_id} ({subject}): " + readings)
    else:
        for subject, sample_id, _ in lines:
            if sample_id == rejected:
                out.append(f"Subject {subject}, sample {sample_id}: {rejected_text}.")
            else:
                readings = " and ".join(value_text(a, sample_id) for a in panel)
                out.append(f"Subject {subject}, sample {sample_id}: {readings}.")

    if rng.random() < 0.3:
        # A failed first run: the entry gives a value, then replaces it. Truth keeps the repeat.
        traps.append("failed_run")
        a = panel[0]
        target = rng.choice([s for s in samples if s.sample_id != rejected]).sample_id
        first = _value(rng, units[a])
        out.append(
            f"Note: first run of {aliases[a]} on {target} read"
            f" {_number(first, units[a].decimals)} {spellings[a]} but failed QC; repeated,"
            f" the value above is the repeat."
        )
    if rng.random() < 0.5:
        traps.append("qc")
        a = panel[0]
        qc = _value(rng, units[a])
        out.append(
            f"QC level {rng.randint(1, 3)}: {aliases[a]} {_number(qc, units[a].decimals)}"
            f" {spellings[a]}, within range."
        )
    out += notes

    title = f"{assays} on {specimen_type} specimens"
    results = [
        Result(sample_id=sid, analyte=a, value=values_of[sid][a], unit=units[a].code)
        for sid, a in measured
    ]
    truth = Extraction(samples=samples, results=results)
    body = "\n".join(out)
    return Entry(f"ELN-{number:05d}", title, rng.choice(AUTHORS), run_day, body, truth, traps)


def generate_entries(
    subjects: dict[str, tuple[date, date]], n: int, seed: int = 0, hard: bool = False
) -> list[Entry]:
    rng, visits = random.Random(seed), {}
    return [generate_entry(rng, number, subjects, visits, hard) for number in range(1, n + 1)]
