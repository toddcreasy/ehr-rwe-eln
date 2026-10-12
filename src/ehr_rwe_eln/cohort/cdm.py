"""OMOP CDM v5.4 schema and vocabulary loading in DuckDB."""

from pathlib import Path

import duckdb

DDL = Path(__file__).parent / "sql" / "omop_cdm_5.4_duckdb.sql"

# Athena names each download file after its table, in upper case: CONCEPT.csv and so on.
VOCABULARY_TABLES = (
    "concept",
    "vocabulary",
    "domain",
    "concept_class",
    "concept_relationship",
    "relationship",
    "concept_synonym",
    "concept_ancestor",
    "drug_strength",
)


def create_cdm(con: duckdb.DuckDBPyConnection, schema: str = "cdm") -> None:
    con.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
    con.execute(DDL.read_text().replace("@cdmDatabaseSchema", schema))


def load_vocabulary(con: duckdb.DuckDBPyConnection, vocab_dir: Path, schema: str = "cdm") -> dict:
    """Load Athena vocabulary CSVs into the CDM vocabulary tables. Returns row counts."""
    counts = {}
    for table in VOCABULARY_TABLES:
        path = vocab_dir / f"{table.upper()}.csv"
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
        # Tab separated with no quoting: concept names contain bare double quotes. Identifiers
        # come from VOCABULARY_TABLES and the catalog, never from input; values are bound.
        insert_sql = (
            f"INSERT INTO {schema}.{table} SELECT {select} FROM read_csv(?, delim = '\t', "  # noqa: S608
            "header = true, quote = '', escape = '', all_varchar = true)"
        )
        con.execute(insert_sql, [str(path)])
        count_sql = f"SELECT count(*) FROM {schema}.{table}"  # noqa: S608
        counts[table] = con.execute(count_sql).fetchone()[0]
    return counts
