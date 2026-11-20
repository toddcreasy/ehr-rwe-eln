"""Run each target trial protocol: analysis table, propensity score, and survival estimates.
Prints each bias report: attrition, arms, balance, positivity diagnostics, risks, hazard ratio,
and negative controls. Stores the run in the tte schema for the /tte page.

Usage: uv run python scripts/run_tte.py

Reads OMOP from the lake through Redshift (OMOP_SOURCE=staging reads the staging Postgres
instead) and stores the run in Postgres, which needs migrations applied (uv run alembic upgrade
head).

Demonstration on synthetic data only; no clinical claims.
"""

from datetime import UTC, datetime

from ehr_rwe_eln.cohort.lake import connect_omop
from ehr_rwe_eln.config import DatabaseSettings
from ehr_rwe_eln.tte.protocol import PROTOCOLS, load_protocol
from ehr_rwe_eln.tte.report import build_report, omop_summary, save_run


def main() -> None:
    started_at = datetime.now(UTC)
    reports = []
    omop, cdm = connect_omop()
    with omop:
        source, persons = omop_summary(omop, cdm)
        for path in sorted(PROTOCOLS.glob("*.yaml")):
            protocol = load_protocol(path)
            report = build_report(omop, protocol, cdm)
            reports.append(report)
            print(f"{protocol.id}: {protocol.name}")
            for label, persons in report.attrition:
                print(f"  {persons:>8,}  {label}")
            for arm in report.arms:
                print(
                    f"  {arm.name:<12} {arm.persons:>6,} persons  {arm.events:>5,} events"
                    f"  median follow-up {arm.median_follow_up_days:.0f} days"
                )
            if report.not_estimable:
                print(f"  NOT ESTIMABLE: {report.not_estimable}\n")
                continue
            strategies = protocol.strategies
            balance, d = report.propensity.balance, report.propensity.diagnostics
            print(
                f"  largest |SMD| {balance.smd_before.abs().max():.2f} before weighting,"
                f" {balance.smd_after.abs().max():.2f} after;"
                f" {d['covariates_unbalanced_after']} covariates at 0.1 or more after"
            )
            print(
                f"  propensity outside 0.05-0.95: {d['share_ps_outside_0.05_0.95']:.0%};"
                f" weights {d['weight_min']:.2f} to {d['weight_max']:.2f};"
                f" effective n {d['effective_n_treatment']:.0f}"
                f" vs {d['effective_n_comparator']:.0f}"
            )
            for column, reason in d["covariates_dropped"].items():
                print(f"  dropped {column}: {reason}")
            survival = report.survival
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
            print("  negative controls, weighted hazard ratio (robust 95% CI), expected near 1:")
            for nc in report.negative_controls:
                head = f"    {nc.name:<20} {nc.persons:>6,} persons {nc.events:>5,} events  "
                if nc.not_estimable:
                    print(f"{head}not estimable: {nc.not_estimable}")
                elif nc.hazard_ratio is None:
                    print(f"{head}none, an arm has no events")
                else:
                    flag = "  EXCLUDES 1" if nc.excludes_null else ""
                    print(
                        f"{head}{nc.hazard_ratio:.2f}"
                        f" ({nc.robust_ci[0]:.2f} to {nc.robust_ci[1]:.2f}){flag}"
                    )
            print()
    with DatabaseSettings().connect() as con:
        run_id = save_run(con, reports, started_at, source, persons)
        con.commit()
    print(f"stored as tte run {run_id}")


if __name__ == "__main__":
    main()
