"""Target trial protocols in YAML.

A protocol writes down the randomized trial we would run, in the parts Hernán and Robins list
(Am J Epidemiol 2016;183:758): who is eligible, the two treatment strategies, when follow-up
starts (time zero), the outcome, how long follow-up lasts, and the causal contrast. The design is
a new-user, active-comparator trial with one time zero: the first day a person starts either
strategy, with eligibility checked on that same day, so no follow-up time is counted before
treatment begins.
"""

from pathlib import Path
from typing import Literal

import yaml
from pydantic import Field

from ehr_rwe_eln.cohort.spec import Strict

PROTOCOLS = Path(__file__).parent / "protocols"


class ConceptSet(Strict):
    concept_ids: list[int] = Field(min_length=1)
    include_descendants: bool = True


class Eligibility(Strict):
    # The condition being treated. Its first record must fall on or before time zero, and no more
    # than max_days_from_diagnosis before it: a trial of first treatment for a new diagnosis.
    diagnosis: ConceptSet
    max_days_from_diagnosis: int = Field(gt=0)
    min_age: int = Field(default=18, ge=0)
    # Records needed before time zero, so "no earlier use" and "no earlier outcome" are observable.
    prior_observation_days: int = Field(default=365, ge=0)


class Strategy(Strict):
    name: str
    drugs: ConceptSet


class Strategies(Strict):
    treatment: Strategy
    comparator: Strategy


class Outcome(Strict):
    name: str
    # Conditions. A person with any of them on or before time zero is not eligible.
    conditions: ConceptSet


class FollowUp(Strict):
    # Follow-up ends at the outcome, death, the end of the observation period, or max_days after
    # time zero, whichever comes first.
    max_days: int = Field(gt=0)


class Protocol(Strict):
    id: int = Field(gt=0)
    name: str
    description: str
    eligibility: Eligibility
    strategies: Strategies
    outcome: Outcome
    follow_up: FollowUp
    # Intention to treat: people stay in the arm they started in, whatever they take later.
    causal_contrast: Literal["intention_to_treat"] = "intention_to_treat"


def load_protocol(path: Path) -> Protocol:
    return Protocol.model_validate(yaml.safe_load(path.read_text()))
