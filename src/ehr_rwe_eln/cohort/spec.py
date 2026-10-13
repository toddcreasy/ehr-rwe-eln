"""Cohort definitions in YAML, built into the OMOP cohort table.

A definition names a concept set, enters each person on their first event from that set (the
index date), applies inclusion rules in order, and sets an exit date. Building it writes rows to
cdm.cohort and returns an attrition table: how many people remain after each rule.
"""

import datetime
from pathlib import Path
from typing import Literal

import psycopg
import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

DEFINITIONS = Path(__file__).parent / "definitions"

# Domain -> (table, concept column, date column)
DOMAINS = {
    "condition": ("condition_occurrence", "condition_concept_id", "condition_start_date"),
    "drug": ("drug_exposure", "drug_concept_id", "drug_exposure_start_date"),
    "procedure": ("procedure_occurrence", "procedure_concept_id", "procedure_date"),
    "measurement": ("measurement", "measurement_concept_id", "measurement_date"),
    "observation": ("observation", "observation_concept_id", "observation_date"),
}


class Strict(BaseModel):
    # A misspelled key in the YAML is an error, not a silently ignored rule.
    model_config = ConfigDict(extra="forbid")


class Entry(Strict):
    domain: Literal["condition", "drug", "procedure", "measurement", "observation"]
    concept_ids: list[int] = Field(min_length=1)
    include_descendants: bool = True


class Inclusion(Strict):
    min_age: int | None = Field(default=None, ge=0)
    max_age: int | None = Field(default=None, ge=0)
    prior_observation_days: int = Field(default=0, ge=0)
    index_from: datetime.date | None = None
    index_to: datetime.date | None = None


class Exit(Strict):
    # end_of_observation: leave when the observation period ends.
    # fixed_days: leave `days` after the index date, or at the end of observation if sooner.
    strategy: Literal["end_of_observation", "fixed_days"] = "end_of_observation"
    days: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def days_match_strategy(self) -> Exit:
        if (self.strategy == "fixed_days") != (self.days is not None):
            raise ValueError("days is required for fixed_days and not allowed otherwise")
        return self


class CohortDefinition(Strict):
    id: int = Field(gt=0)
    name: str
    description: str
    entry: Entry
    inclusion: Inclusion = Inclusion()
    exit: Exit = Exit()


def load_definition(path: Path) -> CohortDefinition:
    return CohortDefinition.model_validate(yaml.safe_load(path.read_text()))


def build_cohort(con: psycopg.Connection, definition: CohortDefinition) -> list[tuple[str, int]]:
    """Replace this definition's rows in cdm.cohort. Returns (rule, persons remaining) pairs."""
    table, concept_column, date_column = DOMAINS[definition.entry.domain]
    ids = definition.entry.concept_ids
    concepts = "SELECT unnest(%s::integer[]) AS concept_id"
    if definition.entry.include_descendants:
        concepts += (
            " UNION SELECT descendant_concept_id FROM cdm.concept_ancestor "
            "WHERE ancestor_concept_id = ANY(%s::integer[])"
        )
    params = [ids, ids] if definition.entry.include_descendants else [ids]

    # First event per person, over all of their history, is the index date.
    con.execute("DROP TABLE IF EXISTS candidates")
    con.execute(
        f"""
        CREATE TEMP TABLE candidates AS
        WITH concepts AS ({concepts}),
        entry AS (
            SELECT person_id, min({date_column}) AS index_date FROM cdm.{table}
            WHERE {concept_column} IN (SELECT concept_id FROM concepts)
            GROUP BY person_id
        )
        SELECT e.person_id, e.index_date,
               extract(year FROM age(e.index_date, make_date(p.year_of_birth,
                   coalesce(p.month_of_birth, 1), coalesce(p.day_of_birth, 1))))::integer AS age,
               op.observation_period_start_date AS op_start,
               op.observation_period_end_date AS op_end
        FROM entry e
        JOIN cdm.person p USING (person_id)
        LEFT JOIN cdm.observation_period op
          ON op.person_id = e.person_id
         AND e.index_date BETWEEN op.observation_period_start_date
                              AND op.observation_period_end_date
        """,
        params,
    )

    rule = definition.inclusion
    rules = [("index date inside an observation period", "op_start IS NOT NULL", [])]
    if rule.prior_observation_days:
        rules.append(
            (
                f"at least {rule.prior_observation_days} days of prior observation",
                "index_date - op_start >= %s",
                [rule.prior_observation_days],
            )
        )
    if rule.min_age is not None:
        rules.append((f"age {rule.min_age} or older at index", "age >= %s", [rule.min_age]))
    if rule.max_age is not None:
        rules.append((f"age {rule.max_age} or younger at index", "age <= %s", [rule.max_age]))
    if rule.index_from is not None:
        rules.append(
            (f"index on or after {rule.index_from}", "index_date >= %s", [rule.index_from])
        )
    if rule.index_to is not None:
        rules.append((f"index on or before {rule.index_to}", "index_date <= %s", [rule.index_to]))

    attrition = [("first event in concept set", _count(con, "TRUE", []))]
    where, where_params = "TRUE", []
    for label, condition, values in rules:
        where += f" AND {condition}"
        where_params += values
        attrition.append((label, _count(con, where, where_params)))

    exit_date = "op_end"
    if definition.exit.strategy == "fixed_days":
        exit_date = f"least(index_date + {definition.exit.days}, op_end)"
    con.execute("DELETE FROM cdm.cohort WHERE cohort_definition_id = %s", [definition.id])
    con.execute(
        f"INSERT INTO cdm.cohort SELECT %s, person_id, index_date, {exit_date} "
        f"FROM candidates WHERE {where}",
        [definition.id, *where_params],
    )
    return attrition


def _count(con: psycopg.Connection, where: str, params: list) -> int:
    return con.execute(f"SELECT count(*) FROM candidates WHERE {where}", params).fetchone()[0]
