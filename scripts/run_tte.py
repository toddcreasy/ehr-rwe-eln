"""Run each target trial protocol: analysis table, propensity score, and survival estimates.
Prints the attrition, arms, balance, positivity diagnostics, risks, and hazard ratio.

Usage: uv run python scripts/run_tte.py
Module 4's larger population: DB_NAME=ehr_rwe_eln_tte uv run python scripts/run_tte.py

Demonstration on synthetic data only; no clinical claims.
"""

from ehr_rwe_eln.config import DatabaseSettings
from ehr_rwe_eln.tte.cohort import build_analysis_table
from ehr_rwe_eln.tte.covariates import add_covariates
from ehr_rwe_eln.tte.propensity import NotEstimable, fit_propensity
from ehr_rwe_eln.tte.protocol import PROTOCOLS, load_protocol
from ehr_rwe_eln.tte.survival import analyze


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
            table = add_covariates(con, protocol, table)
            try:
                result = fit_propensity(table, protocol)
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
            survival = analyze(table, protocol)
            ci = survival.bootstrap
            print("  risk by day, crude / weighted; 95% bootstrap CI for the weighted difference:")
            crude = survival.crude.risks.set_index("day")
            for row in survival.weighted.risks.itertuples():
                low, high = ci.loc[f"risk_difference_{row.day}"]
                print(
                    f"    day {row.day:>5}: {strategies.treatment.name}"
                    f" {crude.loc[row.day, 'risk_treatment']:.1%} / {row.risk_treatment:.1%},"
                    f" {strategies.comparator.name}"
                    f" {crude.loc[row.day, 'risk_comparator']:.1%} / {row.risk_comparator:.1%},"
                    f" difference {row.risk_difference:+.1%} ({low:+.1%} to {high:+.1%})"
                )
            hr = survival.weighted.hazard_ratio
            if hr is None:
                print("  hazard ratio: none, an arm has no events")
            else:
                robust, boot = survival.hazard_ratio_robust_ci, ci.loc["hazard_ratio"]
                crude_hr = survival.crude.hazard_ratio
                print(
                    f"  hazard ratio {hr:.2f} (robust {robust[0]:.2f} to {robust[1]:.2f};"
                    f" bootstrap {boot['low']:.2f} to {boot['high']:.2f});"
                    f" crude {'none' if crude_hr is None else f'{crude_hr:.2f}'}"
                )
            print(
                f"  bootstrap: {survival.replicates_used} replicates,"
                f" {survival.replicates_not_estimable} not estimable"
            )
            print()
        con.rollback()


if __name__ == "__main__":
    main()
