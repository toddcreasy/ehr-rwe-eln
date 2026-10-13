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
"""

import numpy as np
import pandas as pd
from scipy.stats import ks_2samp
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score

from ehr_rwe_eln.synth.bayes_net import encode
from ehr_rwe_eln.synth.spec import Column

WORST_PAIRS = 10


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


def utility_auc(
    train: pd.DataFrame, test: pd.DataFrame, columns: list[Column], target: str
) -> float | None:
    """AUC on test of a logistic regression fit on train, predicting target from every other
    column. None when train has only one class (nothing to learn from)."""
    features = [c for c in columns if c.name != target]
    y_train, y_test = train[target].to_numpy(), test[target].to_numpy()
    if len(set(y_train)) < 2:
        return None
    model = LogisticRegression(max_iter=2000)
    model.fit(_one_hot(encode(train, features), features), y_train)
    scores = model.predict_proba(_one_hot(encode(test, features), features))[:, 1]
    return float(roc_auc_score(y_test, scores))


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
