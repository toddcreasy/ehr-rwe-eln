"""Person-period data for a per-protocol estimate with TrialEmulation (r/run_trialemulation.R).

The intention-to-treat analysis counts everyone in the arm they started. Per-protocol asks what
happens to people who keep to their strategy, so follow-up ends when someone deviates, and the
people who stay are weighted to stand in for those who left (inverse probability of censoring
weights; TrialEmulation fits the models).

Follow-up is cut into PERIOD_DAYS periods from time zero. Each row is one person in one period:
whether they are still on their strategy (treatment), whether the outcome happened in it, and the
covariates. Two definitions of deviating:

- strict: stopping the assigned drug, or starting the other arm's drug. Synthea adds the second
  drug about 30 days in when blood pressure stays high, so this compares the two drugs alone.
- lenient: stopping the assigned drug only; adding the other is allowed.

Stopping means a gap in coverage longer than GRACE_DAYS: coverage runs from time zero through each
fill's end date, chaining fills that start within GRACE_DAYS of the last covered day.

The treatment column is the arm until the period a deviation falls in, then the other value, which
TrialEmulation reads as a switch and censors there. A deviation inside period 0 is moved to
period 1, since period 0's value is what TrialEmulation takes as the assigned strategy.

Time-varying covariates (<name>_now): each measurement covariate's latest value before the period
starts, so the switch model can see, say, blood pressure that stayed high. Until a new value
arrives it is the baseline value.
"""

import numpy as np
import pandas as pd

from ehr_rwe_eln.tte.cohort import build_analysis_table, concept_set_sql
from ehr_rwe_eln.tte.covariates import add_covariates
from ehr_rwe_eln.tte.propensity import design_matrix
from ehr_rwe_eln.tte.protocol import Protocol

PERIOD_DAYS = 30
GRACE_DAYS = 30


def coverage_end(time_zero, fills: pd.DataFrame) -> pd.Timestamp:
    """The last covered day of the assigned drug's first continuous run from time zero. fills has
    start and stop dates, sorted by start."""
    covered = pd.Timestamp(time_zero)
    for start, stop in zip(fills["start"], fills["stop"], strict=True):
        if (pd.Timestamp(start) - covered).days > GRACE_DAYS:
            break
        covered = max(covered, pd.Timestamp(stop))
    return covered


def deviations(table: pd.DataFrame, fills: pd.DataFrame) -> pd.DataFrame:
    """Per person: stop_day (first day off the assigned drug after the grace period) and
    switch_day (first start of the other arm's drug), both in days from time zero, NaN when it
    doesn't happen before follow-up ends. fills: person_id, arm the drug belongs to, start, stop."""
    rows = []
    for r in table.itertuples():
        mine = fills[(fills.person_id == r.person_id) & (fills.arm == r.arm)]
        mine = mine[mine.stop >= r.time_zero].sort_values("start")
        other = fills[(fills.person_id == r.person_id) & (fills.arm != r.arm)]
        other = other[other.start > r.time_zero]
        time_zero = pd.Timestamp(r.time_zero)
        last = (pd.Timestamp(r.censor_date) - time_zero).days
        stop = (coverage_end(r.time_zero, mine) - time_zero).days + GRACE_DAYS
        switch = (pd.Timestamp(other.start.min()) - time_zero).days if len(other) else np.nan
        rows.append(
            (
                r.person_id,
                stop if stop <= last else np.nan,
                switch if switch <= last else np.nan,
            )
        )
    return pd.DataFrame(rows, columns=["person_id", "stop_day", "switch_day"])


def _switch_period(*days: float) -> float:
    """The period the earliest of these deviation days falls in; NaN if none happened."""
    happened = [d for d in days if not np.isnan(d)]
    return max(1, int(min(happened)) // PERIOD_DAYS) if happened else np.nan


def person_periods(
    table: pd.DataFrame, x: pd.DataFrame, deviation: pd.DataFrame, measured: pd.DataFrame
) -> pd.DataFrame:
    """One row per person per period. table: the analysis table with covariates; x: the design
    matrix (baseline covariates); measured: person_id, name, day, value for the time-varying
    measurements after time zero."""
    base = pd.concat([table[["person_id", "arm", "event", "days"]], x], axis=1)
    base = base.merge(deviation, on="person_id")
    frames = []
    for r in base.itertuples(index=False):
        periods = np.arange(int(r.days) // PERIOD_DAYS + 1)
        strict = _switch_period(r.stop_day, r.switch_day)
        lenient = _switch_period(r.stop_day)
        frame = pd.DataFrame(
            {
                "id": r.person_id,
                "period": periods,
                "eligible": (periods == 0).astype(int),
                "treatment_strict": np.where(periods >= strict, 1 - r.arm, r.arm)
                if not np.isnan(strict)
                else r.arm,
                "treatment_lenient": np.where(periods >= lenient, 1 - r.arm, r.arm)
                if not np.isnan(lenient)
                else r.arm,
                "outcome": ((periods == periods[-1]) & (r.event == 1)).astype(int),
            }
        )
        frames.append(frame)
    out = pd.concat(frames, ignore_index=True)
    out = out.merge(base[["person_id", *x.columns]].rename(columns={"person_id": "id"}), on="id")

    for name in measured["name"].unique():
        values = measured[measured["name"] == name].rename(columns={"person_id": "id"})
        starts = out[["id", "period"]].assign(day=out["period"] * PERIOD_DAYS)
        # The latest value strictly before the period starts: a value on day d is known from
        # day d + 1.
        latest = pd.merge_asof(
            starts.sort_values("day"),
            values.assign(day=values["day"] + 1).sort_values("day")[["id", "day", "value"]],
            on="day",
            by="id",
            direction="backward",
        )
        out = out.merge(
            latest[["id", "period", "value"]].rename(columns={"value": f"{name}_now"}),
            on=["id", "period"],
            how="left",
        )
        out[f"{name}_now"] = out[f"{name}_now"].fillna(out[name])
    return out.sort_values(["id", "period"]).reset_index(drop=True)


def build_person_periods(con, protocol: Protocol, cdm: str = "cdm") -> tuple[pd.DataFrame, dict]:
    """The protocol's person-period table and a description of its columns for the R script.
    con is a psycopg connection or a lake.RedshiftSession, as in tte/cohort.py."""
    _, table = build_analysis_table(con, protocol, cdm)
    table = add_covariates(con, protocol, table, cdm)  # leaves the tte_eligible temp table
    x, dropped = design_matrix(table, protocol)
    x = x.set_index(table.index)

    strategies = protocol.strategies
    treatment = concept_set_sql(strategies.treatment.drugs, cdm)
    comparator = concept_set_sql(strategies.comparator.drugs, cdm)
    # Every value in the SQL is an int() or a date the database returned; cdm is a fixed prefix.
    fills = pd.DataFrame(
        con.execute(
            f"""
            WITH treatment AS ({treatment}), comparator AS ({comparator})
            SELECT de.person_id,
                   CASE WHEN t.concept_id IS NOT NULL THEN 1 ELSE 0 END AS arm,
                   de.drug_exposure_start_date AS start,
                   greatest(de.drug_exposure_end_date, de.drug_exposure_start_date) AS stop
            FROM {cdm}.drug_exposure de
            JOIN tte_eligible e ON e.person_id = de.person_id
            LEFT JOIN treatment t ON t.concept_id = de.drug_concept_id
            LEFT JOIN comparator c ON c.concept_id = de.drug_concept_id
            WHERE (t.concept_id IS NOT NULL OR c.concept_id IS NOT NULL)
              AND de.drug_exposure_start_date >= e.time_zero - {int(GRACE_DAYS)}
            """  # noqa: S608
        ).fetchall(),
        columns=["person_id", "arm", "start", "stop"],
    )
    deviation = deviations(table, fills)

    measured_frames = []
    for covariate in protocol.covariates.measurements:
        if covariate.name not in x.columns:
            continue
        concepts = concept_set_sql(covariate.measurements, cdm)
        rows = con.execute(
            f"""
            WITH concepts AS ({concepts})
            SELECT m.person_id, m.measurement_date - e.time_zero AS day, m.value_as_number
            FROM {cdm}.measurement m
            JOIN tte_eligible e ON e.person_id = m.person_id
            JOIN concepts c ON c.concept_id = m.measurement_concept_id
            WHERE m.measurement_date >= e.time_zero
              AND m.measurement_date <= e.time_zero + {int(protocol.follow_up.max_days)}
              AND m.value_as_number IS NOT NULL
            """  # noqa: S608
        ).fetchall()
        measured_frames.append(
            pd.DataFrame(rows, columns=["person_id", "day", "value"]).assign(name=covariate.name)
        )
    measured = (
        pd.concat(measured_frames, ignore_index=True)
        if measured_frames
        else pd.DataFrame(columns=["person_id", "day", "value", "name"])
    )
    measured["day"] = measured["day"].astype(int)
    measured["value"] = measured["value"].astype(float)

    out = person_periods(table, x, deviation, measured)
    arms = {1: strategies.treatment.name, 0: strategies.comparator.name}
    by_arm = table.merge(deviation, on="person_id").groupby("arm")
    description = {
        "protocol": protocol.name,
        "period_days": PERIOD_DAYS,
        "grace_days": GRACE_DAYS,
        "arms": arms,
        "baseline_covariates": list(x.columns),
        "time_varying_covariates": [c for c in out.columns if c.endswith("_now")],
        "covariates_dropped": dropped,
        "persons": {arms[a]: int(len(g)) for a, g in by_arm},
        "stopped": {arms[a]: int(g.stop_day.notna().sum()) for a, g in by_arm},
        "started_other_drug": {arms[a]: int(g.switch_day.notna().sum()) for a, g in by_arm},
        "events": {arms[a]: int(g.event.sum()) for a, g in by_arm},
    }
    return out, description
