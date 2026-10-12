"""Generate synthetic patients with Synthea as CSV under data/synthea/output/csv/.

Usage: uv run python scripts/generate_synthea.py [--patients 1000]

Seeds and the reference date are fixed, so the same arguments always produce the same patients.
Needs Java 17 or newer on PATH.
"""

import argparse
import hashlib
import subprocess  # noqa: S404
import urllib.request
from pathlib import Path

# 3.3.0 is the newest release OHDSI's ETL-Synthea (our correctness reference) supports.
VERSION = "3.3.0"
JAR_URL = (
    f"https://github.com/synthetichealth/synthea/releases/download/v{VERSION}/"
    "synthea-with-dependencies.jar"
)
JAR_SHA256 = "8ba04f7d73abadd5a377e41edf24c5c83935a1cb07c6d982cd5db731ef1cf445"
SEED = "42"
# Without a fixed reference date Synthea simulates up to today, so output drifts day to day.
REFERENCE_DATE = "20260101"

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "synthea"
JAR = DATA_DIR / f"synthea-{VERSION}.jar"
OUTPUT = DATA_DIR / "output"


def fetch_jar() -> None:
    if not JAR.exists():
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        print(f"downloading Synthea {VERSION}")
        urllib.request.urlretrieve(JAR_URL, JAR)
    digest = hashlib.sha256(JAR.read_bytes()).hexdigest()
    if digest != JAR_SHA256:
        raise SystemExit(f"{JAR} sha256 {digest} does not match the pinned {JAR_SHA256}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--patients", type=int, default=1000)
    args = parser.parse_args()

    # Refuse rather than mix files from two runs with different settings.
    if OUTPUT.exists():
        raise SystemExit(f"{OUTPUT} already exists; move it to the trash and rerun")
    fetch_jar()
    subprocess.run(  # noqa: S603
        [  # noqa: S607
            "java",
            "-jar",
            str(JAR),
            "-s", SEED,
            "-cs", SEED,
            "-p", str(args.patients),
            "-r", REFERENCE_DATE,
            "-e", REFERENCE_DATE,
            f"--exporter.baseDirectory={OUTPUT}",
            # One thread: parallel runs order rows and sum billing totals differently each time.
            "--generate.thread_pool_size=1",
            "--exporter.csv.export=true",
            "--exporter.fhir.export=false",
            "--exporter.hospital.fhir.export=false",
            "--exporter.practitioner.fhir.export=false",
            "Massachusetts",
        ],
        check=True,
        cwd=DATA_DIR,
    )  # fmt: skip
    for csv in sorted((OUTPUT / "csv").glob("*.csv")):
        rows = sum(1 for _ in csv.open()) - 1
        print(f"{csv.name:<28}{rows:>10,} rows")


if __name__ == "__main__":
    main()
