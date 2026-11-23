"""Check that the OMOP readers give the same answers from the lake as from the staging Postgres.

Usage: uv run python scripts/compare_omop_sources.py

Runs the real module code on both sources and requires identical results, column types included:
- every trial emulation protocol: its attrition table and its analysis table with covariates;
- every negative control of every protocol: its analysis table with covariates;
- every synthetic data spec: the source table its synthesizers learn from.
Exits 1 on any difference. The lake side goes through Redshift, so this costs some RPU time.
"""

import sys

import pandas as pd

from ehr_rwe_eln.config import DatabaseSettings, LakeSettings
from ehr_rwe_eln.omop import RedshiftSession
from ehr_rwe_eln.synth.source import build_source
from ehr_rwe_eln.synth.spec import SPECS, load_spec
from ehr_rwe_eln.tte.cohort import build_analysis_table
from ehr_rwe_eln.tte.covariates import add_covariates
from ehr_rwe_eln.tte.protocol import PROTOCOLS, load_protocol


def same(label: str, staging: pd.DataFrame, lake: pd.DataFrame) -> bool:
    try:
        pd.testing.assert_frame_equal(staging, lake, check_dtype=True, check_exact=True)
    except AssertionError as exc:
        print(f"  DIFFER  {label}\n{exc}")
        return False
    print(f"  OK      {label}: {len(staging):,} rows x {staging.shape[1]} columns")
    return True


def trial_table(con, protocol, cdm: str) -> tuple[list, pd.DataFrame]:
    attrition, table = build_analysis_table(con, protocol, cdm)
    return attrition, add_covariates(con, protocol, table, cdm)


def main() -> None:
    settings = LakeSettings()
    lake, lake_cdm = RedshiftSession(settings), settings.redshift_lake_schema
    staging = DatabaseSettings().connect()
    ok = True

    # The with block ends the Redshift session, which is billed while open.
    with lake:
        for path in sorted(PROTOCOLS.glob("*.yaml")):
            protocol = load_protocol(path)
            print(f"protocol {protocol.id}: {protocol.name}")
            a_staging, t_staging = trial_table(staging, protocol, "cdm")
            a_lake, t_lake = trial_table(lake, protocol, lake_cdm)
            if a_staging == a_lake:
                eligible, steps = a_staging[-1][1], len(a_staging)
                print(f"  OK      attrition: {eligible:,} eligible after {steps} steps")
            else:
                print(f"  DIFFER  attrition\n    staging {a_staging}\n    lake    {a_lake}")
                ok = False
            ok &= same("analysis table with covariates", t_staging, t_lake)
            for outcome in protocol.negative_controls:
                control = protocol.model_copy(update={"outcome": outcome})
                ok &= same(
                    f"negative control {outcome.name}",
                    trial_table(staging, control, "cdm")[1],
                    trial_table(lake, control, lake_cdm)[1],
                )

        for path in sorted(SPECS.glob("*.yaml")):
            spec = load_spec(path)
            print(f"synthetic data spec {spec.name}")
            ok &= same(
                "source table",
                build_source(staging, spec, "cdm"),
                build_source(lake, spec, lake_cdm),
            )

    staging.rollback()
    if not ok:
        sys.exit("the lake and staging give different results")
    print("lake and staging give identical results")


if __name__ == "__main__":
    main()
