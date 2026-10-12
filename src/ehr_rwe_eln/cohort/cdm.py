"""OMOP CDM v5.4 schema and vocabulary loading in DuckDB."""

from pathlib import Path

import duckdb

DDL = Path(__file__).parent / "sql" / "omop_cdm_5.4_duckdb.sql"

# Athena names each download file after its table, in upper case: CONCEPT.csv and so on.
# Each table's key: when several downloads are loaded, a row whose key is already present is
# skipped, because every Athena bundle repeats the default vocabularies.
VOCABULARY_TABLES = {
    "concept": ("concept_id",),
    "vocabulary": ("vocabulary_id",),
    "domain": ("domain_id",),
    "concept_class": ("concept_class_id",),
    "concept_relationship": ("concept_id_1", "concept_id_2", "relationship_id"),
    "relationship": ("relationship_id",),
    "concept_synonym": ("concept_id", "concept_synonym_name", "language_concept_id"),
    "concept_ancestor": ("ancestor_concept_id", "descendant_concept_id"),
    "drug_strength": ("drug_concept_id", "ingredient_concept_id"),
}


def create_cdm(con: duckdb.DuckDBPyConnection, schema: str = "cdm") -> None:
    con.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
    # OHDSI's DuckDB DDL says NUMERIC, which DuckDB reads as DECIMAL(18,3): three decimal places
    # (a 0.0045 lab value becomes 0.005) and a 10^15 ceiling that Athena's drug_strength exceeds.
    ddl = DDL.read_text().replace(" NUMERIC ", " DOUBLE ")
    con.execute(ddl.replace("@cdmDatabaseSchema", schema))


def load_vocabulary(con: duckdb.DuckDBPyConnection, *vocab_dirs: Path, schema: str = "cdm") -> dict:
    """Load one or more Athena downloads into the CDM vocabulary tables. Returns row counts.

    The first folder wins: later ones only add rows whose key is not already loaded.
    """
    counts = {}
    for table, key in VOCABULARY_TABLES.items():
        columns = con.execute(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_schema = ? AND table_name = ? ORDER BY ordinal_position",
            [schema, table],
        ).fetchall()
        # Athena writes dates as YYYYMMDD; everything else casts implicitly on insert.
        select = ", ".join(
            f"strptime({name}, '%Y%m%d')::DATE" if dtype == "DATE" else name
            for name, dtype in columns
        )
        match = " AND ".join(f"t.{k} = s.{k}" for k in key)
        for vocab_dir in vocab_dirs:
            # Tab separated with no quoting: concept names contain bare double quotes.
            insert_sql = (
                f"INSERT INTO {schema}.{table} SELECT * FROM (SELECT {select} FROM read_csv(?, "
                "delim = '\t', header = true, quote = '', escape = '', all_varchar = true)) s "
                f"WHERE NOT EXISTS (SELECT 1 FROM {schema}.{table} t WHERE {match})"
            )
            con.execute(insert_sql, [str(vocab_dir / f"{table.upper()}.csv")])
        count_sql = f"SELECT count(*) FROM {schema}.{table}"
        counts[table] = con.execute(count_sql).fetchone()[0]
    return counts
