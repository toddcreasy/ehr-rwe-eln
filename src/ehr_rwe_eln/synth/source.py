"""The source table a synthesizer learns from: one row per person, one column per spec column.

person_id is the index, used to join and to split; synthesizers read only the spec's columns.
"""

import hashlib

import pandas as pd
import psycopg

from ehr_rwe_eln.synth.spec import Spec
from ehr_rwe_eln.tte.cohort import build_analysis_table, concept_set_sql
from ehr_rwe_eln.tte.covariates import add_covariates
from ehr_rwe_eln.tte.protocol import PROTOCOLS, load_protocol

DEMOGRAPHICS_SQL = """
SELECT p.person_id,
       extract(year FROM op.end_date)::integer - p.year_of_birth AS age,
       CASE p.gender_concept_id WHEN 8532 THEN 'female' WHEN 8507 THEN 'male' END AS sex,
       p.race_source_value AS race,
       p.ethnicity_source_value AS ethnicity,
       EXISTS (SELECT FROM cdm.death d WHERE d.person_id = p.person_id)::integer AS deceased
FROM cdm.person p
JOIN (
    SELECT person_id, max(observation_period_end_date) AS end_date
    FROM cdm.observation_period GROUP BY person_id
) op USING (person_id)
ORDER BY p.person_id
"""

# 1 for everyone with a record of the concepts; everyone else gets 0.
EVER_SQL = """
SELECT DISTINCT person_id, 1 FROM cdm.{table} WHERE {concept} IN ({concepts})
"""
# The latest value; everyone without one is missing.
LATEST_SQL = """
SELECT DISTINCT ON (person_id) person_id, value_as_number
FROM cdm.measurement
WHERE value_as_number IS NOT NULL AND measurement_concept_id IN ({concepts})
ORDER BY person_id, measurement_date DESC, measurement_id DESC
"""


def build_analysis_source(con: psycopg.Connection, spec: Spec) -> pd.DataFrame:
    """The spec's protocol's analysis table (its eligible people, with covariates), indexed by
    person_id, as the spec's columns."""
    protocol = load_protocol(PROTOCOLS / f"{spec.protocol}.yaml")
    _, table = build_analysis_table(con, protocol)
    table = add_covariates(con, protocol, table).set_index("person_id").sort_index()
    return pd.DataFrame({c.name: table[c.analysis] for c in spec.columns})


def build_source(con: psycopg.Connection, spec: Spec) -> pd.DataFrame:
    """Every person with an observation period, indexed and ordered by person_id, as the spec's
    columns. With a protocol, that protocol's analysis table instead."""
    if spec.protocol is not None:
        return build_analysis_source(con, spec)
    base = pd.DataFrame(
        con.execute(DEMOGRAPHICS_SQL).fetchall(),
        columns=["person_id", "age", "sex", "race", "ethnicity", "deceased"],
    )
    out = pd.DataFrame(index=pd.Index(base["person_id"], name="person_id"))
    base = base.set_index("person_id", drop=False)
    for column in spec.columns:
        if column.demographic:
            out[column.name] = base[column.demographic]
            continue
        if column.measurement:
            concepts, params = concept_set_sql(column.measurement)
            sql = LATEST_SQL.format(concepts=concepts)
        else:
            table, concept, concept_set = (
                ("condition_occurrence", "condition_concept_id", column.condition)
                if column.condition
                else ("drug_exposure", "drug_concept_id", column.drug)
            )
            concepts, params = concept_set_sql(concept_set)
            sql = EVER_SQL.format(table=table, concept=concept, concepts=concepts)
        values = dict(con.execute(sql, params).fetchall())
        mapped = base["person_id"].map(values)
        if column.measurement:
            out[column.name] = mapped.astype(float)
        else:
            out[column.name] = mapped.fillna(0).astype(int)
    return out


def split(source: pd.DataFrame, spec: Spec) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(training, holdout). A person is held out when a hash of the spec name and their
    person_id falls below holdout_fraction: the same person always lands on the same side, and
    there is nothing to store or keep secret."""
    position = source.index.map(
        lambda person_id: (
            int(hashlib.sha256(f"{spec.name}:{person_id}".encode()).hexdigest()[:12], 16) / 16**12
        )
    )
    held = position < spec.holdout_fraction
    return source[~held], source[held]
