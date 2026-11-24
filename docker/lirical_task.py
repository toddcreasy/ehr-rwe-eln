"""The LIRICAL task: run a slice of people, phenotype only, and store their disease rankings.

Usage (the Fargate task's command, from scripts/run_lirical.py):
  lirical_task.py run --prefix studies/<id>

Runs inside the lirical container (docker/lirical.Dockerfile), so it uses only the standard
library and boto3. Every S3 key is under $LIRICAL_BUCKET.

Reads <prefix>/input/people.json (sample_id, sex, hpo_ids for each person) and runs LIRICAL's
prioritize command once per person, $LIRICAL_WORKERS at a time (LIRICAL has no batch mode).
Writes results.zip (one <sample_id>.tsv per person), lirical.log, and the image's SHA256SUMS of
LIRICAL's data to <prefix>/output/, also when some people fail.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import boto3

JAR = "/opt/lirical/lirical-cli.jar"
DATA = Path("/opt/lirical/data")
WORK = Path.home() / "work"
SEX = {"female": "FEMALE", "male": "MALE"}


def prioritize(person: dict, heap: int) -> tuple[str, int, str]:
    sample = person["sample_id"]
    if not re.fullmatch(r"SAMP-\d{5}", sample):
        return sample, 2, "bad sample ID"
    terms = person["hpo_ids"]
    if not terms or not all(re.fullmatch(r"HP:\d{7}", t) for t in terms):
        return sample, 2, "no HPO terms, or a malformed one"
    command = [
        "java",
        f"-Xmx{heap}g",
        "-jar",
        JAR,
        "prioritize",
        "-d",
        str(DATA),
        "-p",
        ",".join(terms),
        "--sex",
        SEX.get(person["sex"], "UNKNOWN"),
        "-o",
        str(WORK / "results"),
        "-f",
        "tsv",
        "-x",
        sample,
    ]
    done = subprocess.run(command, capture_output=True, text=True)  # noqa: S603  (fixed command)
    output = done.stdout + done.stderr
    # Java prints the error first and the stack after it: keep both ends.
    if len(output) > 6000:
        output = output[:5000] + "\n[...]\n" + output[-1000:]
    return sample, done.returncode, output


def run(s3, bucket: str, prefix: str) -> None:
    (WORK / "results").mkdir(parents=True, exist_ok=True)
    s3.download_file(bucket, f"{prefix}/input/people.json", str(WORK / "people.json"))
    people = json.loads((WORK / "people.json").read_text())
    workers = int(os.environ.get("LIRICAL_WORKERS", "4"))
    heap = int(os.environ.get("LIRICAL_HEAP_GB", "3"))
    print(f"{len(people)} people, {workers} at a time", flush=True)

    failed = []
    with (WORK / "lirical.log").open("w") as log, ThreadPoolExecutor(workers) as pool:
        for i, (sample, code, output) in enumerate(
            pool.map(lambda p: prioritize(p, heap), people), 1
        ):
            if code != 0:
                failed.append(sample)
                log.write(f"== {sample}: exit {code}\n{output}\n")
            if i % 100 == 0:
                print(f"{i} done, {len(failed)} failed", flush=True)
        log.write(f"{len(people)} people, {len(failed)} failed\n")

    results = sorted((WORK / "results").glob("*.tsv"))
    with zipfile.ZipFile(WORK / "results.zip", "w", zipfile.ZIP_DEFLATED) as z:
        for path in results:
            z.write(path, path.name)
    s3.upload_file(str(WORK / "results.zip"), bucket, f"{prefix}/output/results.zip")
    s3.upload_file(str(WORK / "lirical.log"), bucket, f"{prefix}/output/lirical.log")
    s3.upload_file(str(DATA / "SHA256SUMS"), bucket, f"{prefix}/output/SHA256SUMS")
    print(f"{len(results)} result files, {len(failed)} failed", flush=True)
    sys.exit(1 if failed else 0)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["run"])
    parser.add_argument("--prefix", required=True)
    args = parser.parse_args()
    run(boto3.client("s3"), os.environ["LIRICAL_BUCKET"], args.prefix.rstrip("/"))


if __name__ == "__main__":
    main()
