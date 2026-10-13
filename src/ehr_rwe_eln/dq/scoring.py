"""Pass, fail, error, and not applicable for each check, and the run summary.

Ports DQD v2.9.0's evaluateThresholds.R, calculateNotApplicableStatus.R, and summarizeResults.R.
"""

import re
from dataclasses import dataclass

from ehr_rwe_eln.dq.checks import Check

# A failed cdmTable or cdmField check means the object is missing; DQD spots that by the error.
MISSING_OBJECT = re.compile(
    "does not exist|missing|not found|invalid object name|invalid column name|ORA-00942"
    "|no such table|no such column",
    re.IGNORECASE,
)


@dataclass
class Result:
    check: Check
    num_violated_rows: int | None
    num_denominator_rows: int | None
    error: str | None
    execution_seconds: float
    query_text: str
    failed: bool = False
    passed: bool = False
    is_error: bool = False
    not_applicable: bool = False
    not_applicable_reason: str | None = None

    @property
    def pct_violated_rows(self) -> float | None:
        if self.num_violated_rows is None:
            return None
        if self.num_denominator_rows == 0:
            return 0.0
        return self.num_violated_rows / self.num_denominator_rows


def evaluate(results: list[Result]) -> None:
    """Set failed, is_error, not_applicable, and passed on every result, in place."""
    for r in results:
        threshold = r.check.threshold
        if r.error is not None:
            missing = MISSING_OBJECT.search(r.error) and r.check.name in ("cdmField", "cdmTable")
            r.failed, r.is_error = bool(missing), not missing
        elif threshold is None or threshold == 0:
            r.failed = r.num_violated_rows is not None and r.num_violated_rows > 0
        else:
            r.failed = r.pct_violated_rows * 100 > threshold
    _not_applicable(results)
    for r in results:
        if r.not_applicable:
            r.failed = False
        r.passed = not (r.failed or r.is_error or r.not_applicable)


def _not_applicable(results: list[Result]) -> None:
    by_name = {}
    for r in results:
        by_name.setdefault(r.check.name, []).append(r)
    table_missing = {r.check.table: r.failed for r in by_name.get("cdmTable", [])}
    field_missing = {(r.check.table, r.check.field): r.failed for r in by_name.get("cdmField", [])}
    value_counts = by_name.get("measureValueCompleteness", [])
    table_empty = {r.check.table: r.num_denominator_rows == 0 for r in value_counts}
    field_empty = {
        (r.check.table, r.check.field): r.num_denominator_rows is not None
        and r.num_denominator_rows == r.num_violated_rows
        for r in value_counts
    }
    conditions_absent = table_missing.get("CONDITION_OCCURRENCE", False) or table_empty.get(
        "CONDITION_OCCURRENCE", False
    )

    for r in results:
        table, field = r.check.table, r.check.field
        flags = {
            "table_missing": table_missing.get(table, False),
            "field_missing": field_missing.get((table, field), False),
            "table_empty": table_empty.get(table, False),
            "field_empty": field_empty.get((table, field), False),
            # A concept check with nothing to count: the concept (and unit) never appears.
            "concept_missing": r.check.level == "CONCEPT"
            and r.check.unit_concept_id is None
            and r.num_denominator_rows == 0,
            "concept_and_unit_missing": r.check.level == "CONCEPT"
            and r.check.unit_concept_id is not None
            and r.num_denominator_rows == 0,
        }
        if r.check.name == "measureConditionEraCompleteness":
            r.not_applicable = conditions_absent
            if conditions_absent:
                r.not_applicable_reason = "Table CONDITION_OCCURRENCE is empty."
            continue
        r.not_applicable = _applies_not(r, **flags)
        if r.not_applicable:
            r.not_applicable_reason = _reason(r.check, **flags)


def _applies_not(
    r: Result,
    table_missing,
    field_missing,
    table_empty,
    field_empty,
    concept_missing,
    concept_and_unit_missing,
) -> bool:
    name = r.check.name
    if name in ("measurePersonCompleteness", "cdmField"):
        return table_missing
    if name == "cdmTable":
        return False
    if table_missing or field_missing:
        return True
    if r.is_error:
        return False
    if table_empty:
        return True
    if name == "measureValueCompleteness":
        return False
    return field_empty or concept_missing or concept_and_unit_missing


def _reason(
    check: Check,
    table_missing,
    field_missing,
    table_empty,
    field_empty,
    concept_missing,
    concept_and_unit_missing,
) -> str:
    table, field = check.table, check.field
    if table_missing:
        return f"Table {table} does not exist."
    if field_missing:
        return f"Field {table}.{field} does not exist."
    if table_empty:
        return f"Table {table} is empty."
    if field_empty:
        return f"Field {table}.{field} is not populated."
    if concept_missing:
        return f"{field}={check.concept_id} is missing from the {table} table."
    return (
        f"Combination of {field}={check.concept_id}, unitConceptId={check.unit_concept_id}"
        f" and VALUE_AS_NUMBER IS NOT NULL is missing from the {table} table."
    )


def summarize(results: list[Result]) -> dict:
    """DQD's Overview, plus a strict pass rate that leaves out not applicable checks.

    DQD's countPassed is every check that did not fail, so it counts not applicable and errored
    checks as passed; percentPassed follows. Both are kept as DQD computes them.
    """
    total = len(results)
    overall_failed = sum(r.failed for r in results)
    passed = total - overall_failed
    overview = {
        "countTotal": total,
        "countPassed": passed,
        "countErrorFailed": sum(r.error is not None for r in results),
        "countThresholdFailed": sum(r.failed and r.error is None for r in results),
        "countOverallFailed": overall_failed,
        "percentPassed": round(passed / (passed + overall_failed) * 100, 2),
        "percentFailed": round(overall_failed / (passed + overall_failed) * 100, 2),
    }
    for category in ("Plausibility", "Conformance", "Completeness"):
        in_category = [r for r in results if r.check.category == category]
        overview[f"countTotal{category}"] = len(in_category)
        overview[f"countFailed{category}"] = sum(r.failed for r in in_category)
        overview[f"countPassed{category}"] = sum(r.passed for r in in_category)

    applicable = [r for r in results if not r.not_applicable]
    overview["countNotApplicable"] = total - len(applicable)
    overview["countIsError"] = sum(r.is_error for r in results)
    overview["strictPercentPassed"] = (
        round(sum(r.passed for r in applicable) / len(applicable) * 100, 2) if applicable else None
    )
    return overview
