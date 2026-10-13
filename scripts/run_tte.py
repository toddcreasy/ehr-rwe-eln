"""Build each target trial protocol's analysis table and print its attrition and arms.

Usage: uv run python scripts/run_tte.py
Module 4's larger population: DB_NAME=ehr_rwe_eln_tte uv run python scripts/run_tte.py

Demonstration on synthetic data only; no clinical claims.
"""

from ehr_rwe_eln.config import DatabaseSettings
from ehr_rwe_eln.tte.cohort import build_analysis_table
from ehr_rwe_eln.tte.protocol import PROTOCOLS, load_protocol


def main() -> None:
    with DatabaseSettings().connect() as con:
        for path in sorted(PROTOCOLS.glob("*.yaml")):
            protocol = load_protocol(path)
            attrition, table = build_analysis_table(con, protocol)
            print(f"{protocol.id}: {protocol.name}")
            for label, persons in attrition:
                print(f"  {persons:>8,}  {label}")
            strategies = protocol.strategies
            for arm, strategy in ((1, strategies.treatment), (0, strategies.comparator)):
                rows = table[table.arm == arm]
                print(
                    f"  {strategy.name:<12} {len(rows):>6,} persons  {rows.event.sum():>5,} events"
                    f"  median follow-up {rows.days.median():.0f} days"
                )
            print()
        con.rollback()


if __name__ == "__main__":
    main()
