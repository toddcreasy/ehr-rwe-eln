"""Residual privacy risk of a synthetic release: three attacks, each comparing the people the
release was trained on (members) with the held-out people (non-members).

What an attacker learns equally about both groups is population-level knowledge, which is what
a release is for. Only the difference between the groups is leakage about individuals.

- Distance to closest record (DCR): for synthetic rows, is the nearest real record a member or
  a non-member? Members and non-members are sampled in equal numbers, so 50% means nothing was
  memorized. Also the share of synthetic rows that exactly match a member, and a non-member.
- Membership inference: an attacker holding a real person's record scores how close it sits
  to the release (fewest differing columns, then how many synthetic rows sit that close) and
  guesses that close means member. Scored by AUC over equal numbers of members and
  non-members: 0.5 is a coin flip, 1 is certainty.
- Attribute inference: an attacker who knows a person's quasi-identifiers (age group, sex,
  race, ethnicity) takes the most common value of a sensitive column among the matching
  synthetic rows as their guess. The leak is how much more accurate that is for members.
- Quasi-identifier uniqueness, of the source itself: the share of training people who are the
  only one with their exact age, sex, race, and ethnicity, and with age in the spec's groups.
  It sets how much any linkage attack could single people out.

Distances count differing columns on the spec's encoding (bins and categories).

A failed attack shows only that this attack failed; a stronger one might not. Differential
privacy is the guarantee; these are empirical checks of it, and are read against the same
attacks on a plain copy of the training data, which shows what real leakage looks like.
"""

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

from ehr_rwe_eln.synth.bayes_net import encode
from ehr_rwe_eln.synth.spec import Spec

SAMPLE = 2000
QUASI_IDENTIFIERS = ["age", "sex", "race", "ethnicity"]
CHUNK = 256


def _nearest(a: np.ndarray, b: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """For each row of a: the fewest columns it differs from any row of b, and how many rows
    of b differ by that few."""
    distance, count = np.empty(len(a), dtype=np.int64), np.empty(len(a), dtype=np.int64)
    for start in range(0, len(a), CHUNK):
        d = (a[start : start + CHUNK, None, :] != b[None, :, :]).sum(axis=2)
        least = d.min(axis=1)
        distance[start : start + CHUNK] = least
        count[start : start + CHUNK] = (d == least[:, None]).sum(axis=1)
    return distance, count


def _sample(codes: np.ndarray, n: int, rng: np.random.Generator) -> np.ndarray:
    return codes[rng.choice(len(codes), min(n, len(codes)), replace=False)]


def distance_to_closest_record(
    members: np.ndarray, non_members: np.ndarray, synthetic: np.ndarray, rng
) -> dict:
    n = min(len(members), len(non_members))
    members, non_members = _sample(members, n, rng), _sample(non_members, n, rng)
    rows = _sample(synthetic, SAMPLE, rng)
    to_member, _ = _nearest(rows, members)
    to_non_member, _ = _nearest(rows, non_members)
    closer = (to_member < to_non_member).mean() + 0.5 * (to_member == to_non_member).mean()
    return {
        "closer_to_member": float(closer),
        "exact_match_member": float((to_member == 0).mean()),
        "exact_match_non_member": float((to_non_member == 0).mean()),
    }


def membership_inference(
    members: np.ndarray, non_members: np.ndarray, synthetic: np.ndarray, rng
) -> dict:
    n = min(len(members), len(non_members), SAMPLE)
    targets = np.vstack([_sample(members, n, rng), _sample(non_members, n, rng)])
    distance, count = _nearest(targets, synthetic)
    # Closer is more suspicious; among equally close, more synthetic rows that close is more.
    score = -distance + count / (len(synthetic) + 1)
    auc = float(roc_auc_score(np.r_[np.ones(n), np.zeros(n)], score))
    return {"auc": auc, "targets_each": int(n)}


def _qi_key(table: pd.DataFrame, spec: Spec) -> pd.Series:
    qis = [c for c in spec.columns if c.name in QUASI_IDENTIFIERS]
    codes = encode(table, qis)
    return pd.Series(["|".join(map(str, row)) for row in codes], index=table.index)


def attribute_inference(
    members: pd.DataFrame,
    non_members: pd.DataFrame,
    synthetic: pd.DataFrame,
    spec: Spec,
    sensitive: list[str],
) -> dict:
    synthetic_key = _qi_key(synthetic, spec)
    out = {}
    for column in sensitive:
        guesses = synthetic.groupby(synthetic_key)[column].agg(lambda v: v.mode().iloc[0])
        overall = synthetic[column].mode().iloc[0]  # for people with no matching row
        accuracy = {}
        for label, people in (("member", members), ("non_member", non_members)):
            guess = _qi_key(people, spec).map(guesses).fillna(overall)
            accuracy[label] = float((guess.to_numpy() == people[column].to_numpy()).mean())
        out[column] = {**accuracy, "gap": accuracy["member"] - accuracy["non_member"]}
    return out


def uniqueness(train: pd.DataFrame, spec: Spec) -> dict:
    qis = [c for c in QUASI_IDENTIFIERS if c in train.columns]
    exact = train.groupby(qis, dropna=False)[qis[0]].transform("size")
    grouped = _qi_key(train, spec).map(_qi_key(train, spec).value_counts())
    return {"exact_age": float((exact == 1).mean()), "age_group": float((grouped == 1).mean())}


def _pct(value: float) -> str:
    return f"{round(value, 3) + 0.0:+.1%}"  # + 0.0 turns -0.0 into 0.0


def privacy_report(
    train: pd.DataFrame, holdout: pd.DataFrame, synthetic: pd.DataFrame, spec: Spec, seed: int = 0
) -> dict:
    rng = np.random.default_rng(seed)
    members, non_members = encode(train, spec.columns), encode(holdout, spec.columns)
    synthetic_codes = encode(synthetic, spec.columns)
    # Sensitive columns: every 0/1 flag that is not a quasi-identifier.
    sensitive = [
        c.name for c in spec.columns if c.categories == [0, 1] and c.name not in QUASI_IDENTIFIERS
    ]
    attributes = attribute_inference(train, holdout, synthetic, spec, sensitive)
    worst = max(attributes, key=lambda name: attributes[name]["gap"])
    report = {
        "distance_to_closest_record": distance_to_closest_record(
            members, non_members, synthetic_codes, rng
        ),
        "membership_inference": membership_inference(members, non_members, synthetic_codes, rng),
        "attribute_inference": {
            "quasi_identifiers": [
                c for c in QUASI_IDENTIFIERS if c in {x.name for x in spec.columns}
            ],
            "gap_mean": float(np.mean([a["gap"] for a in attributes.values()])),
            "gap_max": attributes[worst]["gap"],
            "gap_worst": worst,
            "by_column": attributes,
        },
        "quasi_identifier_uniqueness": uniqueness(train, spec),
    }
    report["summary"] = summary(report)
    return report


def summary(report: dict) -> str:
    """The report in a few plain sentences, for readers who will not read the numbers."""
    dcr = report["distance_to_closest_record"]
    auc = report["membership_inference"]["auc"]
    attrs = report["attribute_inference"]
    unique = report["quasi_identifier_uniqueness"]
    return (
        f"Copying: {dcr['closer_to_member']:.0%} of synthetic rows sit nearer a real person in"
        f" the training data than one held out (50% means no sign of copying);"
        f" {dcr['exact_match_member']:.1%} match a training person exactly on every column,"
        f" against {dcr['exact_match_non_member']:.1%} for held-out people."
        f" Membership: an attacker holding someone's record and this release tells whether they"
        f" were in the training data with an AUC of {auc:.2f} (0.50 is a coin flip)."
        f" Sensitive values: guessing a condition, drug, or death from age group, sex, race, and"
        f" ethnicity is {_pct(attrs['gap_mean'])} more accurate for training people than for"
        f" held-out ones on average, at most {_pct(attrs['gap_max'])} ({attrs['gap_worst']})."
        f" In the source, {unique['exact_age']:.1%} of people are the only one with their exact"
        f" age, sex, race, and ethnicity, and {unique['age_group']:.1%} with age in groups."
        f" These attacks are a lower bound on risk; the source has no location, which a real"
        f" linkage attack would use."
    )
