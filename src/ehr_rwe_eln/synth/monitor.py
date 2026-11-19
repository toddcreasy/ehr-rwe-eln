"""Scheduled privacy checks on released synthetic data.

The privacy attacks are seeded, so on the same source data and the same code they give the same
result. A release can drift only when one of those changes: the OMOP source is rebuilt or
written to (the ELN bridge adds lab results), or the synth code changes. So each run
fingerprints every spec's source table and the synth package's code, and does the work only when
a fingerprint differs from the last evaluated run's. Then it reruns the attacks on every release
with a holdout, saves the privacy reports, and records any release whose checks have drifted
past halfway to a copy of the training data (distribution.privacy_flags). Every run, skipped or
not, goes to synth.monitor_run.

It does not rerun trial parity, which redraws releases (minutes, and the VAE needs PyTorch) and
measures how a synthesizer behaves rather than drift. scripts/evaluate_synth.py does everything.

Usage:
    uv run python -m ehr_rwe_eln.synth.monitor --once     one check, then exit
    python -m ehr_rwe_eln.synth.monitor                   every MONITOR_INTERVAL_HOURS (Compose)
"""

import argparse
import hashlib
import logging
import time
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import psycopg
from psycopg.types.json import Jsonb

from ehr_rwe_eln.api.log_config import configure_logging
from ehr_rwe_eln.config import DatabaseSettings
from ehr_rwe_eln.synth.distribution import privacy_flags
from ehr_rwe_eln.synth.privacy import privacy_report
from ehr_rwe_eln.synth.release import load_release, save_report
from ehr_rwe_eln.synth.source import build_source, split
from ehr_rwe_eln.synth.spec import Spec

log = logging.getLogger(__name__)
CODE = Path(__file__).parent


class MonitorSettings(DatabaseSettings):
    log_level: str = "INFO"
    # How often the Compose monitor service checks, in hours.
    monitor_interval_hours: float = 24


def code_fingerprint() -> str:
    """A hash of the synth package's Python files: the code that builds sources and attacks."""
    digest = hashlib.sha256()
    for path in sorted(CODE.glob("*.py")):
        digest.update(path.name.encode() + path.read_bytes())
    return digest.hexdigest()[:16]


def table_fingerprint(table: pd.DataFrame) -> str:
    rows = pd.util.hash_pandas_object(table, index=False).to_numpy()
    return hashlib.sha256(rows.tobytes() + ",".join(table.columns).encode()).hexdigest()[:16]


def _last_fingerprints(con: psycopg.Connection) -> dict | None:
    found = con.execute(
        "SELECT fingerprints FROM synth.monitor_run WHERE NOT skipped ORDER BY run_id DESC LIMIT 1"
    ).fetchone()
    return found[0] if found else None


def run_once(con: psycopg.Connection) -> dict:
    """One check. Returns the run as recorded in synth.monitor_run; the caller commits."""
    started = datetime.now(UTC)
    releases = con.execute(
        "SELECT release_id, method, epsilon, spec FROM synth.release"
        " WHERE holdout_rows > 0 ORDER BY release_id"
    ).fetchall()
    code = code_fingerprint()
    sources, fingerprints = {}, {}
    for _, _, _, spec_json in releases:
        spec = Spec.model_validate(spec_json)
        key = spec.model_dump_json(include={"name", "columns", "holdout_fraction", "protocol"})
        if key not in sources:
            train, holdout = split(build_source(con, spec), spec)
            sources[key] = (train, holdout)
            fingerprints[spec.name] = {
                "source": table_fingerprint(pd.concat([train, holdout])),
                "code": code,
            }
    skipped = bool(releases) and fingerprints == _last_fingerprints(con)
    flags, checked, copies = [], 0, {}
    if not skipped:
        for release_id, method, epsilon, spec_json in releases:
            spec = Spec.model_validate(spec_json)
            if not spec.attacks_allowed:
                continue  # a controlled source without approval: the attacks may not run
            key = spec.model_dump_json(include={"name", "columns", "holdout_fraction", "protocol"})
            train, holdout = sources[key]
            if key not in copies:
                copies[key] = privacy_report(train, holdout, train, spec)
            copied = copies[key]
            privacy = privacy_report(train, holdout, load_release(con, release_id), spec)
            privacy["copy_of_training_data"] = {
                "distance_to_closest_record": copied["distance_to_closest_record"],
                "membership_inference": copied["membership_inference"],
                "attribute_gap_mean": copied["attribute_inference"]["gap_mean"],
                "attribute_gap_max": copied["attribute_inference"]["gap_max"],
            }
            save_report(con, release_id, "privacy", privacy)
            checked += 1
            flags += [
                {"release_id": release_id, "release": f"{method} {epsilon:g}", "flag": flag}
                for flag in privacy_flags(privacy)
            ]
    run = {
        "started_at": started,
        "finished_at": datetime.now(UTC),
        "fingerprints": fingerprints,
        "skipped": skipped,
        "releases_checked": checked,
        "flags": flags,
    }
    run["run_id"] = con.execute(
        "INSERT INTO synth.monitor_run (started_at, finished_at, fingerprints, skipped,"
        " releases_checked, flags) VALUES (%s, %s, %s, %s, %s, %s) RETURNING run_id",
        [started, run["finished_at"], Jsonb(fingerprints), skipped, checked, Jsonb(flags)],
    ).fetchone()[0]
    return run


def _report(run: dict) -> None:
    if run["skipped"]:
        log.info("privacy check skipped: sources and code unchanged", extra={"fields": {}})
    else:
        log.info(
            "privacy check done",
            extra={"fields": {"releases_checked": run["releases_checked"], "flags": run["flags"]}},
        )
    for flag in run["flags"]:
        log.warning("privacy drift: review this release", extra={"fields": flag})


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="check once and exit")
    args = parser.parse_args()
    settings = MonitorSettings()
    configure_logging(settings.log_level)
    while True:
        try:
            with settings.connect() as con:
                run = run_once(con)
                con.commit()
            _report(run)
        except Exception:
            # One failed check (the database restarting, say) must not stop the schedule.
            if args.once:
                raise
            log.exception("privacy check failed; trying again at the next interval")
        if args.once:
            return
        time.sleep(settings.monitor_interval_hours * 3600)


if __name__ == "__main__":
    main()
