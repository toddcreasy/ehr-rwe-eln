"""A differentially private Bayesian network synthesizer, and an independent-columns baseline.

Differential privacy (DP) bounds how much any one person can change what is released. Here the
only thing computed from the source is a set of histograms (counts per cell), and every count
gets random noise from diffprivlib before anything else sees it. Adding or removing one person
changes one cell of each histogram by 1 (the sensitivity), so noise on that scale hides them.

1. Encode: each value becomes an integer code. Categories by position; numbers by bin, clamped
   into the end bins, with one extra code for missing where the column allows it.
2. Measure: one noisy histogram per column, over the column and its parents (bayes_net) or the
   column alone (independent). Every histogram counts every person, so their privacy costs add
   up (sequential composition): the release's epsilon is split evenly across them, and
   diffprivlib's BudgetAccountant refuses to spend more than that.
3. Sample: draw each column in spec order from its noisy counts given its parents' codes. This
   uses only the noisy histograms, never the source, so it costs no privacy (post-processing).
4. Decode: codes back to values; a number is drawn uniformly inside its bin.
"""

from dataclasses import asdict, dataclass
from typing import cast

import numpy as np
import pandas as pd
from diffprivlib import BudgetAccountant
from diffprivlib.tools import histogramdd

from ehr_rwe_eln.synth.spec import Column, Numeric, Release, Spec


@dataclass
class Measurement:
    columns: list[str]
    cells: int
    epsilon: float


def encode(table: pd.DataFrame, columns: list[Column]) -> np.ndarray:
    """An int array, one column per spec column. A category outside the spec is an error: the
    domain is fixed in the spec, and the data never extends it."""
    codes = np.empty((len(table), len(columns)), dtype=np.int64)
    for j, column in enumerate(columns):
        values = table[column.name]
        if column.categories is not None:
            lookup = {value: i for i, value in enumerate(column.categories)}
            unknown = set(values.unique()) - set(lookup)
            if unknown:
                outside = sorted(unknown, key=str)
                raise ValueError(f"{column.name}: values outside the spec: {outside}")
            codes[:, j] = values.map(lookup).to_numpy()
            continue
        # Not categories, so numeric: the spec gives each column exactly one.
        n = cast(Numeric, column.numeric)
        width = (n.high - n.low) / n.bins
        binned = np.clip(np.floor((values.to_numpy(dtype=float) - n.low) / width), 0, n.bins - 1)
        missing = values.isna().to_numpy()
        if missing.any() and not column.missing_allowed:
            raise ValueError(f"{column.name}: missing values, and the column allows none")
        codes[:, j] = np.where(missing, n.bins, binned)
    return codes


def decode(codes: np.ndarray, columns: list[Column], rng: np.random.Generator) -> pd.DataFrame:
    out = {}
    for j, column in enumerate(columns):
        if column.categories is not None:
            out[column.name] = np.asarray(column.categories, dtype=object)[codes[:, j]]
            continue
        # Not categories, so numeric: the spec gives each column exactly one.
        n = cast(Numeric, column.numeric)
        width = (n.high - n.low) / n.bins
        start = n.low + codes[:, j] * width
        if n.integer:
            values = np.floor(start + rng.random(len(codes)) * width).astype(float)
        else:
            values = start + rng.random(len(codes)) * width
        out[column.name] = np.where(codes[:, j] == n.bins, np.nan, values)
    frame = pd.DataFrame(out)
    for column in columns:
        if column.categories is not None and all(isinstance(c, int) for c in column.categories):
            frame[column.name] = frame[column.name].astype(int)
    return frame


def _conditional(counts: np.ndarray) -> np.ndarray:
    """Noisy counts over (parents..., column) to P(column | parents), one row per parent cell.
    A parent cell whose counts are all zero falls back to the column's overall distribution,
    and that to uniform."""
    size = counts.shape[-1]
    rows = counts.reshape(-1, size)
    marginal = rows.sum(axis=0)
    marginal = marginal / marginal.sum() if marginal.sum() > 0 else np.full(size, 1 / size)
    totals = rows.sum(axis=1, keepdims=True)
    safe = np.where(totals > 0, totals, 1)
    return np.where(totals > 0, rows / safe, marginal)


def synthesize(
    table: pd.DataFrame, spec: Spec, release: Release
) -> tuple[pd.DataFrame, list[Measurement]]:
    """A synthetic table with the spec's columns, and the measurements it spent epsilon on.
    The number of rows is the noisy total of the first histogram, not the source's count."""
    columns = spec.columns
    position = {c.name: j for j, c in enumerate(columns)}
    codes = encode(table, columns)
    # Seeded noise for reproducible releases from synthetic sources; None gives secure noise.
    noise = np.random.RandomState(spec.seed) if spec.seed is not None else None
    sampling = np.random.default_rng(spec.seed)
    accountant = BudgetAccountant(epsilon=release.epsilon)
    # Shaved so that rounding in the sum can only fall under the budget, never over it.
    epsilon = release.epsilon / len(columns) * (1 - 1e-12)

    measurements, tables, totals = [], [], []
    for column in columns:
        names = (column.parents if release.method == "bayes_net" else []) + [column.name]
        dims = [position[name] for name in names]
        sizes = [columns[d].size for d in dims]
        counts, _ = histogramdd(
            codes[:, dims],
            epsilon=epsilon,
            # One bin per code. diffprivlib's hint says int; its docs also take bin edges.
            bins=[np.arange(size + 1) - 0.5 for size in sizes],  # type: ignore[arg-type]
            random_state=noise,
            accountant=accountant,
        )
        totals.append(counts.sum())
        measurements.append(Measurement(names, int(np.prod(sizes)), epsilon))
        tables.append((dims[:-1], sizes[:-1], _conditional(counts)))

    n = int(round(totals[0]))
    synthetic = np.zeros((n, len(columns)), dtype=np.int64)
    for j, (parent_dims, parent_sizes, conditional) in enumerate(tables):
        cell = (
            np.ravel_multi_index(tuple(synthetic[:, d] for d in parent_dims), parent_sizes)
            if parent_dims
            else np.zeros(n, dtype=np.int64)
        )
        cumulative = conditional[cell].cumsum(axis=1)
        drawn = (cumulative < sampling.random((n, 1))).sum(axis=1)
        synthetic[:, j] = np.minimum(drawn, columns[j].size - 1)
    return decode(synthetic, columns, sampling), measurements


def plan(measurements: list[Measurement]) -> list[dict]:
    return [asdict(m) for m in measurements]
