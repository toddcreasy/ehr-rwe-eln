"""Bias diagnostics for one protocol: everything needed to judge whether its estimate can be
trusted, gathered in one place.

- Attrition: how many people each eligibility rule removed.
- Balance and positivity: covariate SMDs before and after weighting, the propensity score and
  weight ranges, the effective sample size, and the covariates the model dropped.
- Not estimable: why, when the arms do not overlap and no estimate is made.
- Estimates: crude next to weighted, with robust and bootstrap intervals.
- Negative controls: outcomes neither strategy can plausibly cause, run through the same analysis.
  Their hazard ratios should be near 1; an interval that excludes 1 points to confounding the
  weights did not remove (or chance, which grows with the number of controls).

Demonstration on synthetic data only; no clinical claims.
"""

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime

import pandas as pd
import psycopg
from psycopg.types.json import Jsonb

from ehr_rwe_eln.tte.cohort import build_analysis_table
from ehr_rwe_eln.tte.covariates import add_covariates
from ehr_rwe_eln.tte.propensity import NotEstimable, Propensity, fit_propensity
from ehr_rwe_eln.tte.protocol import Outcome, Protocol
from ehr_rwe_eln.tte.survival import Survival, analyze


@dataclass
class Arm:
    name: str
    persons: int
    events: int
    median_follow_up_days: float


@dataclass
class NegativeControl:
    name: str
    persons: int
    events: int
    hazard_ratio: float | None = None
    robust_ci: tuple[float, float] | None = None
    not_estimable: str | None = None

    @property
    def excludes_null(self) -> bool:
        return self.robust_ci is not None and not self.robust_ci[0] <= 1 <= self.robust_ci[1]


@dataclass
class Report:
    protocol: Protocol
    attrition: list[tuple[str, int]]
    arms: list[Arm]
    not_estimable: str | None = None
    propensity: Propensity | None = None
    survival: Survival | None = None
    negative_controls: list[NegativeControl] = field(default_factory=list)


def build_report(con: psycopg.Connection, protocol: Protocol) -> Report:
    attrition, table = build_analysis_table(con, protocol)
    strategies = protocol.strategies
    arms = [
        Arm(
            strategy.name,
            int((table.arm == arm).sum()),
            int(table.event[table.arm == arm].sum()),
            float(table.days[table.arm == arm].median()),
        )
        for arm, strategy in ((1, strategies.treatment), (0, strategies.comparator))
    ]
    report = Report(protocol, attrition, arms)
    table = add_covariates(con, protocol, table)
    try:
        report.propensity = fit_propensity(table, protocol)
    except NotEstimable as exc:
        report.not_estimable = str(exc)
        return report
    report.survival = analyze(table, protocol)
    report.negative_controls = [
        negative_control(con, protocol, outcome) for outcome in protocol.negative_controls
    ]
    return report


def negative_control(
    con: psycopg.Connection, protocol: Protocol, outcome: Outcome
) -> NegativeControl:
    """The protocol rerun with this outcome: its own eligibility (no prior outcome), propensity
    weights, and weighted Cox model. No bootstrap; the robust interval is enough to flag it."""
    control = protocol.model_copy(
        update={
            "outcome": outcome,
            "analysis": protocol.analysis.model_copy(update={"bootstrap_replicates": 0}),
        }
    )
    _, table = build_analysis_table(con, control)
    table = add_covariates(con, control, table)
    result = NegativeControl(outcome.name, len(table), int(table.event.sum()))
    try:
        survival = analyze(table, control)
    except NotEstimable as exc:
        result.not_estimable = str(exc)
        return result
    result.hazard_ratio = survival.weighted.hazard_ratio
    result.robust_ci = survival.hazard_ratio_robust_ci
    return result


def _records(frame: pd.DataFrame) -> list[dict]:
    # Through pandas' JSON writer: numpy numbers become plain ones, NaN becomes null.
    return json.loads(frame.to_json(orient="records"))


def report_json(report: Report) -> dict:
    protocol = report.protocol
    out = {
        "protocol": {
            "id": protocol.id,
            "name": protocol.name,
            "description": protocol.description,
            "treatment": protocol.strategies.treatment.name,
            "comparator": protocol.strategies.comparator.name,
            "outcome": protocol.outcome.name,
        },
        "attrition": [{"rule": rule, "persons": n} for rule, n in report.attrition],
        "arms": [asdict(arm) for arm in report.arms],
        "not_estimable": report.not_estimable,
        "balance": None,
        "diagnostics": None,
        "survival": None,
        "negative_controls": [
            {**asdict(nc), "excludes_null": nc.excludes_null} for nc in report.negative_controls
        ],
    }
    if report.propensity is not None:
        out["balance"] = _records(report.propensity.balance)
        out["diagnostics"] = report.propensity.diagnostics
    if report.survival is not None:
        s = report.survival
        out["survival"] = {
            "crude_risks": _records(s.crude.risks),
            "weighted_risks": _records(s.weighted.risks),
            "crude_hazard_ratio": s.crude.hazard_ratio,
            "hazard_ratio": s.weighted.hazard_ratio,
            "hazard_ratio_robust_ci": s.hazard_ratio_robust_ci,
            # Keyed by estimate, e.g. risk_difference_365 or hazard_ratio: {low, high}.
            "bootstrap_ci": json.loads(s.bootstrap.to_json(orient="index")),
            "replicates_used": s.replicates_used,
            "replicates_not_estimable": s.replicates_not_estimable,
        }
    return out


def save_run(con: psycopg.Connection, reports: list[Report], started_at: datetime) -> int:
    source = con.execute("SELECT cdm_source_name FROM cdm.cdm_source").fetchone()
    persons = con.execute("SELECT count(*) FROM cdm.person").fetchone()[0]
    run_id = con.execute(
        "INSERT INTO tte.run (started_at, finished_at, cdm_source_name, persons)"
        " VALUES (%s, %s, %s, %s) RETURNING run_id",
        [started_at, datetime.now(UTC), source[0] if source else None, persons],
    ).fetchone()[0]
    with con.cursor() as cur:
        cur.executemany(
            "INSERT INTO tte.report VALUES (%s, %s, %s, %s)",
            [(run_id, r.protocol.id, r.protocol.name, Jsonb(report_json(r))) for r in reports],
        )
    return run_id
