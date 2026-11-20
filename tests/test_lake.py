import datetime

import pyarrow as pa
import pytest

from ehr_rwe_eln.cohort.lake import arrow_schema, batches, columns, compare, fingerprint_sql

# Every Postgres type the OMOP tables use, plus NULLs and an empty string.
TABLE_SQL = """
CREATE TEMP TABLE lake_t (
    id integer, big bigint, name varchar(50), note text, day date,
    at timestamp without time zone, value numeric
)
"""
ROWS = [
    (1, 10, "a", "x", datetime.date(2020, 1, 1), datetime.datetime(2020, 1, 1, 8, 30), 1.5),
    (2, 20, None, "", datetime.date(2021, 6, 15), None, None),
    (3, 30, "", None, None, datetime.datetime(2022, 2, 2, 23, 59, 59), 87.3),
    (4, 40, "dddd", "yy", datetime.date(2019, 12, 31), datetime.datetime(2019, 1, 1), -2.25),
    (5, None, "e", "z", datetime.date(2023, 3, 3), datetime.datetime(2023, 3, 3), 0),
]


@pytest.fixture
def lake_t(pg):
    pg.execute(TABLE_SQL)
    with pg.cursor() as cur:
        cur.executemany("INSERT INTO lake_t VALUES (%s, %s, %s, %s, %s, %s, %s)", ROWS)
    # Temp tables live in a per-session schema (pg_temp_N); information_schema reports that name.
    (schema,) = pg.execute(
        "SELECT nspname FROM pg_namespace WHERE oid = pg_my_temp_schema()"
    ).fetchone()
    return pg, schema


def test_arrow_schema_maps_every_omop_type(lake_t):
    con, temp = lake_t
    schema = arrow_schema(columns(con, temp, "lake_t"))
    assert schema.types == [
        pa.int32(),
        pa.int64(),
        pa.string(),
        pa.string(),
        pa.date32(),
        pa.timestamp("us"),
        pa.float64(),
    ]


def test_arrow_schema_refuses_unknown_types():
    with pytest.raises(ValueError, match=r"flag \(boolean\)"):
        arrow_schema([("id", "integer"), ("flag", "boolean")])


def test_batches_stream_every_row_and_keep_nulls_apart_from_empty_strings(lake_t):
    con, temp = lake_t
    out = list(batches(con, temp, "lake_t", batch_rows=2))
    assert [b.num_rows for b in out] == [2, 2, 1]
    table = pa.concat_tables(out)
    assert table.column("name").to_pylist() == ["a", None, "", "dddd", "e"]
    assert table.column("note").to_pylist() == ["x", "", None, "yy", "z"]
    assert table.column("value").to_pylist() == [1.5, None, 87.3, -2.25, 0.0]
    assert table.column("big").to_pylist() == [10, 20, 30, 40, None]


def test_fingerprint_on_postgres(lake_t):
    con, temp = lake_t
    query, labels = fingerprint_sql("lake_t", columns(con, temp, "lake_t"))
    row = dict(zip([label for label, _ in labels], con.execute(query).fetchone(), strict=True))
    assert row["rows"] == 5
    assert row["id: sum"] == 15
    assert row["big: non-null"] == 4
    assert row["name: total length"] == 1 + 0 + 4 + 1
    assert row["day: min"] == "2019-12-31"
    assert row["at: max"] == "2023-03-03 00:00:00"
    assert row["value: sum"] == pytest.approx(1.5 + 87.3 - 2.25)


def test_compare_flags_changes_and_tolerates_float_rounding():
    labels = [("rows", "int"), ("v: sum", "float"), ("d: min", "text")]
    assert compare(labels, [5, 0.1 + 0.2, "2020-01-01"], ["5", 0.3, "2020-01-01"]) == []
    assert compare(labels, [5, 1.0, "2020-01-01"], [4, 1.0, None]) == [
        "rows: source 5, lake 4",
        "d: min: source 2020-01-01, lake None",
    ]
