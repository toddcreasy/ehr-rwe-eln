"""Round-trip check against the Compose Postgres: pgvector insert + cosine similarity.

Runs in one transaction on a temp table and rolls back, so it leaves nothing behind.

    uv run python scripts/db_check.py
"""

from ehr_rwe_eln.config import DatabaseSettings


def main() -> None:
    with DatabaseSettings().connect(connect_timeout=5) as conn:
        print(conn.execute("SELECT version()").fetchone()[0])
        vector = "SELECT extversion FROM pg_extension WHERE extname = 'vector'"
        print(conn.execute(vector).fetchall())
        conn.execute("CREATE TEMP TABLE db_check (id int, label text, embedding vector(3))")
        conn.execute(
            "INSERT INTO db_check VALUES "
            "(1, 'same direction', '[2,4,6]'), "
            "(2, 'close', '[1,2,3.5]'), "
            "(3, 'opposite', '[-1,-2,-3]')"
        )
        rows = conn.execute(
            "SELECT id, label, 1 - (embedding <=> '[1,2,3]') AS cosine_similarity "
            "FROM db_check ORDER BY embedding <=> '[1,2,3]'"
        ).fetchall()
        print("query vector [1,2,3]:")
        for id_, label, similarity in rows:
            print(f"  {id_} {label:<15} cosine_similarity={similarity:.4f}")
        conn.rollback()


if __name__ == "__main__":
    main()
