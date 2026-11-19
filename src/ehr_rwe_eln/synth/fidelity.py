"""How closely a synthetic release matches the real data it was made from, and whether a model
trained on it still works on real people.

Every table is first encoded with the spec's bins and categories (as the synthesizers encode
it), so every column is compared on the same footing.

- Total variation distance (TVD): half the summed absolute difference between two
  distributions' shares. 0 means identical, 1 means no overlap. Per column, and per pair of
  columns on their joint distribution, which catches relationships the synthesizer was not
  told about as well as those it was.
- Kolmogorov-Smirnov (KS) statistic: for numeric columns, the largest gap between the two
  cumulative distributions of the raw values, missing values left out.
- Correlation gap: the mean absolute difference between the two Pearson correlation matrices
  over the ordered columns (numeric bins and 0/1 flags; unordered categories have no
  correlation).
- Utility, train on synthetic, test on real (TSTR): a logistic regression trained on the
  release predicts a 0/1 target for held-out real people, scored by AUC (area under the ROC
  curve: the chance a random positive ranks above a random negative; 0.5 is guessing, 1 is
  perfect). Set against the same model trained on the real training data (TRTR).

None of these has a fixed pass mark. Read them against the noise floor: the same report for
the real holdout against the real training set, two samples of the same population.

A release can match its source overall and still distort a small group, because DP noise is
the same size for every count. So the spec's subgroup columns (race, sex, age bins) get the
same reading within each group: its share of the release, its mean column TVD, and its own
noise floor, which is higher for a small group because two small samples differ more.
"""

import itertools

import numpy as np
import pandas as pd
from scipy.stats import ks_2samp
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score

from ehr_rwe_eln.synth.bayes_net import encode
from ehr_rwe_eln.synth.spec import Column

WORST_PAIRS = 10
# Groups smaller than this are reported without numbers, as CMS suppresses any published
# cell under 11 people; below it a group's measures are mostly noise anyway. A group AUC also
# needs this many people in each outcome class.
MIN_GROUP = 11


def _tvd(a: np.ndarray, b: np.ndarray, size: int) -> float:
    p = np.bincount(a, minlength=size) / len(a)
    q = np.bincount(b, minlength=size) / len(b)
    return float(0.5 * np.abs(p - q).sum())


def _ordered(column: Column) -> bool:
    return column.numeric is not None or column.categories == [0, 1]


def _correlations(codes: np.ndarray, columns: list[Column]) -> pd.DataFrame:
    frame = pd.DataFrame(
        {c.name: codes[:, j].astype(float) for j, c in enumerate(columns) if _ordered(c)}
    )
    for c in columns:
        if c.numeric is not None and c.missing_allowed:
            frame.loc[frame[c.name] == c.numeric.bins, c.name] = np.nan
    return frame.corr()


def _one_hot(codes: np.ndarray, columns: list[Column]) -> np.ndarray:
    return np.hstack([np.eye(c.size)[codes[:, j]] for j, c in enumerate(columns)])


def _fit(
    train: pd.DataFrame, columns: list[Column], target: str
) -> tuple[LogisticRegression, list[Column]] | None:
    features = [c for c in columns if c.name != target]
    y_train = train[target].to_numpy()
    if len(set(y_train)) < 2:
        return None
    model = LogisticRegression(max_iter=2000)
    model.fit(_one_hot(encode(train, features), features), y_train)
    return model, features


def _auc(
    fit: tuple[LogisticRegression, list[Column]] | None,
    test: pd.DataFrame,
    target: str,
    min_class: int = 1,
) -> float | None:
    y_test = test[target].to_numpy()
    if fit is None or min((y_test == 0).sum(), (y_test == 1).sum()) < min_class:
        return None
    model, features = fit
    scores = model.predict_proba(_one_hot(encode(test, features), features))[:, 1]
    return float(roc_auc_score(y_test, scores))


def utility_auc(
    train: pd.DataFrame, test: pd.DataFrame, columns: list[Column], target: str
) -> float | None:
    """AUC on test of a logistic regression fit on train, predicting target from every other
    column. None when train has only one class (nothing to learn from)."""
    return _auc(_fit(train, columns, target), test, target)


def _group_labels(column: Column) -> list[str]:
    """One label per code: the categories, or each numeric bin's range, then missing."""
    if column.numeric is None:
        return [str(c) for c in column.categories or []]
    n = column.numeric
    edges = np.linspace(n.low, n.high, n.bins + 1)
    top = [edges[i + 1] - 1 if n.integer else edges[i + 1] for i in range(n.bins)]
    labels = [f"{edges[i]:g} to {top[i]:g}" for i in range(n.bins)]
    if n.open_top:
        labels[-1] = f"{edges[-2]:g} or more"
    return labels + (["missing"] if column.missing_allowed else [])


def _column_tvd_mean(real: np.ndarray, synthetic: np.ndarray, columns: list[Column]) -> float:
    return float(
        np.mean([_tvd(real[:, j], synthetic[:, j], c.size) for j, c in enumerate(columns)])
    )


def subgroup_report(
    train: pd.DataFrame,
    holdout: pd.DataFrame,
    synthetic: pd.DataFrame,
    columns: list[Column],
    by: list[str | list[str]],
    target: str | None = None,
) -> list[dict]:
    """Fidelity within each group of each entry in by: a column, one group per category or
    bin, or a list of columns, one group per combination. One row per group:

    - share_ratio: the group's share of the release over its share of the training data (1 is
      right; 0.7 means the release has 30% too few of them).
    - column_tvd_mean: mean column TVD between the group's training rows and its release rows,
      over the other columns. noise_floor: the same between its holdout and training rows.
      excess: the first minus the second, how far the release is past sampling noise.
    - tstr_auc, trtr_auc (with a target and a holdout): the utility models, trained on the
      whole release and on the whole training data, scored on the group's held-out people.

    A group with fewer than MIN_GROUP training people is still listed, with suppressed true and
    no numbers, so a reader sees how much of an intersection is too small to report.
    """
    real, held, synth = (encode(t, columns) for t in (train, holdout, synthetic))
    fits = None
    if target and len(holdout):
        fits = (_fit(synthetic, columns, target), _fit(train, columns, target))
    names = {c.name: j for j, c in enumerate(columns)}
    out = []
    for entry in by:
        group_columns = [entry] if isinstance(entry, str) else entry
        js = [names[name] for name in group_columns]
        others = [k for k in range(len(columns)) if k not in js]
        rest = [columns[k] for k in others]
        labels = [_group_labels(columns[j]) for j in js]
        for combination in itertools.product(*(range(len(x)) for x in labels)):
            masks = [
                np.all([t[:, j] == code for j, code in zip(js, combination, strict=True)], axis=0)
                for t in (real, held, synth)
            ]
            r, h, s = (t[m][:, others] for t, m in zip((real, held, synth), masks, strict=True))
            row: dict = {
                "column": " x ".join(group_columns),
                "group": ", ".join(x[code] for x, code in zip(labels, combination, strict=True)),
                "suppressed": len(r) < MIN_GROUP,
            }
            if row["suppressed"]:
                out.append(row)
                continue
            tvd = _column_tvd_mean(r, s, rest) if len(s) >= MIN_GROUP else None
            floor = _column_tvd_mean(r, h, rest) if len(h) >= MIN_GROUP else None
            row |= {
                "train_people": len(r),
                "holdout_people": len(h),
                "release_people": len(s),
                "share_ratio": (len(s) / len(synth)) / (len(r) / len(real)),
                "column_tvd_mean": tvd,
                "noise_floor": floor,
                "excess": tvd - floor if tvd is not None and floor is not None else None,
            }
            if fits and target:
                group = holdout[masks[1]]
                row["tstr_auc"] = _auc(fits[0], group, target, MIN_GROUP)
                row["trtr_auc"] = _auc(fits[1], group, target, MIN_GROUP)
            out.append(row)
    return out


def fidelity_report(real: pd.DataFrame, synthetic: pd.DataFrame, columns: list[Column]) -> dict:
    real_codes, synthetic_codes = encode(real, columns), encode(synthetic, columns)
    column_tvd = {
        c.name: _tvd(real_codes[:, j], synthetic_codes[:, j], c.size) for j, c in enumerate(columns)
    }
    ks = {}
    for c in columns:
        if c.numeric is not None:
            a, b = real[c.name].dropna(), synthetic[c.name].dropna()
            ks[c.name] = float(ks_2samp(a, b).statistic) if len(a) and len(b) else None
    pairs = []
    for i, a in enumerate(columns):
        for j in range(i + 1, len(columns)):
            b = columns[j]
            # One code per combination of the two columns' codes.
            real_joint = real_codes[:, i] * b.size + real_codes[:, j]
            synthetic_joint = synthetic_codes[:, i] * b.size + synthetic_codes[:, j]
            pairs.append(([a.name, b.name], _tvd(real_joint, synthetic_joint, a.size * b.size)))
    pairs.sort(key=lambda p: p[1], reverse=True)
    gap = (_correlations(real_codes, columns) - _correlations(synthetic_codes, columns)).abs()
    upper = gap.to_numpy()[np.triu_indices(len(gap), k=1)]
    upper = upper[~np.isnan(upper)]
    worst_column = max(column_tvd, key=lambda name: column_tvd[name])
    return {
        "summary": {
            "column_tvd_mean": float(np.mean(list(column_tvd.values()))),
            "column_tvd_max": column_tvd[worst_column],
            "column_tvd_worst": worst_column,
            "pair_tvd_mean": float(np.mean([t for _, t in pairs])),
            "pair_tvd_max": pairs[0][1],
            "pair_tvd_worst": pairs[0][0],
            # A column that is constant in one table has no correlation; such pairs are skipped,
            # and with none left there is no gap to report.
            "correlation_gap_mean": float(upper.mean()) if len(upper) else None,
        },
        "column_tvd": column_tvd,
        "ks": ks,
        "worst_pairs": [{"columns": names, "tvd": t} for names, t in pairs[:WORST_PAIRS]],
    }
