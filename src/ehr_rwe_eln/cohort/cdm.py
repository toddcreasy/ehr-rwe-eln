"""OMOP CDM v5.4 schema and vocabulary loading in PostgreSQL."""

from pathlib import Path

import psycopg

DDL = Path(__file__).parent / "sql" / "omop_cdm_5.4_postgresql.sql"
PRIMARY_KEYS, FOREIGN_KEYS, INDICES = (
    DDL.with_name(f"omop_cdm_5.4_postgresql_{part}.sql")
    for part in ("primary_keys", "constraints", "indices")
)

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

# Tab separated with no quoting: concept names contain bare double quotes, so the quote
# character is set to one that never appears. Empty fields load as NULL.
ATHENA_COPY = "FORMAT csv, DELIMITER E'\\t', QUOTE E'\\x01', HEADER true"


def create_cdm(con: psycopg.Connection, schema: str = "cdm") -> None:
    con.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
    con.execute(DDL.read_text().replace("@cdmDatabaseSchema", schema))


def add_constraints(con: psycopg.Connection, schema: str = "cdm") -> None:
    """Primary keys, foreign keys, and indices. Run after loading: checking each row as it is
    inserted would slow the vocabulary load and the ETL, and a violation fails here instead."""
    con.execute(PRIMARY_KEYS.read_text().replace("@cdmDatabaseSchema", schema))
    # v5.4.3 leaves this key out of its primary key file, yet foreign keys point at it.
    con.execute(f"ALTER TABLE {schema}.vocabulary ADD PRIMARY KEY (vocabulary_id)")
    con.execute(FOREIGN_KEYS.read_text().replace("@cdmDatabaseSchema", schema))
    con.execute(INDICES.read_text().replace("@cdmDatabaseSchema", schema))


def load_vocabulary(con: psycopg.Connection, *vocab_dirs: Path, schema: str = "cdm") -> dict:
    """Load one or more Athena downloads into the CDM vocabulary tables. Returns row counts.

    The first folder wins: later ones only add rows whose key is not already loaded.
    """
    counts = {}
    for table, key in VOCABULARY_TABLES.items():
        columns = {
            row[0]
            for row in con.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = %s AND table_name = %s",
                [schema, table],
            )
        }
        match = " AND ".join(f"t.{k} = s.{k}" for k in key)
        for vocab_dir in vocab_dirs:
            path = vocab_dir / f"{table.upper()}.csv"
            with path.open("rb") as f:
                header = f.readline().decode().rstrip("\r\n").split("\t")
                if not set(header) <= columns:
                    raise ValueError(f"{path}: unexpected columns {set(header) - columns}")
                f.seek(0)
                con.execute(f"CREATE TEMP TABLE staging (LIKE {schema}.{table})")
                with con.cursor().copy(
                    f"COPY staging ({', '.join(header)}) FROM STDIN ({ATHENA_COPY})"
                ) as copy:
                    while data := f.read(1 << 20):
                        copy.write(data)
            con.execute(
                f"INSERT INTO {schema}.{table} SELECT * FROM staging s "
                f"WHERE NOT EXISTS (SELECT 1 FROM {schema}.{table} t WHERE {match})"
            )
            con.execute("DROP TABLE staging")
        con.execute(f"ANALYZE {schema}.{table}")
        count_sql = f"SELECT count(*) FROM {schema}.{table}"
        counts[table] = con.execute(count_sql).fetchone()[0]
    return counts
