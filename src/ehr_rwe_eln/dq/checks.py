"""Which data quality checks run, on which tables and fields, with which thresholds.

The csv/ files are copied unchanged from OHDSI/DataQualityDashboard v2.9.0, inst/csv
(Apache License 2.0). Each row of Check_Descriptions is a check type with a filter; the check
type runs once for every Table_Level or Field_Level row its filter matches, exactly as DQD's
executeDqChecks expands them. CONCEPT level checks are not ported yet.
"""

import csv
import re
from dataclasses import dataclass
from pathlib import Path

CSV = Path(__file__).parent / "csv"
LEVELS = ("TABLE", "FIELD")

# DQD's default tablesToExclude: the vocabulary tables, which come from Athena, not the ETL.
EXCLUDED_TABLES = {
    "CONCEPT",
    "VOCABULARY",
    "CONCEPT_ANCESTOR",
    "CONCEPT_RELATIONSHIP",
    "CONCEPT_CLASS",
    "CONCEPT_SYNONYM",
    "RELATIONSHIP",
    "DOMAIN",
}

# Filters are R expressions such as isForeignKey=='Yes' & fkDomain!= ''. These are the only
# shapes the CSV uses, so they are parsed here rather than evaluated.
FILTER_TERM = re.compile(r"\s*(\w+)\s*(==|!=)\s*'([^']*)'\s*")


@dataclass(frozen=True)
class Check:
    check_id: str
    level: str
    name: str
    table: str
    field: str | None
    description: str
    context: str
    category: str
    subcategory: str | None
    severity: str
    threshold: float | None
    notes: str | None
    params: dict[str, str]


def _read(name: str) -> list[dict[str, str]]:
    # DQD reads blank and single-space cells as NA; they are left out of each row here.
    with (CSV / f"OMOP_CDMv5.4_{name}.csv").open(encoding="utf-8-sig", newline="") as f:
        return [{k: v for k, v in row.items() if v not in ("", " ")} for row in csv.DictReader(f)]


def matches(row: dict[str, str], evaluation_filter: str) -> bool:
    for term in evaluation_filter.split("&"):
        match = FILTER_TERM.fullmatch(term)
        if match is None:
            raise ValueError(f"unsupported evaluation filter: {evaluation_filter}")
        column, op, value = match.groups()
        # An NA cell makes the R comparison NA, and dplyr::filter drops the row.
        if column not in row or (row[column] == value) != (op == "=="):
            return False
    return True


def _check(description: dict[str, str], row: dict[str, str]) -> Check:
    level, name = description["checkLevel"], description["checkName"]
    table, field = row["cdmTableName"], row.get("cdmFieldName")
    # DQD renders the description with every value upper cased.
    values = {k: v.upper() for k, v in row.items()}
    text = re.sub(r"@(\w+)", lambda m: values.get(m[1], m[0]), description["checkDescription"])
    threshold = row.get(f"{name}Threshold")
    return Check(
        check_id="_".join(p.replace(" ", "") for p in (level, name, table, field) if p).lower(),
        level=level,
        name=name,
        table=table,
        field=field,
        description=text,
        context=description["kahnContext"],
        category=description["kahnCategory"],
        subcategory=description.get("kahnSubcategory"),
        severity=description["severity"],
        threshold=float(threshold) if threshold is not None else None,
        notes=row.get(f"{name}Notes"),
        params=row,
    )


def load_checks() -> list[Check]:
    tables = [r for r in _read("Table_Level") if r["cdmTableName"] not in EXCLUDED_TABLES]
    fields = [
        r
        for r in _read("Field_Level")
        if r["cdmTableName"] not in EXCLUDED_TABLES and r["cdmFieldName"] != "offset"
    ]
    for row in fields:
        row["cdmFieldName"] = row["cdmFieldName"].upper()
    rows = {"TABLE": tables, "FIELD": fields}
    return [
        _check(description, row)
        for description in _read("Check_Descriptions")
        if description["checkLevel"] in LEVELS
        for row in rows[description["checkLevel"]]
        if matches(row, description["evaluationFilter"])
    ]
