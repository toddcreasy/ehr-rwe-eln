"""AIM, MST's successor from the same group: it spends its budget on the queries you name.

McKenna, Mullins, Sheldon, and Miklau, "AIM: An Adaptive and Iterative Mechanism for
Differentially Private Synthetic Data" (VLDB 2022), https://arxiv.org/abs/2201.12677. Adapted
from the authors' mechanisms/aim.py in private-pgm (Apache-2.0, commit bad442f729a8), with `mbi`
for the model, as synth/mst.py. MST picks a tree of pairs once; AIM is given a workload (the
marginals an analyst will ask for, each with a weight) and works in rounds:

1. Measure every column's histogram with Gaussian noise and fit a model to them.
2. Each round, pick the workload marginal (or a smaller marginal inside one) the current model
   gets most wrong, with the exponential mechanism; measure it with Gaussian noise; refit. A
   candidate is skipped while adding it would grow the model past a size limit, which rises
   with the budget spent.
3. When a measurement barely changes the model, the noise was too large to tell: halve it (the
   next rounds cost more each, so there are fewer of them).
4. Stop when the budget is spent, and sample rows from the final model.

Each round gives 10% of its rho to the choice and 90% to the measurement. Budgets are in zCDP;
the total rho comes from the release's (epsilon, delta) by cdp_rho.

The workload is the spec's `workload` (the trial's and the cohorts' marginals) plus every pair
of columns at weight 1, the authors' default, so columns outside the queries are still related.
"""

import itertools
import math
import resource
import sys

import jax
import numpy as np
import pandas as pd
from mbi import Dataset, Domain, LinearMeasurement, estimation, junction_tree, marginal_oracles
from scipy.special import softmax

from ehr_rwe_eln.synth.bayes_net import decode, encode
from ehr_rwe_eln.synth.mst import cdp_rho
from ehr_rwe_eln.synth.spec import Release, Spec


def workload(spec: Spec) -> dict[tuple[str, ...], float]:
    """The spec's queries at their weights, and every other pair of columns at weight 1."""
    names = [c.name for c in spec.columns]
    order = {name: i for i, name in enumerate(names)}
    out = {pair: 1.0 for pair in itertools.combinations(names, 2)}
    for query in spec.workload:
        out[tuple(sorted(query.columns, key=order.get))] = query.weight
    return out


def candidates(weights: dict[tuple[str, ...], float]) -> dict[tuple[str, ...], float]:
    """Every marginal inside a workload marginal, scored by how much of the workload it covers:
    the sum, over workload marginals, of weight times the columns they share."""
    closure = {
        sub
        for cl in weights
        for r in range(1, len(cl) + 1)
        for sub in itertools.combinations(cl, r)
    }
    return {
        sub: sum(w * len(set(sub) & set(cl)) for cl, w in weights.items())
        # Sorted fully: set order changes with each process's string hashing, and the order
        # decides which marginal the seeded draw in _worst picks.
        for sub in sorted(closure, key=lambda c: (len(c), c))
    }


def _measure(data: Dataset, clique, sigma: float, rng: np.random.Generator) -> LinearMeasurement:
    x = data.project(clique).datavector()
    return LinearMeasurement(x + rng.normal(0, sigma, x.size), clique, sigma)


# mbi compiles variable elimination once per clique and model shape and keeps every copy: about
# 230 new programs a round on the person summary, 0.9 GB a round. Uncompiled it gives the same
# marginals, faster, and keeps nothing.
_eliminate = marginal_oracles.variable_elimination.__wrapped__


def _marginal(model, clique) -> np.ndarray:
    if model.marginals.supports(clique):
        return model.project(clique).datavector()
    return _eliminate(model.potentials, clique, float(model.total)).datavector()


def _worst(cands, answers, model, epsilon, sigma, rng):
    """The candidate the model fits worst, chosen with the exponential mechanism. A marginal's
    error drops by the error noise alone would leave, so large marginals are not favored just
    for having more cells. One person moves a marginal's L1 error by at most 1, times its
    weight."""
    keys = list(cands)
    errors = np.array([
        cands[cl] * (
            np.linalg.norm(answers[cl] - _marginal(model, cl), 1)
            - math.sqrt(2 / math.pi) * sigma * model.domain.size(cl)
        )
        for cl in keys
    ])  # fmt: skip
    sensitivity = max(abs(cands[cl]) for cl in keys)
    p = softmax(0.5 * epsilon / sensitivity * (errors - errors.max()))
    return keys[rng.choice(len(keys), p=p)]


def synthesize(table: pd.DataFrame, spec: Spec, release: Release) -> tuple[pd.DataFrame, list]:
    """A synthetic table with the spec's columns, and the privacy spend of each round. The
    number of rows is the model's total, from the noisy histograms."""
    # The model fit still keeps its compiled programs (11 GB over the person summary's two
    # releases); start each fit clean, so the trial's 20 redraws in one process don't add up.
    jax.clear_caches()
    columns = spec.columns
    names = [c.name for c in columns]
    codes = encode(table, columns)
    domain = Domain(names, [c.size for c in columns])
    data = Dataset({name: codes[:, j] for j, name in enumerate(names)}, domain)
    rng = np.random.default_rng(spec.seed)
    settings = spec.pgm

    cands = candidates(workload(spec))
    answers = {cl: data.project(cl).datavector() for cl in cands}
    rho = cdp_rho(release.epsilon, settings.delta)
    rounds = settings.rounds or 16 * len(names)
    sigma = math.sqrt(rounds / (2 * 0.9 * rho))
    epsilon = math.sqrt(8 * 0.1 * rho / rounds)

    oneway = [(name,) for name in names]
    measurements = [_measure(data, cl, sigma, rng) for cl in oneway]
    used = len(oneway) * 0.5 / sigma**2
    spend = [{"mechanism": "gaussian", "of": "one-way histograms", "columns": names,
              "rho": used, "sigma": sigma}]  # fmt: skip
    md = estimation.MirrorDescent()
    model = md.estimate(domain, measurements, iters=settings.round_iters)

    done = False
    while not done:
        if rho - used < 2 * (0.5 / sigma**2 + epsilon**2 / 8):
            # Not enough left for two more rounds: spend all of it on one last.
            remaining = rho - used
            sigma = math.sqrt(1 / (2 * 0.9 * remaining))
            epsilon = math.sqrt(8 * 0.1 * remaining)
            done = True
        used += epsilon**2 / 8 + 0.5 / sigma**2
        size_limit = settings.max_model_size * used / rho
        free = {
            sub
            for cl in model.cliques
            for r in range(1, len(cl) + 1)
            for sub in itertools.combinations(cl, r)
        }
        small = {
            cl: w
            for cl, w in cands.items()
            if cl in free
            or junction_tree.hypothetical_model_size(domain, list(model.cliques) + [cl])
            <= size_limit
        }
        cl = _worst(small, answers, model, epsilon, sigma, rng)
        measurements.append(_measure(data, cl, sigma, rng))
        before = _marginal(model, cl)
        potentials = model.potentials.expand(list(dict.fromkeys(m.clique for m in measurements)))
        model = md.estimate(domain, measurements, iters=settings.round_iters, warm_start=potentials)
        spend.append({"mechanism": "exponential and gaussian", "of": f"round {len(spend)}",
                      "pairs": [list(cl)], "rho": epsilon**2 / 8 + 0.5 / sigma**2,
                      "sigma": sigma})  # fmt: skip
        # Every 10th round: the trial's redraws fit AIM 40 times in one evaluation.
        if (len(spend) - 1) % 10 == 0:
            peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (
                2**30 if sys.platform == "darwin" else 2**20
            )
            size = junction_tree.hypothetical_model_size(domain, list(model.cliques))
            print(f"    round {len(spend) - 1}: {', '.join(cl)}; model {size:.1f} MB,"
                  f" peak memory {peak:.1f} GB", flush=True)  # fmt: skip
        after = _marginal(model, cl)
        if np.linalg.norm(after - before, 1) <= sigma * math.sqrt(2 / math.pi) * domain.size(cl):
            sigma /= 2
            epsilon *= 2

    model = md.estimate(domain, measurements, iters=settings.iters, warm_start=model.potentials)
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (
        2**30 if sys.platform == "darwin" else 2**20
    )
    print(f"    final fit after {len(spend) - 1} rounds: peak memory {peak:.1f} GB", flush=True)
    # mbi samples with numpy's global generator; seeding it makes the release repeatable.
    np.random.seed(spec.seed)
    sampled = model.synthetic_data()
    synthetic = np.stack([np.asarray(sampled.to_dict()[name]) for name in names], axis=1)
    return decode(synthetic, columns, rng), spend
