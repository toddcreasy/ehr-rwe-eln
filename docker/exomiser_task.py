"""The Exomiser task: fetch a data release into S3 once, or run a batch of analyses.

Usage (the Fargate task's command, from scripts/run_exomiser.py):
  exomiser_task.py fetch --release 2609
  exomiser_task.py run --release 2609 --prefix studies/<id>

Runs inside the exomiser container (docker/exomiser.Dockerfile), so it uses only the standard
library and boto3. Every S3 key is under $EXOMISER_BUCKET.

fetch: downloads <release>_hg38.zip and <release>_phenotype.zip from the address Exomiser's
release notes give, checks each against the size the server reports and tests the archive
(Exomiser publishes no checksums), then stores it under reference/exomiser/<release>/ with its
SHA-256 in the object's metadata.

run: copies both zips to the task's disk, checks each against that SHA-256, unpacks them, then
runs Exomiser's batch command on <prefix>/input/inputs.zip (an analysis file, one sample file and
VCF per person, and the batch file listing them) and writes results.zip and exomiser.log to
<prefix>/output/, also when a step fails.
"""

import argparse
import hashlib
import os
import re
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

import boto3
from boto3.s3.transfer import TransferConfig

SOURCE = "https://g-879a9f.f5dc97.75bc.dn.glob.us/data"
PARTS = ["hg38", "phenotype"]
JAR = "/opt/exomiser/exomiser-cli.jar"
HOME = Path.home()
DATA, WORK = HOME / "data", HOME / "work"
TRANSFER = TransferConfig(multipart_chunksize=64 * 1024 * 1024, max_concurrency=16)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        while block := f.read(16 * 1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def fetch(s3, bucket: str, release: str) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    for part in PARTS:
        name = f"{release}_{part}.zip"
        path = DATA / name
        url = f"{SOURCE}/{name}"
        print(f"downloading {url}", flush=True)
        # The server sends the size only to HEAD; GET comes chunked, with no Content-Length.
        with urllib.request.urlopen(urllib.request.Request(url, method="HEAD")) as response:  # noqa: S310  (fixed https host)
            expected = int(response.headers["Content-Length"])
        with urllib.request.urlopen(url) as response, path.open("wb") as f:  # noqa: S310  (fixed https host)
            while block := response.read(16 * 1024 * 1024):
                f.write(block)
        if path.stat().st_size != expected:
            raise SystemExit(f"{name}: {path.stat().st_size} bytes, the server said {expected}")
        subprocess.run(["unzip", "-tq", str(path)], check=True)  # noqa: S603, S607  (fixed command)
        digest = sha256(path)
        print(f"{name}: {expected} bytes, sha256 {digest}; uploading", flush=True)
        s3.upload_file(
            str(path),
            bucket,
            f"reference/exomiser/{release}/{name}",
            ExtraArgs={"Metadata": {"sha256": digest}},
            Config=TRANSFER,
        )
        path.unlink()


def unpack(s3, bucket: str, release: str) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    for part in PARTS:
        name = f"{release}_{part}.zip"
        key, path = f"reference/exomiser/{release}/{name}", DATA / name
        expected = s3.head_object(Bucket=bucket, Key=key)["Metadata"]["sha256"]
        print(f"copying {key}", flush=True)
        s3.download_file(bucket, key, str(path), Config=TRANSFER)
        if sha256(path) != expected:
            raise SystemExit(f"{name} does not match the SHA-256 recorded when it was fetched")
        subprocess.run(["unzip", "-q", str(path), "-d", str(DATA)], check=True)  # noqa: S603, S607  (fixed command)
        path.unlink()


def run(s3, bucket: str, release: str, prefix: str) -> None:
    WORK.mkdir(parents=True, exist_ok=True)
    log = WORK / "exomiser.log"
    failed = False
    try:
        unpack(s3, bucket, release)
        s3.download_file(bucket, f"{prefix}/input/inputs.zip", str(WORK / "inputs.zip"))
        with zipfile.ZipFile(WORK / "inputs.zip") as z:
            z.extractall(WORK)
        (WORK / "application.properties").write_text(
            f"exomiser.data-directory={DATA}\n"
            f"exomiser.hg38.data-version={release}\n"
            f"exomiser.phenotype.data-version={release}\n"
        )
        heap = int(os.environ.get("EXOMISER_HEAP_GB", "12"))
        command = [
            "java",
            f"-Xmx{heap}g",
            "-jar",
            JAR,
            "batch",
            "batch.txt",
        ]
        print("+", " ".join(command), flush=True)
        # The batch command takes no --spring.config.location option; Spring reads the variable.
        env = {**os.environ, "SPRING_CONFIG_LOCATION": str(WORK / "application.properties")}
        with log.open("w") as f:
            subprocess.run(  # noqa: S603  (fixed command)
                command, check=True, cwd=WORK, env=env, stdout=f, stderr=subprocess.STDOUT
            )
    except (subprocess.CalledProcessError, SystemExit) as error:
        print(f"failed: {error}", file=sys.stderr, flush=True)
        failed = True
    results = WORK / "results"
    if results.is_dir():
        with zipfile.ZipFile(WORK / "results.zip", "w", zipfile.ZIP_DEFLATED) as z:
            for path in sorted(results.iterdir()):
                z.write(path, path.name)
        s3.upload_file(str(WORK / "results.zip"), bucket, f"{prefix}/output/results.zip")
        print(f"{len(list(results.iterdir()))} result files", flush=True)
    if log.exists():
        s3.upload_file(str(log), bucket, f"{prefix}/output/exomiser.log")
    sys.exit(1 if failed else 0)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["fetch", "run"])
    parser.add_argument("--release", required=True)
    parser.add_argument("--prefix")
    args = parser.parse_args()
    if not re.fullmatch(r"\d{4}", args.release):
        raise SystemExit("release is four digits, e.g. 2609")
    bucket, s3 = os.environ["EXOMISER_BUCKET"], boto3.client("s3")
    if args.command == "fetch":
        fetch(s3, bucket, args.release)
    else:
        run(s3, bucket, args.release, args.prefix.rstrip("/"))


if __name__ == "__main__":
    main()
