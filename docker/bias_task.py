"""The BIAS-2015 task: fetch its reference data into S3 once, or annotate and classify a VCF.

Usage (the Fargate task's command, from scripts/run_bias.py):
  bias_task.py fetch
  bias_task.py run --prefix studies/<id>

Runs inside the bias container (docker/bias.Dockerfile): Ensembl VEP 115, BIAS-2015 v3.0.0,
Python's standard library and boto3. Every S3 key is under $BIAS_BUCKET.

fetch: copies into reference/ in the bucket, each object with its SHA-256 in its metadata:
- vep/115/: Ensembl's GRCh38 VEP cache and genome FASTA, from EBI's copy in parallel byte
  ranges, each checked against the CHECKSUMS file Ensembl publishes beside it;
- bias/2026.03.01/: BIAS-2015's hg38 tables for VEP, and the REVEL and AlphaMissense files
  Bitscopic prepared for VEP, from Bitscopic's public bucket (no checksums published).

run: picks the input's positions out of gnomAD v4.1 exomes (each needed chromosome copied from
gnomAD's public bucket, then deleted); copies the reference data to the task's disk and checks
each file against its SHA-256; annotates
<prefix>/input/variants.vcf with VEP (offline, the input's ClinVar VCF as a custom annotation);
runs BIAS once per skip list in the input; writes results.zip and task.log to <prefix>/output/,
also when a step fails.
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import boto3
from boto3.s3.transfer import TransferConfig
from botocore import UNSIGNED
from botocore.config import Config

# EBI's copy of Ensembl's FTP site: the same files, and faster than ftp.ensembl.org when
# measured on 2026-11-22.
ENSEMBL = "https://ftp.ebi.ac.uk/ensemblorg/pub/release-115"
PIECE = 64 * 1024 * 1024
VEP_FILES = {
    "variation/indexed_vep_cache": ["homo_sapiens_vep_115_GRCh38.tar.gz"],
    "fasta/homo_sapiens/dna_index": [
        "Homo_sapiens.GRCh38.dna.toplevel.fa.gz",
        "Homo_sapiens.GRCh38.dna.toplevel.fa.gz.fai",
        "Homo_sapiens.GRCh38.dna.toplevel.fa.gz.gzi",
    ],
}
BITSCOPIC = "bias-2015"
TABLES = "v3.0.0_datasets/2026.03.01/"
SCORES = [
    "vep/hg38/revel_grch38.tsv.gz",
    "vep/hg38/revel_grch38.tsv.gz.tbi",
    "vep/hg38/AlphaMissense_hg38.tsv.gz",
    "vep/hg38/AlphaMissense_hg38.tsv.gz.tbi",
]
# gnomAD's public bucket, in the same region as the task.
GNOMAD_BUCKET = "gnomad-public-us-east-1"
GNOMAD = "release/4.1/vcf/exomes/gnomad.exomes.v4.1.sites.{chromosome}.vcf.bgz"
WORK = Path("/work")
VEP, DATA = WORK / "vep", WORK / "bias_data"
TRANSFER = TransferConfig(multipart_chunksize=64 * 1024 * 1024, max_concurrency=16)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        while block := f.read(16 * 1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def store(s3, bucket: str, path: Path, key: str) -> None:
    digest = sha256(path)
    print(f"{path.name}: {path.stat().st_size} bytes, sha256 {digest}; uploading", flush=True)
    s3.upload_file(
        str(path), bucket, key, ExtraArgs={"Metadata": {"sha256": digest}}, Config=TRANSFER
    )
    path.unlink()


def ranged_download(url: str, path: Path, workers: int = 16) -> None:
    """The file in 64 MB byte ranges, 16 at a time: a slow server usually limits each connection,
    not the total. Each range has a 2-minute timeout and up to 5 tries, so a stalled connection
    is retried instead of hanging the task. Progress every 5%."""
    request = urllib.request.Request(url, method="HEAD")  # noqa: S310  (fixed https host)
    with urllib.request.urlopen(request, timeout=120) as response:  # noqa: S310  (fixed https host)
        size = int(response.headers["Content-Length"])
    with path.open("wb") as f:
        f.truncate(size)
    starts = list(range(0, size, PIECE))
    done = [0]

    def piece(start: int) -> None:
        end = min(start + PIECE, size) - 1
        for attempt in range(5):
            try:
                ranged = urllib.request.Request(url, headers={"Range": f"bytes={start}-{end}"})  # noqa: S310
                with urllib.request.urlopen(ranged, timeout=120) as response:  # noqa: S310
                    data = response.read()
                if response.status != 206 or len(data) != end - start + 1:
                    raise OSError(f"got {len(data)} bytes, status {response.status}")
                with path.open("r+b") as f:
                    f.seek(start)
                    f.write(data)
                break
            except (urllib.error.URLError, TimeoutError, OSError) as error:
                if attempt == 4:
                    raise
                print(f"bytes {start}-{end}: {error}; retrying", flush=True)
        done[0] += 1
        if done[0] % max(1, len(starts) // 20) == 0:
            print(f"{path.name}: {done[0]} of {len(starts)} pieces", flush=True)

    with ThreadPoolExecutor(workers) as pool:
        list(pool.map(piece, starts))


def fetch(s3, bucket: str) -> None:
    WORK.mkdir(exist_ok=True)
    for directory, names in VEP_FILES.items():
        with urllib.request.urlopen(f"{ENSEMBL}/{directory}/CHECKSUMS", timeout=120) as response:  # noqa: S310
            rows = [line.split() for line in response.read().decode().splitlines()]
            sums = {r[2]: r[:2] for r in rows if len(r) == 3}
        for name in names:
            path = WORK / name
            print(f"downloading {ENSEMBL}/{directory}/{name}", flush=True)
            ranged_download(f"{ENSEMBL}/{directory}/{name}", path)
            # Ensembl's CHECKSUMS are the BSD checksum and size in 1 KB blocks (`sum -r`).
            found = subprocess.run(  # noqa: S603  (fixed command)
                ["sum", "-r", str(path)],  # noqa: S607
                check=True,
                capture_output=True,
                text=True,
            ).stdout.split()[:2]
            if [int(x) for x in found] != [int(x) for x in sums[name]]:
                raise SystemExit(f"{name}: sum {found}, Ensembl's CHECKSUMS say {sums[name]}")
            store(s3, bucket, path, f"reference/vep/115/{name}")

    public = boto3.client("s3", config=Config(signature_version=UNSIGNED))
    listed = public.list_objects_v2(Bucket=BITSCOPIC, Prefix=TABLES)["Contents"]
    tables = [o["Key"] for o in listed if Path(o["Key"]).name.startswith("hg38_")]
    tables = [k for k in tables if "nirvana" not in k]
    for key in tables + SCORES:
        path = WORK / Path(key).name
        print(f"copying s3://{BITSCOPIC}/{key}", flush=True)
        public.download_file(BITSCOPIC, key, str(path), Config=TRANSFER)
        store(s3, bucket, path, f"reference/bias/2026.03.01/{path.name}")


def download(s3, bucket: str, prefix: str, into: Path) -> list[Path]:
    """Every object under prefix, each checked against the SHA-256 stored when it was fetched."""
    into.mkdir(parents=True, exist_ok=True)
    out = []
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
        for o in page.get("Contents", []):
            path = into / Path(o["Key"]).name
            expected = s3.head_object(Bucket=bucket, Key=o["Key"])["Metadata"]["sha256"]
            s3.download_file(bucket, o["Key"], str(path), Config=TRANSFER)
            if sha256(path) != expected:
                raise SystemExit(f"{path.name} does not match the SHA-256 recorded when fetched")
            out.append(path)
    if not out:
        raise SystemExit(f"nothing under {prefix}: run fetch first")
    return out


def gnomad_subset(variants: Path, out: Path) -> None:
    """gnomAD v4.1 exome records at the input's positions, as one indexed VCF. Each needed
    chromosome's file and index are copied from gnomAD's public bucket to the task's disk, read
    with tabix, and deleted before the next: the image's htslib cannot read over HTTPS."""
    regions: dict[str, list[tuple[int, int]]] = {}
    for line in variants.read_text().splitlines():
        if line.startswith("#"):
            continue
        chromosome, position, _, ref = line.split("\t")[:4]
        regions.setdefault(chromosome, []).append((int(position) - 1, int(position) + len(ref)))
    out.parent.mkdir(parents=True, exist_ok=True)
    public = boto3.client("s3", config=Config(signature_version=UNSIGNED))
    header, records = [], {}
    for chromosome, spans in regions.items():
        bed = out.parent / f"{chromosome}.bed"
        bed.write_text("".join(f"{chromosome}\t{a}\t{b}\n" for a, b in sorted(spans)))
        local = out.parent / Path(GNOMAD.format(chromosome=chromosome)).name
        for suffix in ("", ".tbi"):
            key = GNOMAD.format(chromosome=chromosome) + suffix
            print(f"copying s3://{GNOMAD_BUCKET}/{key}", flush=True)
            public.download_file(GNOMAD_BUCKET, key, f"{local}{suffix}", Config=TRANSFER)
        found = subprocess.run(  # noqa: S603  (fixed command)
            ["/usr/bin/tabix", "-h", str(local), "-R", str(bed)],
            capture_output=True,
            text=True,
            cwd=out.parent,
        )
        local.unlink()
        Path(f"{local}.tbi").unlink()
        if found.returncode != 0:
            raise SystemExit(f"tabix on {chromosome} exited {found.returncode}: {found.stderr}")
        text = found.stdout
        for line in text.splitlines():
            if line.startswith("#"):
                if not records and line not in header:
                    header.append(line)
            else:
                cols = line.split("\t", 5)
                records[(chromosome, int(cols[1]), cols[3], cols[4])] = line
    order = sorted(records, key=lambda k: (list(regions).index(k[0]), k[1]))
    plain = out.with_suffix("")
    plain.write_text("\n".join(header + [records[k] for k in order]) + "\n")
    with out.open("wb") as f:
        subprocess.run(["bgzip", "-c", str(plain)], check=True, stdout=f)  # noqa: S603, S607
    subprocess.run(["/usr/bin/tabix", "-p", "vcf", str(out)], check=True)  # noqa: S603
    print(f"gnomAD: {len(records)} records at {len(regions)} chromosomes' positions", flush=True)


def run(s3, bucket: str, prefix: str) -> None:
    log = WORK / "task.log"
    out = WORK / "out"
    out.mkdir(parents=True, exist_ok=True)
    failed = False
    try:
        with log.open("w") as logf:

            def call(command: list[str], cwd: Path = WORK) -> None:
                print("+", " ".join(command), file=logf, flush=True)
                subprocess.run(command, check=True, cwd=cwd, stdout=logf, stderr=subprocess.STDOUT)  # noqa: S603  (fixed commands)

            s3.download_file(bucket, f"{prefix}/input/inputs.zip", str(WORK / "inputs.zip"))
            with zipfile.ZipFile(WORK / "inputs.zip") as z:
                z.extractall(WORK / "input")
            inputs = WORK / "input"
            # First, before the long copy below: a failure here shows in a minute.
            gnomad = WORK / "gnomad" / "gnomad.exomes.v4.1.subset.vcf.gz"
            gnomad_subset(inputs / "variants.vcf", gnomad)

            for path in download(s3, bucket, "reference/vep/115/", VEP):
                if path.name.endswith(".tar.gz"):
                    call(["tar", "-xzf", str(path), "-C", str(VEP)])
                    path.unlink()
            download(s3, bucket, "reference/bias/2026.03.01/", DATA)

            annotated = out / "variants.vep.json"
            fasta = VEP / "Homo_sapiens.GRCh38.dna.toplevel.fa.gz"
            clinvar = inputs / "clinvar.vcf.gz"
            # As in BIAS-2015's doc/vep_setup.md for hg38.
            call(
                [
                    "vep",
                    "--input_file",
                    str(inputs / "variants.vcf"),
                    "--output_file",
                    str(annotated),
                    "--json",
                    "--cache",
                    "--offline",
                    "--assembly",
                    "GRCh38",
                    "--cache_version",
                    "115",
                    "--dir_cache",
                    str(VEP),
                    "--fasta",
                    str(fasta),
                    "--everything",
                    "--fork",
                    "4",
                    "--force_overwrite",
                    "--custom",
                    f"file={gnomad},short_name=gnomAD_exomes,format=vcf,type=exact,"
                    "coords=0,fields=AF%AF_joint%AC%AN",
                    "--custom",
                    f"file={clinvar},short_name=ClinVar,format=vcf,type=exact,"
                    "coords=0,fields=CLNSIG%CLNREVSTAT%CLNDN%CLNVC%CLNSIGSCV",
                    "--plugin",
                    f"AlphaMissense,file={DATA / 'AlphaMissense_hg38.tsv.gz'}",
                    "--plugin",
                    f"REVEL,file={DATA / 'revel_grch38.tsv.gz'}",
                ]  # fmt: skip
            )

            # BIAS's own paths file, pointed at this disk.
            paths = json.loads((DATA / "hg38_vep_required_paths.json").read_text())
            paths = {k: str(DATA / Path(v).name) for k, v in paths.items()}
            (WORK / "paths.json").write_text(json.dumps(paths, indent=2))
            for skip in sorted((inputs / "skips").glob("*.txt")):
                command = [
                    "python3", "bias_2015.py", str(annotated), str(WORK / "paths.json"),
                    str(out / f"{skip.stem}.tsv"), "--annotator", "vep",
                ]  # fmt: skip
                if skip.read_text().strip():
                    command += ["--skip_list", str(skip)]
                call(command, cwd=Path("/opt/bias"))
    except (subprocess.CalledProcessError, SystemExit, KeyError, OSError) as error:
        print(f"failed: {error}", file=sys.stderr, flush=True)
        with log.open("a") as logf:
            print(f"failed: {error}", file=logf)
        failed = True
    if any(out.iterdir()):
        with zipfile.ZipFile(WORK / "results.zip", "w", zipfile.ZIP_DEFLATED) as z:
            for path in sorted(out.iterdir()):
                z.write(path, path.name)
        s3.upload_file(str(WORK / "results.zip"), bucket, f"{prefix}/output/results.zip")
    if log.exists():
        s3.upload_file(str(log), bucket, f"{prefix}/output/task.log")
    sys.exit(1 if failed else 0)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["fetch", "run"])
    parser.add_argument("--prefix")
    args = parser.parse_args()
    bucket, s3 = os.environ["BIAS_BUCKET"], boto3.client("s3")
    if args.command == "fetch":
        fetch(s3, bucket)
    else:
        run(s3, bucket, args.prefix.rstrip("/"))


if __name__ == "__main__":
    main()
