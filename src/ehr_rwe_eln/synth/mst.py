"""MST, the winning mechanism of the 2018 NIST synthetic data contest, in its general form.

McKenna, Miklau, and Sheldon, "Winning the NIST Contest: A scalable and general approach to
differentially private synthetic data" (2021), https://arxiv.org/abs/2108.04978. Adapted from
the authors' mechanisms/mst.py in private-pgm (Apache-2.0, commit bad442f729a8), with `mbi`
(private-pgm's library) for the model. Where the Bayes net is told which columns depend on
which (the spec's parents), MST picks the pairs itself, from the data, and pays privacy for it:

1. Measure every column's histogram with Gaussian noise.
2. Select pairs: fit a model to those histograms alone, find the pairs of columns it gets most
   wrong, and pick a tree of pairs (each column joined to the rest, no cycles) one pair at a
   time with the exponential mechanism, which favors the worst-fitted pairs but adds chance so
   no one person decides the choice.
3. Measure each chosen pair's two-way histogram with Gaussian noise.
4. Fit a graphical model (a Markov random field) to all the noisy histograms with mirror
   descent, and sample rows from it. Sampling uses only the noisy measurements (post-processing,
   no privacy cost).

The three measuring steps get a third of the budget each. Budgets here are in zero-concentrated
differential privacy (zCDP), whose cost rho adds up across steps; the total rho is converted to
the release's (epsilon, delta) by cdp_rho. Encoding and decoding are the Bayes net's, so both
release the same binned columns.

The authors' version also merges categories whose noisy count is under three standard
deviations into one before step 2. Here columns have at most 13 codes, so that is left out.
"""

import itertools
import math

import numpy as np
import pandas as pd
from mbi import Dataset, Domain, LinearMeasurement, estimation
from scipy.cluster.hierarchy import DisjointSet
from scipy.special import logsumexp

from ehr_rwe_eln.synth.bayes_net import decode, encode
from ehr_rwe_eln.synth.spec import Release, Spec


# cdp_delta and cdp_rho: Canonne, Kamath, and Steinke, "The Discrete Gaussian for Differential
# Privacy" (2020), from IBM/discrete-gaussian-differential-privacy (Apache-2.0), as private-pgm
# ships them in mechanisms/cdp2adp.py.
def cdp_delta(rho: float, eps: float) -> float:
    """The delta that rho-zCDP gives at this epsilon."""
    if rho == 0:
        return 0.0
    # Any alpha above 1 gives a valid bound; search for the best. The floor keeps it stable.
    amin, amax = 1.01, (eps + 1) / (2 * rho) + 2
    for _ in range(1000):
        alpha = (amin + amax) / 2
        derivative = (2 * alpha - 1) * rho - eps + math.log1p(-1.0 / alpha)
        if derivative < 0:
            amin = alpha
        else:
            amax = alpha
    delta = math.exp((alpha - 1) * (alpha * rho - eps) + alpha * math.log1p(-1 / alpha))
    return min(delta / (alpha - 1.0), 1.0)


def cdp_rho(eps: float, delta: float) -> float:
    """The largest rho whose zCDP guarantee implies (eps, delta)-differential privacy."""
    rhomin, rhomax = 0.0, eps + 1
    for _ in range(1000):
        rho = (rhomin + rhomax) / 2
        if cdp_delta(rho, eps) <= delta:
            rhomin = rho
        else:
            rhomax = rho
    return rhomin


def _measure(
    data: Dataset, cliques: list[tuple[str, ...]], sigma: float, rng: np.random.Generator
) -> list[LinearMeasurement]:
    """One noisy histogram per clique. Each person is in every histogram, so with k of them the
    noise on each is sigma * sqrt(k): together they cost what one histogram at sigma would,
    rho = 1 / (2 sigma^2)."""
    scale = sigma * math.sqrt(len(cliques))
    out = []
    for clique in cliques:
        x = data.project(clique).datavector()
        out.append(LinearMeasurement(x + rng.normal(0, scale, x.size), clique, scale))
    return out


def _select(
    data: Dataset, rho: float, measured: list[LinearMeasurement], rng: np.random.Generator
) -> list[tuple[str, str]]:
    """A spanning tree of column pairs, chosen with the exponential mechanism at a total cost of
    rho. A pair's score is how far the model of one-way histograms is from the pair's real
    counts (L1); one person changes it by at most 1."""
    model = estimation.MirrorDescent().estimate(data.domain, measured, iters=2500)
    columns = list(data.domain.attributes)
    candidates = list(itertools.combinations(columns, 2))
    score = {}
    for a, b in candidates:
        real, fitted = data.project([a, b]).datavector(), model.project([a, b]).datavector()
        score[a, b] = float(np.linalg.norm(real - fitted, 1))
    joined = DisjointSet(columns)
    # A tree over n columns has n - 1 pairs; each choice costs epsilon^2 / 8 in zCDP.
    epsilon = math.sqrt(8 * rho / (len(columns) - 1))
    tree = []
    for _ in range(len(columns) - 1):
        candidates = [e for e in candidates if not joined.connected(*e)]
        q = 0.5 * epsilon * np.array([score[e] for e in candidates])
        chosen = candidates[rng.choice(len(candidates), p=np.exp(q - logsumexp(q)))]
        joined.merge(*chosen)
        tree.append(chosen)
    return tree


def synthesize(table: pd.DataFrame, spec: Spec, release: Release) -> tuple[pd.DataFrame, list]:
    """A synthetic table with the spec's columns, and the privacy spend of each step. The number
    of rows is the model's total, which comes from the noisy histograms."""
    columns = spec.columns
    names = [c.name for c in columns]
    codes = encode(table, columns)
    domain = Domain(names, [c.size for c in columns])
    data = Dataset({name: codes[:, j] for j, name in enumerate(names)}, domain)
    rng = np.random.default_rng(spec.seed)

    rho = cdp_rho(release.epsilon, spec.pgm.delta)
    sigma = math.sqrt(3 / (2 * rho))
    one_way = _measure(data, [(name,) for name in names], sigma, rng)
    tree = _select(data, rho / 3, one_way, rng)
    two_way = _measure(data, tree, sigma, rng)
    model = estimation.MirrorDescent().estimate(domain, one_way + two_way, iters=spec.pgm.iters)

    # mbi samples with numpy's global generator; seeding it makes the release repeatable.
    np.random.seed(spec.seed)
    sampled = model.synthetic_data()
    synthetic = np.stack([np.asarray(sampled.to_dict()[name]) for name in names], axis=1)
    spend = [
        {"mechanism": "gaussian", "of": "one-way histograms", "columns": names,
         "rho": rho / 3, "sigma": sigma * math.sqrt(len(names))},
        {"mechanism": "exponential", "of": "pair selection", "pairs": [list(e) for e in tree],
         "rho": rho / 3},
        {"mechanism": "gaussian", "of": "two-way histograms", "pairs": [list(e) for e in tree],
         "rho": rho / 3, "sigma": sigma * math.sqrt(len(tree))},
    ]  # fmt: skip
    return decode(synthetic, columns, rng), spend
