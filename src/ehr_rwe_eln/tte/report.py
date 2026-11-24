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


def build_report(con, protocol: Protocol, cdm: str = "cdm") -> Report:
    """con is a psycopg connection or a lake.RedshiftSession; cdm is the OMOP tables' prefix."""
    return report_from(protocol, *read_trial(con, protocol, cdm))


def read_trial(con, protocol: Protocol, cdm: str = "cdm"):
    """Every OMOP read a report needs: the analysis table and each negative control's, so a
    caller can end the Redshift session (billed while open) before the fits and the bootstrap."""
    attrition, table = _read(con, protocol, cdm)
    controls = []
    for outcome in protocol.negative_controls:
        control = _control(protocol, outcome)
        controls.append((control, _read(con, control, cdm)[1]))
    return attrition, table, controls


def report_from(protocol: Protocol, attrition, table: pd.DataFrame, controls) -> Report:
    """The report from read_trial's tables; reads nothing."""
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
    try:
        report.propensity = fit_propensity(table, protocol)
    except NotEstimable as exc:
        report.not_estimable = str(exc)
        return report
    report.survival = analyze(table, protocol)
    report.negative_controls = [_control_result(c, t) for c, t in controls]
    return report


def negative_control(
    con, protocol: Protocol, outcome: Outcome, cdm: str = "cdm"
) -> NegativeControl:
    """The protocol rerun with this outcome: its own eligibility (no prior outcome), propensity
    weights, and weighted Cox model. No bootstrap; the robust interval is enough to flag it."""
    control = _control(protocol, outcome)
    return _control_result(control, _read(con, control, cdm)[1])


def _read(con, protocol: Protocol, cdm: str):
    attrition, table = build_analysis_table(con, protocol, cdm)
    return attrition, add_covariates(con, protocol, table, cdm)


def _control(protocol: Protocol, outcome: Outcome) -> Protocol:
    return protocol.model_copy(
        update={
            "outcome": outcome,
            "analysis": protocol.analysis.model_copy(update={"bootstrap_replicates": 0}),
        }
    )


def _control_result(control: Protocol, table: pd.DataFrame) -> NegativeControl:
    result = NegativeControl(control.outcome.name, len(table), int(table.event.sum()))
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


def omop_summary(con, cdm: str = "cdm") -> tuple[str | None, int]:
    """The OMOP source's name and person count, recorded with each run."""
    source = con.execute(f"SELECT cdm_source_name FROM {cdm}.cdm_source").fetchone()
    persons = con.execute(f"SELECT count(*) FROM {cdm}.person").fetchone()[0]
    return (source[0] if source else None), persons


def save_run(
    con: psycopg.Connection,
    reports: list[Report],
    started_at: datetime,
    source: str | None,
    persons: int,
) -> int:
    """Store the run in the tte schema (Postgres). source and persons come from omop_summary."""
    run_id = con.execute(
        "INSERT INTO tte.run (started_at, finished_at, cdm_source_name, persons)"
        " VALUES (%s, %s, %s, %s) RETURNING run_id",
        [started_at, datetime.now(UTC), source, persons],
    ).fetchone()[0]
    with con.cursor() as cur:
        cur.executemany(
            "INSERT INTO tte.report VALUES (%s, %s, %s, %s)",
            [(run_id, r.protocol.id, r.protocol.name, Jsonb(report_json(r))) for r in reports],
        )
    return run_id
