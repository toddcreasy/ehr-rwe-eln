"""Score every synthetic release for fidelity and utility, store each report, and print them
next to the noise floor.

Usage: DB_NAME=ehr_rwe_eln_tte uv run python scripts/evaluate_synth.py

Rebuilds each release's source and split from the spec stored with it, so it must run against
the database the release was made from. The noise floor is the same report for the real
holdout against the real training set: no release can be expected to do better.

Releases of a module 4 trial's analysis table also get a trial report: the trial rerun on the
release, and on 20 more draws of its method and epsilon (a few minutes for the VAE).
"""

from ehr_rwe_eln.config import DatabaseSettings
from ehr_rwe_eln.synth import bayes_net, vae
from ehr_rwe_eln.synth.fidelity import fidelity_report, utility_auc
from ehr_rwe_eln.synth.parity import load_trial, parity_report, repeated_draws, trial_estimate
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


def interval(estimate: dict) -> str:
    if estimate["hazard_ratio"] is None or not estimate["robust_ci"]:
        return "not estimable"
    low, high = estimate["robust_ci"]
    return f"{estimate['hazard_ratio']:.2f} ({low:.2f} to {high:.2f})"


def trial_row(label: str, report: dict) -> str:
    r = report["repeated"]
    spread = r["hazard_ratio_10th_90th"]
    median = (
        f"{r['hazard_ratio_median']:.2f} ({spread[0]:.2f} to {spread[1]:.2f})" if spread else "-"
    )
    events = report["release"]["events_treated"] + report["release"]["events_comparator"]
    return (
        f"{label:<24}{events:>7}  {interval(report['release']):<24}{r['estimable']:>9.0%}"
        f"{r['covers_real']:>9.0%}{r['spurious_effect']:>11.0%}  {median}"
    )


def main() -> None:
    with DatabaseSettings().connect() as con:
        releases = con.execute(
            "SELECT release_id, method, epsilon, spec FROM synth.release ORDER BY release_id"
        ).fetchall()
        sources, trial_lines = {}, []
        print(
            f"{'':<24}{'column TVD':>14}{'pair TVD':>14}  {'worst pair':<34}{'corr gap':>7}"
            f"   TSTR / TRTR AUC\n{'':<24}{'mean':>7}{'max':>7}{'mean':>7}{'max':>7}"
        )
        for release_id, method, epsilon, spec_json in releases:
            spec = Spec.model_validate(spec_json)
            key = spec.model_dump_json(include={"name", "columns", "holdout_fraction", "protocol"})
            if key not in sources:
                train, holdout = split(build_source(con, spec), spec)
                target = spec.utility_target
                trtr = utility_auc(train, holdout, spec.columns, target) if target else None
                sources[key] = (train, holdout, trtr)
                if len(holdout):
                    floor = fidelity_report(train, holdout, spec.columns)
                    print(row(f"{spec.name}: noise floor", floor, trtr, None))
                else:
                    print(f"{spec.name}: no holdout, so no noise floor")
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
            if spec.protocol is not None:
                protocol = load_trial(spec.protocol)
                real_key = ("trial", key)
                if real_key not in sources:
                    sources[real_key] = trial_estimate(train, protocol)
                    real = sources[real_key]
                    events = real["events_treated"] + real["events_comparator"]
                    trial_lines.append(f"{spec.name}, real:")
                    trial_lines.append(f"{'real':<24}{events:>7}  {interval(real)}")
                real = sources[real_key]
                release = next(
                    r for r in spec.releases if (r.method, r.epsilon) == (method, epsilon)
                )
                module = vae if method == "vae" else bayes_net
                draws = repeated_draws(train, spec, release, protocol, module.synthesize, real)
                trial = parity_report(real, trial_estimate(synthetic, protocol), draws)
                save_report(con, release_id, "trial", trial)
                con.commit()
                trial_lines.append(trial_row(f"{release_id}: {method} {epsilon:g}", trial))
        if trial_lines:
            print(
                f"\n{'':<24}{'events':>7}  {'release HR (95% CI)':<24}{'estimable':>9}{'covers':>9}"
                f"{'spurious':>11}  median HR over draws (10th to 90th)"
            )
            print("\n".join(trial_lines))


if __name__ == "__main__":
    main()
