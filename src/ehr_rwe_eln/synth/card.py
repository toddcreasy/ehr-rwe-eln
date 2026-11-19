"""A data card per synthetic release: one Markdown page with what the release is, how it was
made, what it spent in privacy, how well it matches its source, what it risks, and what it is
fit for. Built only from the release record and its stored reports, so it can be regenerated
and checked against them.
"""

import math

from ehr_rwe_eln.synth.fidelity import MIN_GROUP
from ehr_rwe_eln.synth.privacy import signed_percent
from ehr_rwe_eln.synth.spec import Column, Spec


def _column(c: Column) -> str:
    if c.demographic:
        source = f"demographic: {c.demographic}"
    elif c.analysis:
        source = f"trial analysis column: {c.analysis}"
    else:
        kind = "condition" if c.condition else "drug" if c.drug else "measurement"
        concepts = c.condition or c.drug or c.measurement
        source = f"{kind}, concepts {', '.join(map(str, concepts.concept_ids))}"
    if c.numeric is not None:
        n = c.numeric
        domain = f"{n.low:g} to {n.high:g} in {n.bins} bins"
        if n.open_top:
            domain += f", the last {n.high - (n.high - n.low) / n.bins:g} or older"
        if c.missing_allowed:
            domain += ", or missing"
    else:
        domain = ", ".join(map(str, c.categories or []))
    parents = ", ".join(c.parents) or "none"
    return f"| {c.name} | {source} | {domain} | {parents} |"


def _spend(entry: dict) -> str:
    if entry.get("mechanism") == "dp_sgd":
        return (
            f"| DP-SGD training | epsilon {entry['epsilon']:.3f}, delta {entry['delta']:g};"
            f" noise multiplier {entry['noise_multiplier']:.2f}, gradient clip"
            f" {entry['max_grad_norm']:g}, {entry['steps']} steps |"
        )
    if entry.get("of"):
        return f"| Noisy {entry['of']} | epsilon {entry['epsilon']:.4f} |"
    return (
        f"| Histogram of {' x '.join(entry['columns'])} ({entry['cells']} cells) |"
        f" epsilon {entry['epsilon']:.4f} |"
    )


def _num(value, fmt: str = ".3f") -> str:
    return "n/a" if value is None else format(value, fmt)


def _fidelity(report: dict) -> list[str]:
    s, floor = report["summary"], report.get("noise_floor")
    rows = [
        ("Column TVD, mean", "column_tvd_mean"),
        ("Column TVD, max", "column_tvd_max"),
        ("Pair TVD, mean", "pair_tvd_mean"),
        ("Pair TVD, max", "pair_tvd_max"),
        ("Correlation gap, mean", "correlation_gap_mean"),
    ]
    out = [
        "## Fidelity",
        "",
        "Total variation distance (TVD) is 0 for identical distributions and 1 for no overlap."
        " Pairs compare the joint distribution of two columns, which shows whether relationships"
        " survived. The noise floor is the same measure between two real samples (the held-out"
        " people against the training people): no release can be expected to beat it.",
        "",
        "| Measure | This release | Noise floor |",
        "|---|---|---|",
    ]
    for label, key in rows:
        out.append(f"| {label} | {_num(s[key])} | {_num(floor[key]) if floor else 'n/a'} |")
    out += [
        "",
        f"Worst column: {s['column_tvd_worst']}. Worst pair: {' x '.join(s['pair_tvd_worst'])}.",
    ]
    if floor is None:
        out.append("This spec keeps no holdout, so there is no noise floor to read against.")
    utility = report.get("utility")
    if utility:
        out += [
            "",
            "## Utility",
            "",
            f"A logistic regression predicting {utility['target']} from the other columns, trained"
            f" on this release and tested on held-out real people, scores AUC"
            f" {_num(utility['tstr_auc'])}; trained on the real training data instead, it scores"
            f" {_num(utility['trtr_auc'])}. (AUC 0.5 is guessing, 1 is perfect.)",
        ]
    return out


# A group whose share of the release is off by more than this, and by more than sampling noise
# explains, is named under intended use.
SHARE_WARNING = 0.2
# The warning names at most this many, furthest off first.
WARN_AT_MOST = 5


def _single(rows: list[dict]) -> list[dict]:
    """Reported groups of one column; intersections are summarized separately."""
    return [r for r in rows if not r.get("suppressed") and " x " not in r["column"]]


def _misrepresented(rows: list[dict]) -> list[dict]:
    """Groups and intersection cells whose share of the release is off by more than
    SHARE_WARNING and by more than three standard errors of a count that size (about
    3 / sqrt(people)), so a small cell is not flagged for sampling noise alone."""
    flagged = [
        r
        for r in rows
        if not r.get("suppressed")
        and abs(r["share_ratio"] - 1) > max(SHARE_WARNING, 3 / math.sqrt(r["train_people"]))
    ]
    return sorted(flagged, key=lambda r: -abs(r["share_ratio"] - 1))


def _intersections(rows: list[dict]) -> list[str]:
    cells = [r for r in rows if " x " in r["column"]]
    if not cells:
        return []
    reported = [r for r in cells if not r["suppressed"]]
    names = ", ".join(dict.fromkeys(r["column"] for r in cells))
    out = [
        "",
        f"Intersections ({names}): {len(reported)} groups reported, {len(cells) - len(reported)}"
        f" left out under {MIN_GROUP} people.",
    ]
    ranked = sorted((r for r in reported if r["excess"] is not None), key=lambda r: -r["excess"])
    if ranked:
        out[-1] += (
            " Furthest past their floor: "
            + "; ".join(
                f"{r['group']} ({r['train_people']:,} people, {r['column_tvd_mean']:.3f} against"
                f" {r['noise_floor']:.3f}, share {r['share_ratio']:.2f})"
                for r in ranked[:5]
            )
            + "."
        )
    return out


def _subgroups(all_rows: list[dict], target: str | None) -> list[str]:
    rows = _single(all_rows)
    has_floor = any(r["noise_floor"] is not None for r in rows)
    out = [
        "## Fidelity by subgroup",
        "",
        "The same reading within each group: its share of this release against its share of the"
        " real data (1.00 is right, 0.80 is 20% too few), and the mean column TVD of the other"
        " columns within the group"
        + (
            ", next to the group's own noise floor (two real samples of a small group differ"
            " more, so its floor is higher)."
            if has_floor
            else ". This spec keeps no holdout, so there is no floor to read it against."
        )
        + f" Groups under {MIN_GROUP} people are left out.",
        "",
    ]
    ranked = sorted((r for r in rows if r["excess"] is not None), key=lambda r: -r["excess"])
    if ranked:
        out += [
            "Furthest past their floor: "
            + "; ".join(
                f"{r['column']} {r['group']} ({r['column_tvd_mean']:.3f} against"
                f" {r['noise_floor']:.3f})"
                for r in ranked[:3]
            )
            + ".",
            "",
        ]
    utility = target is not None and any("tstr_auc" in r for r in rows)
    header = "| Group | Training people | Share in release | Column TVD | Noise floor |"
    rule = "|---|---|---|---|---|"
    if utility:
        header += f" {target} AUC, release / real |"
        rule += "---|"
    out += [header, rule]
    for r in rows:
        line = (
            f"| {r['column']}: {r['group']} | {r['train_people']:,} | {r['share_ratio']:.2f}"
            f" | {_num(r['column_tvd_mean'])} | {_num(r['noise_floor'])} |"
        )
        if utility:
            line += f" {_num(r.get('tstr_auc'))} / {_num(r.get('trtr_auc'))} |"
        out.append(line)
    if utility:
        out += [
            "",
            f"The {target} models are trained on the whole release and on the whole real"
            f" training data, then scored on the group's held-out people; n/a means fewer than"
            f" {MIN_GROUP} of them on one side of the outcome.",
        ]
    return out + _intersections(all_rows)


def _trial(report: dict) -> list[str]:
    real, release, r = report["real"], report["release"], report["repeated"]

    def interval(e: dict) -> str:
        if e["hazard_ratio"] is None or not e["robust_ci"]:
            return "not estimable"
        return f"{e['hazard_ratio']:.2f} ({e['robust_ci'][0]:.2f} to {e['robust_ci'][1]:.2f})"

    spread = r["hazard_ratio_10th_90th"]
    out = [
        "## Trial parity",
        "",
        "The module 4 trial's own propensity-weighted Cox analysis, run on the real analysis"
        " table and on this release, and on further draws of the same method and epsilon (one"
        " draw varies like a fresh small sample).",
        "",
        "| | Events | Hazard ratio (95% CI) |",
        "|---|---|---|",
        f"| Real | {real['events_treated'] + real['events_comparator']} | {interval(real)} |",
        f"| This release | {release['events_treated'] + release['events_comparator']}"
        f" | {interval(release)} |",
        "",
        f"Over {r['draws']} more draws: {r['estimable']:.0%} estimable, {r['covers_real']:.0%}"
        f" with an interval covering the real hazard ratio, {r['spurious_effect']:.0%} showing"
        f" an effect the real data does not (an interval excluding 1). Median hazard ratio"
        + (
            f" {r['hazard_ratio_median']:.2f}, 10th to 90th percentile {spread[0]:.2f} to"
            f" {spread[1]:.2f}."
            if spread
            else " not available."
        ),
    ]
    return out


def _privacy(report: dict) -> list[str]:
    dcr, mia = report["distance_to_closest_record"], report["membership_inference"]
    attrs, copy = report["attribute_inference"], report["copy_of_training_data"]
    copy_dcr = copy["distance_to_closest_record"]
    return [
        "## Privacy risk",
        "",
        report["summary"],
        "",
        "| Attack | This release | Copy of the training data |",
        "|---|---|---|",
        f"| Synthetic rows nearer a training person than a held-out one (50% is no copying)"
        f" | {dcr['closer_to_member']:.1%} | {copy_dcr['closer_to_member']:.1%} |",
        f"| Exact matches, training / held-out people | {dcr['exact_match_member']:.1%} /"
        f" {dcr['exact_match_non_member']:.1%} | {copy_dcr['exact_match_member']:.1%} /"
        f" {copy_dcr['exact_match_non_member']:.1%} |",
        f"| Membership inference AUC (0.5 is a coin flip) | {mia['auc']:.3f}"
        f" | {copy['membership_inference']['auc']:.3f} |",
        f"| Attribute inference gap, mean / max | {signed_percent(attrs['gap_mean'])} /"
        f" {signed_percent(attrs['gap_max'])} | {signed_percent(copy['attribute_gap_mean'])} /"
        f" {signed_percent(copy['attribute_gap_max'])} |",
    ]


def render_card(release: dict, reports: dict[str, dict]) -> str:
    """release: a synth.release row as a dict. reports: its stored reports by kind."""
    spec = Spec.model_validate(release["spec"])
    method = {
        "bayes_net": "differentially private Bayesian network (noisy histograms of each column"
        " with its parents, then sampling)",
        "independent": "independent columns (a baseline: each column's noisy histogram alone,"
        " no relationships kept)",
        "vae": "variational autoencoder trained with differentially private SGD (Opacus)",
    }[release["method"]]
    trial = reports.get("trial")
    spurious = trial["repeated"]["spurious_effect"] if trial else None
    subgroups = reports.get("fidelity", {}).get("subgroups") or []
    misrepresented = _misrepresented(subgroups)
    withdrawn = release.get("withdrawn_at")
    lines = [
        f"# Data card: synthetic release {release['release_id']}",
        "",
        *(
            [
                f"**Withdrawn {withdrawn:%Y-%m-%d}: {release['withdrawn_reason']}** Do not use"
                " this release. Delete every copy, and recheck any result computed from it.",
                "",
            ]
            if withdrawn
            else []
        ),
        f"**{spec.name}**, made {release['created_at']:%Y-%m-%d} from database"
        f" `{release['source_database']}` at code version `{release['code_version']}`.",
        "",
        spec.description,
        "",
        "## At a glance",
        "",
        "| | |",
        "|---|---|",
        f"| Method | {method} |",
        f"| Privacy budget | epsilon {release['epsilon']:g}"
        + (f", delta {spec.vae.delta:g}" if release["method"] == "vae" else "")
        + " |",
        f"| Rows | {release['rows']:,} (a noisy count) |",
        f"| Trained on | {release['source_rows']:,} people;"
        f" {release['holdout_rows'] or 0:,} held out for evaluation |",
        f"| Seed | {release['seed'] if release['seed'] is not None else 'none (secure noise)'} |",
        "",
        "## Intended use",
        "",
        "For building, testing, and demonstrating analyses and pipelines without touching the"
        " source. Not for estimates that will be reported, and never for clinical decisions."
        + (
            f" In trial parity, {spurious:.0%} of draws at this setting showed an effect the real"
            " data does not, so do not read effect estimates from it."
            if spurious
            else ""
        )
        + (
            " Some groups are misrepresented, so do not study them in it: "
            + "; ".join(
                f"{r['column']} {r['group']} at {r['share_ratio']:.2f} times its real share"
                for r in misrepresented[:WARN_AT_MOST]
            )
            + (
                f"; and {len(misrepresented) - WARN_AT_MOST} more, listed in its fidelity report."
                if len(misrepresented) > WARN_AT_MOST
                else "."
            )
            if misrepresented
            else ""
        ),
        "",
        "## Data use limitations",
        "",
        "Inherited from the source: a synthetic release is derived from it and may be used only"
        " within these terms.",
        "",
        spec.data_use_limitations,
        "",
        *(
            [
                "Derived from controlled-access data, so it is shared only with the approved users"
                " named in the data access request"
                + (f" ({', '.join(spec.approved_users)})" if spec.approved_users else "")
                + (
                    f", or as the DAC has allowed: {spec.dac_sharing_approval}."
                    if spec.dac_sharing_approval
                    else ", unless the DAC approves wider sharing."
                ),
                "",
            ]
            if spec.source_access == "controlled"
            else []
        ),
        "## How it was made",
        "",
        "Every category list and numeric range below is fixed in the spec, never read from the"
        " data. Parents are the columns each column's distribution was measured against; they"
        " were declared, not learned, so they cost no privacy.",
        "",
        "| Column | Source | Domain | Parents |",
        "|---|---|---|---|",
        *(_column(c) for c in spec.columns),
        "",
        "## Privacy spend",
        "",
        "Each mechanism that touched the source, and what it spent. The spends add up to the"
        " release's budget (sequential composition).",
        "",
        "| Mechanism | Spend |",
        "|---|---|",
        *(_spend(entry) for entry in release["measurements"]),
    ]
    if release["seed"] is not None:
        lines += [
            "",
            "The noise was seeded so the release can be remade exactly. That is only acceptable"
            " because the source is itself synthetic: anyone with the seed can regenerate the"
            " noise. A release from real data must leave the seed unset.",
        ]
    if "fidelity" in reports:
        lines += ["", *_fidelity(reports["fidelity"])]
    if subgroups:
        lines += ["", *_subgroups(subgroups, spec.utility_target)]
    if trial:
        lines += ["", *_trial(trial)]
    if "privacy" in reports:
        lines += ["", *_privacy(reports["privacy"])]
    elif not spec.attacks_allowed:
        lines += [
            "",
            "## Privacy risk",
            "",
            "Not assessed: on a controlled source the attacks are attempts to identify"
            " participants, and the data access request has not approved them. Its protection"
            " rests on the differential privacy budget alone.",
        ]
    elif not release["holdout_rows"]:
        lines += [
            "",
            "## Privacy risk",
            "",
            "Not assessed: the attacks compare training people with held-out people, and this"
            " spec keeps no holdout. Its protection rests on the differential privacy budget"
            " alone.",
        ]
    lines += [
        "",
        "## Limitations",
        "",
        "- The source is Synthea output, not real patients. The methods carry over; the numbers"
        " describe this source only.",
        "- The reports above were computed on the source and are not themselves differentially"
        " private. They are for reviewers, not for release.",
        "- The privacy attacks bound risk from below: a stronger attack might do better."
        " Differential privacy is the guarantee.",
        "- The source has no location, the strongest quasi-identifier for linkage.",
    ]
    if release["method"] == "bayes_net":
        lines.append(
            "- Only the relationships named as parents are kept; others survive only through them."
        )
    lines.append("")
    return "\n".join(lines)
