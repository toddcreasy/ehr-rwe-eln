"""Score every synthetic release for fidelity and utility, store each report, and print them
next to the noise floor.

Usage: DB_NAME=ehr_rwe_eln_tte uv run python scripts/evaluate_synth.py

Rebuilds each release's source and split from the spec stored with it, so it must run against
the database the release was made from. The noise floor is the same report for the real
holdout against the real training set: no release can be expected to do better.
"""

from ehr_rwe_eln.config import DatabaseSettings
from ehr_rwe_eln.synth.fidelity import fidelity_report, utility_auc
from ehr_rwe_eln.synth.release import load_release, save_report
from ehr_rwe_eln.synth.source import build_source, split
from ehr_rwe_eln.synth.spec import Spec


def row(label: str, report: dict, tstr: float | None, trtr: float | None) -> str:
    s = report["summary"]
    auc = f"{tstr:.3f}" if tstr is not None else "  n/a"
    floor = f" / {trtr:.3f}" if trtr is not None else ""
    worst_pair = " x ".join(s["pair_tvd_worst"])
    gap = s["correlation_gap_mean"]
    gap_text = f"{gap:>7.3f}" if gap is not None else f"{'n/a':>7}"
    return (
        f"{label:<24}{s['column_tvd_mean']:>7.3f}{s['column_tvd_max']:>7.3f}"
        f"{s['pair_tvd_mean']:>7.3f}{s['pair_tvd_max']:>7.3f}  {worst_pair:<34}"
        f"{gap_text}   {auc}{floor}"
    )


def main() -> None:
    with DatabaseSettings().connect() as con:
        releases = con.execute(
            "SELECT release_id, method, epsilon, spec FROM synth.release ORDER BY release_id"
        ).fetchall()
        sources = {}
        print(
            f"{'':<24}{'column TVD':>14}{'pair TVD':>14}  {'worst pair':<34}{'corr gap':>7}"
            f"   TSTR / TRTR AUC\n{'':<24}{'mean':>7}{'max':>7}{'mean':>7}{'max':>7}"
        )
        for release_id, method, epsilon, spec_json in releases:
            spec = Spec.model_validate(spec_json)
            key = spec.model_dump_json(include={"name", "columns", "holdout_fraction"})
            if key not in sources:
                train, holdout = split(build_source(con, spec), spec)
                target = spec.utility_target
                trtr = utility_auc(train, holdout, spec.columns, target) if target else None
                sources[key] = (train, holdout, trtr)
                floor = fidelity_report(train, holdout, spec.columns)
                print(row(f"{spec.name}: noise floor", floor, trtr, None))
            train, holdout, trtr = sources[key]
            synthetic = load_release(con, release_id)
            report = fidelity_report(train, synthetic, spec.columns)
            if spec.utility_target:
                tstr = utility_auc(synthetic, holdout, spec.columns, spec.utility_target)
                report["utility"] = {
                    "target": spec.utility_target,
                    "tstr_auc": tstr,
                    "trtr_auc": trtr,
                }
            else:
                tstr = None
            save_report(con, release_id, "fidelity", report)
            con.commit()
            print(row(f"{release_id}: {method} {epsilon:g}", report, tstr, trtr))


if __name__ == "__main__":
    main()
