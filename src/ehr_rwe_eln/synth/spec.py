"""Synthetic release specs in YAML: the source table's columns, each column's domain, the
Bayesian network structure, and the releases to make.

Every domain (category list, numeric bounds and bins) comes from the spec, never from the data.
A range read from the data would itself leak: the top bin edge would be the oldest person's age.
The structure is declared too. Learning it from the data would spend privacy budget; declaring
it costs none and is easy to explain to a reviewer.
"""

from pathlib import Path
from typing import Literal, cast

import yaml
from pydantic import Field, model_validator

from ehr_rwe_eln.cohort.spec import Strict
from ehr_rwe_eln.tte.protocol import ConceptSet

SPECS = Path(__file__).parent / "specs"
# A column's parents and the column together index one noisy histogram; more parents means
# more cells sharing the same people, so each count gets noisier relative to its size.
MAX_PARENTS = 2


class Numeric(Strict):
    low: float
    high: float
    bins: int = Field(gt=0)
    # Whole numbers when decoded (age in years).
    integer: bool = False
    # The last bin means "its low edge or more" and decodes to that edge, never a value
    # inside it: age 90 stands for 90 or older, as HIPAA Safe Harbor allows (45 CFR
    # 164.514(b)(2)(i)(C)).
    open_top: bool = False

    @model_validator(mode="after")
    def _ordered(self) -> Numeric:
        if self.low >= self.high:
            raise ValueError("low must be below high")
        return self


class Column(Strict):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    # Where the value comes from in OMOP: exactly one of these.
    demographic: Literal["age", "sex", "race", "ethnicity", "deceased"] | None = None
    condition: ConceptSet | None = None  # 1 if ever recorded, else 0
    drug: ConceptSet | None = None  # 1 if ever exposed, else 0
    measurement: ConceptSet | None = None  # the latest value; missing when never measured
    # A column of a module 3 protocol's analysis table, taken as is (specs with a protocol).
    analysis: str | None = None
    # Whether an analysis column can be missing (a measurement covariate with no value in its
    # lookback window). OMOP measurements always allow it.
    allow_missing: bool = False
    # The domain: categories, or numeric bounds and bins. Flags default to [0, 1].
    categories: list[str | int] | None = None
    numeric: Numeric | None = None
    parents: list[str] = Field(default=[], max_length=MAX_PARENTS)

    @model_validator(mode="after")
    def _one_source_and_a_domain(self) -> Column:
        sources = [self.demographic, self.condition, self.drug, self.measurement, self.analysis]
        if sum(s is not None for s in sources) != 1:
            raise ValueError(f"{self.name}: give exactly one source")
        flag = self.condition or self.drug or self.demographic == "deceased"
        if flag and self.categories is None:
            self.categories = [0, 1]
        if self.measurement and self.numeric is None:
            raise ValueError(f"{self.name}: a measurement needs numeric bounds")
        if (self.categories is None) == (self.numeric is None):
            raise ValueError(f"{self.name}: give categories or numeric, one and not both")
        return self

    @property
    def missing_allowed(self) -> bool:
        return self.measurement is not None or self.allow_missing

    @property
    def size(self) -> int:
        """Number of codes: categories, or numeric bins plus one for missing if allowed."""
        if self.numeric is None:
            return len(cast(list, self.categories))
        return self.numeric.bins + self.missing_allowed


class Release(Strict):
    # bayes_net measures each column with its parents; independent measures each column alone,
    # a baseline that keeps every marginal and loses every relationship between columns. vae
    # trains a variational autoencoder with DP-SGD. mst picks its own pairs of columns and fits
    # a graphical model to their noisy histograms (synth/mst.py); it ignores parents. aim does
    # the same in rounds, aimed at the spec's workload (synth/aim.py).
    method: Literal["bayes_net", "independent", "vae", "mst", "aim"]
    # The total privacy budget for this release: split evenly across the histograms, or for
    # vae, 1% to the noisy row count and the rest to training; for mst and aim, with
    # pgm.delta.
    epsilon: float = Field(gt=0)


class VaeSettings(Strict):
    """Training settings for vae releases. Fixed in the spec, not tuned against the source:
    every training run on private data spends privacy, tuning runs included."""

    hidden: int = Field(default=128, gt=0)
    latent: int = Field(default=16, gt=0)
    epochs: int = Field(default=20, gt=0)
    batch_size: int = Field(default=512, gt=0)
    learning_rate: float = Field(default=1e-3, gt=0)
    # DP-SGD clips each person's gradient to this length before adding noise.
    max_grad_norm: float = Field(default=1.0, gt=0)
    # DP-SGD's guarantee is (epsilon, delta): delta is the small chance it does not hold.
    # Keep it well below one over the number of people.
    delta: float = Field(default=1e-5, gt=0, lt=1)
    # A column to condition on (a conditional VAE). Its histogram is measured with noise, from
    # 10% of the budget; the decoder takes the column as an input instead of generating it, and
    # releases draw it from the noisy histogram. Without it, every column comes from the decoder.
    condition: str | None = None


class PgmSettings(Strict):
    """Settings for mst and aim releases (private-pgm's mechanisms). Fixed in the spec, not
    tuned."""

    # MST's guarantee is (epsilon, delta), like DP-SGD's. The authors' default; far below one
    # over the number of people.
    delta: float = Field(default=1e-9, gt=0, lt=1)
    # Mirror descent steps for fitting the final model. More fits the noisy histograms closer.
    iters: int = Field(default=10_000, gt=0)
    # aim only. The rounds it plans for, which set each round's share of the budget (the
    # authors' default, 16 per column, when unset); halving the noise uses them up sooner.
    rounds: int | None = Field(default=None, gt=0)
    # Mirror descent steps for the refit after each round (the authors' 1,000).
    round_iters: int = Field(default=1000, gt=0)
    # The largest model, in megabytes, a round may grow it to; the limit rises from 0 to this
    # as the budget is spent. The authors' default.
    max_model_size: float = Field(default=80, gt=0)


class Query(Strict):
    """A marginal an analyst will ask for: the counts of every combination of these columns."""

    columns: list[str] = Field(min_length=1, max_length=3)
    # How much aim favors getting it right; every pair of columns not listed has weight 1.
    weight: float = Field(default=1, gt=0)


class Spec(Strict):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    description: str
    # Where the source comes from, stated by every spec so no guard can be skipped by omission.
    # synthetic: generated data with no participants (Synthea, here). controlled: a
    # controlled-access source such as a dbGaP study, used under a data access request; then
    # seeds are refused, the privacy attacks need attack_approval, and exports need the
    # recipient to be an approved user (docs/nih_hhs_requirements.md, items 2 and 7).
    source_access: Literal["synthetic", "controlled"]
    # Where the data access request approves the privacy attacks, which on a real source are in
    # method attempts to identify participants. Without it they do not run on controlled data.
    attack_approval: str | None = None
    # The users and teams named in the data access request. A release from controlled data is
    # derived data and goes only to them, unless dac_sharing_approval cites the DAC decision
    # that allows wider sharing.
    approved_users: list[str] = []
    dac_sharing_approval: str | None = None
    # The source's data use limitations: the consent-based terms that say what its data may be
    # used for (dbGaP's "general research use", "disease-specific", and so on). A synthetic
    # release is derived data and inherits them, so they are required and printed on every
    # data card. For a source with none, say so and why.
    data_use_limitations: str = Field(min_length=1)
    # Seeds the noise and the sampling, so a release can be remade exactly. Only for sources
    # that are already synthetic: anyone who knows the seed can regenerate the noise and
    # subtract it. Leave it null for real data, and the noise comes from a secure generator.
    seed: int | None = None
    releases: list[Release] = Field(min_length=1)
    vae: VaeSettings = VaeSettings()
    pgm: PgmSettings = PgmSettings()
    # The marginals aim releases are aimed at: the queries the trial emulation and the cohorts
    # will run on the release. Other methods ignore it.
    workload: list[Query] = []
    # The share of people kept out of every release, to evaluate against: real people the
    # synthesizer never saw (utility tests, and non-members for membership inference).
    # 0 keeps no holdout: for a spec judged against the data it learned from (trial parity).
    holdout_fraction: float = Field(default=0.3, ge=0, lt=1)
    # A module 3 protocol (its file name without .yaml). When set, the source is that
    # protocol's analysis table, and every column is an analysis column.
    protocol: str | None = None
    # A 0/1 column to predict in the utility test (train on synthetic, test on real).
    utility_target: str | None = None
    # Columns to report fidelity within, one group per category or numeric bin: a release can
    # match its source overall and still distort a small group. A list of two or three columns
    # is an intersection, one group per combination (age 70 to 79 and Black, for example).
    subgroups: list[str | list[str]] = []
    columns: list[Column] = Field(min_length=1)

    @model_validator(mode="after")
    def _parents_come_first(self) -> Spec:
        seen: set[str] = set()
        for column in self.columns:
            if column.name in seen:
                raise ValueError(f"duplicate column {column.name}")
            for parent in column.parents:
                if parent not in seen:
                    raise ValueError(f"{column.name}: parent {parent} must be listed before it")
            seen.add(column.name)
        if self.pgm.rounds is not None and self.pgm.rounds < len(self.columns):
            # AIM's one-way histograms cost a round's share each; fewer rounds than columns
            # would spend more than the whole budget on them.
            raise ValueError(f"pgm.rounds must be at least the {len(self.columns)} columns")
        if self.vae.condition is not None and self.vae.condition not in seen:
            raise ValueError(f"vae.condition {self.vae.condition} is not a column")
        for method in ("mst", "aim"):
            if self.seed is None and any(r.method == method for r in self.releases):
                # Their Gaussian noise comes from numpy, which is not safe for real data:
                # floating point noise can leak the value it hides. Refuse rather than release.
                raise ValueError(
                    f"{method} releases need a seed: their noise is numpy's, not secure noise"
                    " for real data"
                )
        queried: set[frozenset[str]] = set()
        for query in self.workload:
            if len(set(query.columns)) != len(query.columns):
                raise ValueError(f"workload query {query.columns} repeats a column")
            if frozenset(query.columns) in queried:
                raise ValueError(f"workload query {query.columns} is listed twice")
            queried.add(frozenset(query.columns))
            for name in query.columns:
                if name not in seen:
                    raise ValueError(f"workload column {name} is not a column")
        if self.seed is None and any(r.method == "vae" for r in self.releases):
            # Unseeded means real data, which needs Opacus's secure noise. That needs
            # torchcsprng, last released in 2021 for torch 1.8 and Python 3.9: not installable
            # here. Refuse rather than train on ordinary noise.
            raise ValueError(
                "vae releases need a seed: secure noise for real data needs torchcsprng,"
                " which does not install on this stack"
            )
        if any((c.analysis is not None) != (self.protocol is not None) for c in self.columns):
            raise ValueError("with a protocol every column is an analysis column; without, none")
        if self.utility_target is not None:
            target = next((c for c in self.columns if c.name == self.utility_target), None)
            if target is None or target.categories != [0, 1]:
                raise ValueError(f"utility_target {self.utility_target} must be a 0/1 column")
        for entry in self.subgroups:
            names = [entry] if isinstance(entry, str) else entry
            if isinstance(entry, list) and not 2 <= len(set(entry)) == len(entry) <= 3:
                raise ValueError(f"intersection {entry} needs two or three different columns")
            for name in names:
                if name not in seen:
                    raise ValueError(f"subgroup {name} is not a column")
        if self.source_access == "controlled":
            if self.seed is not None:
                raise ValueError("a controlled source needs secure noise: leave seed unset")
            if not self.approved_users and self.dac_sharing_approval is None:
                raise ValueError(
                    "a controlled source needs approved_users from the data access request,"
                    " or a dac_sharing_approval"
                )
        return self

    @property
    def attacks_allowed(self) -> bool:
        return self.source_access == "synthetic" or bool(self.attack_approval)

    def may_receive(self, recipient: str) -> bool:
        """Whether a release from this spec may go to recipient (item 7)."""
        return (
            self.source_access == "synthetic"
            or self.dac_sharing_approval is not None
            or recipient in self.approved_users
        )


def load_spec(path: Path) -> Spec:
    return Spec.model_validate(yaml.safe_load(path.read_text()))
