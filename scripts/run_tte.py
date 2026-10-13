"""Build each target trial protocol's analysis table, fit its propensity score, and print the
attrition, arms, balance, and positivity diagnostics.

Usage: uv run python scripts/run_tte.py
Module 4's larger population: DB_NAME=ehr_rwe_eln_tte uv run python scripts/run_tte.py

Demonstration on synthetic data only; no clinical claims.
"""

from ehr_rwe_eln.config import DatabaseSettings
from ehr_rwe_eln.tte.cohort import build_analysis_table
from ehr_rwe_eln.tte.covariates import add_covariates
from ehr_rwe_eln.tte.propensity import NotEstimable, fit_propensity
from ehr_rwe_eln.tte.protocol import PROTOCOLS, load_protocol


def main() -> None:
    with DatabaseSettings().connect() as con:
        for path in sorted(PROTOCOLS.glob("*.yaml")):
            protocol = load_protocol(path)
            attrition, table = build_analysis_table(con, protocol)
            print(f"{protocol.id}: {protocol.name}")
            for label, persons in attrition:
                print(f"  {persons:>8,}  {label}")
            strategies = protocol.strategies
            for arm, strategy in ((1, strategies.treatment), (0, strategies.comparator)):
                rows = table[table.arm == arm]
                print(
                    f"  {strategy.name:<12} {len(rows):>6,} persons  {rows.event.sum():>5,} events"
                    f"  median follow-up {rows.days.median():.0f} days"
                )
            try:
                result = fit_propensity(add_covariates(con, protocol, table), protocol)
            except NotEstimable as exc:
                print(f"  NOT ESTIMABLE: {exc}\n")
                continue
            balance, d = result.balance, result.diagnostics
            print(
                f"  largest |SMD| {balance.smd_before.abs().max():.2f} before weighting,"
                f" {balance.smd_after.abs().max():.2f} after;"
                f" {d['covariates_unbalanced_after']} covariates at 0.1 or more after"
            )
            print(
                f"  propensity outside 0.05-0.95: {d['share_ps_outside_0.05_0.95']:.0%};"
                f" weights {d['weight_min']:.2f} to {d['weight_max']:.2f};"
                f" effective n {d['effective_n_treatment']:.0f}"
                f" vs {d['effective_n_comparator']:.0f};"
                f" model converged: {d['model_converged']}"
            )
            print()
        con.rollback()


if __name__ == "__main__":
    main()
