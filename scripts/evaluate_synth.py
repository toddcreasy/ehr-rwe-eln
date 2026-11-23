"""Score every synthetic release for fidelity and utility, store each report, and print them
next to the noise floor.

Usage: uv run python scripts/evaluate_synth.py

Rebuilds each release's source and split from the spec stored with it, so it must run against
the database the release was made from. The noise floor is the same report for the real
holdout against the real training set: no release can be expected to do better.

Every privacy report is also checked for drift toward leakage, and any release past the
halfway mark is listed for review (scripts/withdraw_release.py withdraws one). Specs with
subgroup columns also get fidelity within each group (race, sex, age bins), stored
in the fidelity report. Releases with a holdout also get a privacy report: three attacks, read
against the same attacks on a plain copy of the training data. Releases of a module 3 trial's
analysis table also get a trial report: the trial rerun on the release, and on 20 more draws
of its method and epsilon (a few minutes for the VAE).
"""

from ehr_rwe_eln.config import DatabaseSettings
from ehr_rwe_eln.omop import connect_omop
from ehr_rwe_eln.synth import aim, bayes_net, mst, vae
from ehr_rwe_eln.synth.distribution import privacy_flags
from ehr_rwe_eln.synth.fidelity import fidelity_report, subgroup_report, utility_auc
from ehr_rwe_eln.synth.parity import load_trial, parity_report, repeated_draws, trial_estimate
from ehr_rwe_eln.synth.privacy import privacy_report
from ehr_rwe_eln.synth.release import load_release, save_report
from ehr_rwe_eln.synth.source import build_source, split
from ehr_rwe_eln.synth.spec import SPECS, Spec, load_spec


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


def subgroup_row(label: str, report: dict, worst: int = 3) -> str:
    rows = [r for r in report["subgroups"] if r.get("excess") is not None]
    if not rows:
        return f"{label:<24}no noise floor (no holdout)"
    rows.sort(key=lambda r: r["excess"], reverse=True)
    return f"{label:<24}" + "; ".join(
        f"{r['column']} {r['group']} {r['excess']:+.3f}, x{r['share_ratio']:.2f}"
        for r in rows[:worst]
    )


def privacy_row(label: str, report: dict) -> str:
    dcr = report["distance_to_closest_record"]
    attrs = report["attribute_inference"]
    return (
        f"{label:<24}{dcr['closer_to_member']:>9.1%}{dcr['exact_match_member']:>9.1%}"
        f"{dcr['exact_match_non_member']:>9.1%}{report['membership_inference']['auc']:>9.3f}"
        f"{attrs['gap_mean']:>+10.1%}{attrs['gap_max']:>+9.1%}  {attrs['gap_worst']}"
    )


def main() -> None:
    omop, cdm = connect_omop()
    with DatabaseSettings().connect() as con:
        releases = con.execute(
            "SELECT release_id, method, epsilon, spec, withdrawn_at FROM synth.release"
            " ORDER BY release_id"
        ).fetchall()
        # Every spec's source is read first, so the Redshift session (billed while open) ends
        # before the hours of scoring and trial redraws.
        tables = {}
        with omop:
            for *_, spec_json, _ in releases:
                spec = Spec.model_validate(spec_json)
                key = spec.model_dump_json(
                    include={"name", "columns", "holdout_fraction", "protocol"}
                )
                if key not in tables:
                    tables[key] = split(build_source(omop, spec, cdm), spec)
        sources, trial_lines, privacy_lines, summaries, subgroup_lines = {}, [], [], [], []
        review = []
        print(
            f"{'':<24}{'column TVD':>14}{'pair TVD':>14}  {'worst pair':<34}{'corr gap':>7}"
            f"   TSTR / TRTR AUC\n{'':<24}{'mean':>7}{'max':>7}{'mean':>7}{'max':>7}"
        )
        for release_id, method, epsilon, spec_json, withdrawn_at in releases:
            spec = Spec.model_validate(spec_json)
            key = spec.model_dump_json(include={"name", "columns", "holdout_fraction", "protocol"})
            if key not in sources:
                train, holdout = tables[key]
                target = spec.utility_target
                trtr = utility_auc(train, holdout, spec.columns, target) if target else None
                floor = None
                if len(holdout):
                    floor = fidelity_report(train, holdout, spec.columns)["summary"]
                    print(row(f"{spec.name}: noise floor", {"summary": floor}, trtr, None))
                else:
                    print(f"{spec.name}: no holdout, so no noise floor")
                sources[key] = (train, holdout, trtr, floor)
            train, holdout, trtr, floor = sources[key]
            synthetic = load_release(con, release_id)
            report = fidelity_report(train, synthetic, spec.columns)
            # Stored with each report, so the report can be read on its own.
            report["noise_floor"] = floor
            if spec.utility_target:
                tstr = utility_auc(synthetic, holdout, spec.columns, spec.utility_target)
                report["utility"] = {
                    "target": spec.utility_target,
                    "tstr_auc": tstr,
                    "trtr_auc": trtr,
                }
            else:
                tstr = None
            # Subgroups choose how a release is read, not how it was made, so every release is
            # read with the current spec file's subgroups when there is one, older releases
            # included; the list stored with the release is the fallback.
            shipped = SPECS / f"{spec.name}.yaml"
            by = load_spec(shipped).subgroups if shipped.exists() else spec.subgroups
            names = {c.name for c in spec.columns}
            by = [e for e in by if set([e] if isinstance(e, str) else e) <= names]
            if by:
                report["subgroups"] = subgroup_report(
                    train, holdout, synthetic, spec.columns, by, spec.utility_target
                )
                subgroup_lines.append(subgroup_row(f"{release_id}: {method} {epsilon:g}", report))
            save_report(con, release_id, "fidelity", report)
            con.commit()
            print(row(f"{release_id}: {method} {epsilon:g}", report, tstr, trtr))
            if len(holdout) and not spec.attacks_allowed:
                privacy_lines.append(
                    f"{release_id}: {method} {epsilon:g}: not run; controlled source without"
                    " attack_approval"
                )
            elif len(holdout):
                copy_key = ("copy", key)
                if copy_key not in sources:
                    sources[copy_key] = privacy_report(train, holdout, train, spec)
                    privacy_lines.append(privacy_row(f"{spec.name}: copy", sources[copy_key]))
                copied = sources[copy_key]
                privacy = privacy_report(train, holdout, synthetic, spec)
                # The same attacks on a copy of the training data, what real leakage looks like.
                privacy["copy_of_training_data"] = {
                    "distance_to_closest_record": copied["distance_to_closest_record"],
                    "membership_inference": copied["membership_inference"],
                    "attribute_gap_mean": copied["attribute_inference"]["gap_mean"],
                    "attribute_gap_max": copied["attribute_inference"]["gap_max"],
                }
                save_report(con, release_id, "privacy", privacy)
                status = " (withdrawn)" if withdrawn_at else ""
                for flag in privacy_flags(privacy):
                    review.append(f"{release_id}: {method} {epsilon:g}{status}: {flag}")
                con.commit()
                privacy_lines.append(privacy_row(f"{release_id}: {method} {epsilon:g}", privacy))
                summaries.append(f"{release_id}: {method} {epsilon:g}. {privacy['summary']}")
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
                module = {"vae": vae, "mst": mst, "aim": aim}.get(method, bayes_net)
                draws = repeated_draws(train, spec, release, protocol, module.synthesize, real)
                trial = parity_report(real, trial_estimate(synthetic, protocol), draws)
                save_report(con, release_id, "trial", trial)
                con.commit()
                trial_lines.append(trial_row(f"{release_id}: {method} {epsilon:g}", trial))
        print(
            "\nReview after release (privacy checks more than halfway from chance to a copy of"
            " the training data; consider scripts/withdraw_release.py):\n"
            + ("\n".join(review) if review else "none")
        )
        if subgroup_lines:
            print(
                "\nSubgroups furthest past their noise floor (column TVD minus floor; share of"
                " the release over share of the real data):\n" + "\n".join(subgroup_lines)
            )
        if privacy_lines:
            print(
                f"\n{'':<24}{'nearer':>9}{'exact match':>18}{'member':>9}"
                f"{'attribute gap':>19}\n{'':<24}{'member':>9}{'member':>9}{'non':>9}"
                f"{'AUC':>9}{'mean':>10}{'max':>9}  worst"
            )
            print("\n".join(privacy_lines))
            print("\n" + "\n\n".join(summaries))
        if trial_lines:
            print(
                f"\n{'':<24}{'events':>7}  {'release HR (95% CI)':<24}{'estimable':>9}{'covers':>9}"
                f"{'spurious':>11}  median HR over draws (10th to 90th)"
            )
            print("\n".join(trial_lines))


if __name__ == "__main__":
    main()
