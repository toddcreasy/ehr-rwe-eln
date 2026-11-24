"""Run LIRICAL on every study subject's HPO terms, phenotype only, as Fargate tasks.

Usage:
  uv run python scripts/run_lirical.py run [--limit N] [--tasks K]
  uv run python scripts/run_lirical.py summarize --study <id>   # run.json again, no tasks

Run scripts/generate_panel.py and scripts/match_phenotypes.py first (subject_hpo.tsv), and apply
infra/terraform/app/ (lirical.tf). Builds the lirical image with CodeBuild if ECR has no image with
the current tag (a hash of docker/lirical.Dockerfile and docker/lirical_task.py); its data is in
the image, so there is nothing to fetch.

LIRICAL (https://github.com/TheJacksonLaboratory/LIRICAL) ranks diseases by how well a person's
HPO terms fit them. It runs without a VCF: with one it reads ClinVar through Exomiser's data,
which already knows which panel variants are pathogenic. Its license is non-commercial use only.

run: splits the people into K slices (--tasks, default 1; --limit N runs the first N people and
some carriers, to try it), each to studies/lirical-<id>/part-<k>/input/people.json, and runs them
as tasks, all at once. Downloads each slice's results.zip, lirical.log, and SHA256SUMS (the data
in the image) into data/genomics/lirical/<id>/part-<k>/, and writes run.json there.
Waits twice the expected time (about 30 s a person, 4 at a time); if a task is still running
then, it downloads what is there and names the parts still running; summarize fetches their
output from S3 once they stop.

Then, as summarize does: reads each person's disease ranking back as panel gene scores
(curation/lirical.py), and checks them against the panel's answer key, as run_exomiser.py does
for Exomiser's phenotype score: how often a pathogenic carrier's planted gene ranks first among
the genes the person has a panel variant in, and per gene the AUC for picking out the pathogenic
carriers among everyone with a panel variant there. Adds both to run.json.

summarize: downloads any part's output not yet on the laptop, then scores the run; stops if a
part has no results yet.

Needs AWS credentials (aws sso login).
"""

import argparse
import hashlib
import io
import json
import math
import subprocess
import time
import zipfile
from pathlib import Path

import boto3
import numpy as np
import polars as pl
from botocore.config import Config
from botocore.exceptions import ClientError, WaiterError

from ehr_rwe_eln.curation.lirical import (
    check_planted,
    gene_auc,
    read_disease_genes,
    read_results_zip,
)
from ehr_rwe_eln.genomics.panel import read_panel_carriers

ROOT = Path(__file__).resolve().parent.parent
STUDY = ROOT / "data" / "genomics"
OUT = STUDY / "lirical"
# The HPO release subject_hpo.tsv uses (scripts/match_phenotypes.py).
HPO = ROOT / "data" / "reference" / "hpo" / "2026-09-01"
IMAGE_FILES = ["lirical.Dockerfile", "lirical_task.py"]
OUTPUTS = ("results.zip", "lirical.log", "SHA256SUMS")
# The trial took about 30 s a person, 4 at a time (LIRICAL_WORKERS in lirical.tf).
SECONDS_PER_PERSON = 30
WORKERS = 4


def terraform_outputs(stack: str) -> dict:
    out = subprocess.run(  # noqa: S603  (fixed command; stack is "app")
        ["terraform", f"-chdir={ROOT / 'infra' / 'terraform' / stack}", "output", "-json"],  # noqa: S607
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return {k: v["value"] for k, v in json.loads(out).items()}


def image_tag() -> str:
    """The same hash as lirical.tf's local.lirical_image_tag."""
    digests = "".join(
        hashlib.sha256((ROOT / "docker" / f).read_bytes()).hexdigest() for f in IMAGE_FILES
    )
    return hashlib.sha256(digests.encode()).hexdigest()[:12]


def ensure_image(app: dict, tag: str) -> None:
    ecr = boto3.client("ecr")
    try:
        ecr.describe_images(repositoryName=app["lirical_repository"], imageIds=[{"imageTag": tag}])
        return
    except ecr.exceptions.ImageNotFoundException:
        pass
    context = io.BytesIO()
    with zipfile.ZipFile(context, "w") as z:
        for f in IMAGE_FILES:
            z.write(ROOT / "docker" / f, f)
    key = f"build/lirical-{tag}.zip"
    boto3.client("s3").put_object(Bucket=app["gwas_bucket"], Key=key, Body=context.getvalue())
    codebuild = boto3.client("codebuild")
    build = codebuild.start_build(
        projectName=app["gwas_codebuild_project"],
        sourceLocationOverride=f"{app['gwas_bucket']}/{key}",
        environmentVariablesOverride=[
            {"name": "DOCKERFILE", "value": "lirical.Dockerfile", "type": "PLAINTEXT"},
            {"name": "REPOSITORY", "value": app["lirical_repository_url"], "type": "PLAINTEXT"},
            {"name": "TAG", "value": tag, "type": "PLAINTEXT"},
        ],
    )["build"]["id"]
    print(f"building image {tag} ({build})", flush=True)
    while True:
        time.sleep(15)
        status = codebuild.batch_get_builds(ids=[build])["builds"][0]["buildStatus"]
        if status != "IN_PROGRESS":
            break
    if status != "SUCCEEDED":
        raise SystemExit(f"image build {status}; logs in /codebuild/ehr-rwe-eln-gwas")


def start_task(app: dict, command: list[str]) -> str:
    ecs = boto3.client("ecs", config=Config(retries={"mode": "adaptive", "max_attempts": 10}))
    task = ecs.run_task(
        cluster=app["cluster"],
        taskDefinition=app["lirical_task_definition"],
        launchType="FARGATE",
        networkConfiguration={
            "awsvpcConfiguration": {
                "subnets": app["public_subnet_ids"],
                "securityGroups": [app["app_security_group_id"]],
                "assignPublicIp": "ENABLED",
            }
        },
        overrides={"containerOverrides": [{"name": "lirical", "command": command}]},
    )["tasks"][0]["taskArn"]
    print(f"task {task.split('/')[-1]}: {' '.join(command)}; logs: /ecs/ehr-rwe-eln, lirical/")
    return task


def wait_tasks(
    app: dict, tasks: list[str], seconds: int
) -> dict[str, tuple[int | None, str | None]]:
    """Waits until every task stops (at most 100), or `seconds`; each task's exit code and reason.

    A task still running when the wait ends has no exit code, and the reason says so.
    """
    ecs = boto3.client("ecs")
    try:
        ecs.get_waiter("tasks_stopped").wait(
            cluster=app["cluster"],
            tasks=tasks,
            WaiterConfig={"Delay": 30, "MaxAttempts": math.ceil(seconds / 30)},
        )
    except WaiterError as e:
        # Only running out of attempts is a timeout; throttling or expired credentials are not.
        if e.kwargs.get("reason") != "Max attempts exceeded":
            raise
        print(f"stopped waiting after {seconds}s; some tasks still run", flush=True)
    out = {}
    for t in ecs.describe_tasks(cluster=app["cluster"], tasks=tasks)["tasks"]:
        container = t["containers"][0]
        if t["lastStatus"] != "STOPPED":
            out[t["taskArn"]] = (None, f"still {t['lastStatus']} when the wait ended")
            continue
        out[t["taskArn"]] = (
            container.get("exitCode"),
            container.get("reason") or t.get("stoppedReason"),
        )
    return out


def download(s3, bucket: str, out: Path, k: int) -> None:
    """Downloads part k's outputs that are not yet in out/part-<k>/."""
    part = out / f"part-{k}"
    part.mkdir(parents=True, exist_ok=True)
    for name in OUTPUTS:
        if (part / name).exists():
            continue
        key = f"studies/lirical-{out.name}/part-{k}/output/{name}"
        try:
            s3.download_file(bucket, key, str(part / name))
        except ClientError:
            print(f"part {k}: no {name} yet")


def people() -> list[dict]:
    hpo = pl.read_csv(
        STUDY / "subject_hpo.tsv", separator="\t", schema_overrides={"hpo_ids": pl.Utf8}
    )
    table = (
        pl.read_csv(STUDY / "subject_sample_mapping.tsv", separator="\t")
        .join(pl.read_csv(STUDY / "subject_phenotypes.tsv", separator="\t"), on="subject_id")
        .join(hpo, on="subject_id")
        .sort("sample_id")
    )
    return [
        {
            "sample_id": r["sample_id"],
            "sex": r["sex"],
            "hpo_ids": r["hpo_ids"].split(",") if r["hpo_ids"] else [],
        }
        for r in table.iter_rows(named=True)
    ]


def carriers() -> set[str]:
    """Sample IDs of the panel's pathogenic carriers, so a trial run includes some."""
    mapping = dict(pl.read_csv(STUDY / "subject_sample_mapping.tsv", separator="\t").iter_rows())
    truth = json.loads((STUDY / "panel_truth.json").read_text())["variants"]
    return {mapping[s] for v in truth if v["role"] == "pathogenic" for s in v["carrier_subjects"]}


def summarize(out: Path, run: dict) -> None:
    """run.json: how often LIRICAL puts a planted gene first, and the per-gene AUCs."""
    truth = json.loads((STUDY / "panel_truth.json").read_text())["variants"]
    gene_of = {v["id"]: v["gene"] for v in truth}
    disease_genes = read_disease_genes(HPO / "genes_to_phenotype.txt", set(gene_of.values()))
    results: dict[str, dict[str, int]] = {}
    for z in sorted(out.glob("part-*/results.zip")):
        results |= read_results_zip(z, disease_genes)

    mapping = dict(pl.read_csv(STUDY / "subject_sample_mapping.tsv", separator="\t").iter_rows())
    planted: dict[str, set[str]] = {}
    for v in truth:
        if v["role"] == "pathogenic":
            for s in v["carrier_subjects"]:
                if mapping[s] in results:
                    planted.setdefault(mapping[s], set()).add(v["gene"])
    # Who has a variant in which gene comes from the genotypes, as for Exomiser.
    genes_of: dict[str, set[str]] = {}
    for variant_id, samples in read_panel_carriers(STUDY / "panel.vcf.gz").items():
        for s in samples:
            genes_of.setdefault(s, set()).add(gene_of[variant_id])

    summary = {
        **run,
        "hpo_release": HPO.name,
        "people_with_results": len(results),
        "planted_gene_first": check_planted(results, planted, genes_of),
        "auc_by_gene": gene_auc(results, planted, genes_of, np.random.default_rng(0)),
    }
    (out / "run.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["run", "summarize"])
    parser.add_argument("--limit", type=int, help="run the first N people only")
    parser.add_argument("--tasks", type=int, default=1, help="split the people across K tasks")
    parser.add_argument("--study", help="summarize: the run's ID, as in data/genomics/lirical/")
    args = parser.parse_args()

    if args.command == "summarize":
        out = OUT / args.study
        run = json.loads((out / "run.json").read_text())
        s3 = boto3.client("s3")
        bucket = terraform_outputs("app")["gwas_bucket"]
        for k in range(run["tasks"]):
            download(s3, bucket, out, k)
        missing = [
            k for k in range(run["tasks"]) if not (out / f"part-{k}" / "results.zip").exists()
        ]
        if missing:
            raise SystemExit(f"parts {missing} have no results yet; run summarize again later")
        keep = ("study", "image", "tasks", "seconds", "people")
        summarize(out, {k: v for k, v in run.items() if k in keep})
        return

    app = terraform_outputs("app")
    tag = image_tag()
    if tag != app["lirical_image_tag"]:
        raise SystemExit(
            f"image files changed ({tag}, Terraform has {app['lirical_image_tag']}):"
            " plan and apply infra/terraform/app first"
        )
    ensure_image(app, tag)

    chosen = [p for p in people() if p["hpo_ids"]]
    if args.limit:
        first = {p["sample_id"] for p in chosen[: args.limit]}
        first |= set(sorted(carriers())[: max(1, args.limit // 10)])
        chosen = [p for p in chosen if p["sample_id"] in first]
    study = time.strftime("%Y%m%d-%H%M%S")
    s3 = boto3.client("s3")
    parts = {}
    for k in range(args.tasks):
        prefix = f"studies/lirical-{study}/part-{k}"
        body = json.dumps(chosen[k :: args.tasks]).encode()
        s3.put_object(Bucket=app["gwas_bucket"], Key=f"{prefix}/input/people.json", Body=body)
        parts[k] = prefix
    print(f"{len(chosen)} people in {args.tasks} tasks")

    # Twice the expected time for the largest slice, plus 30 minutes to start.
    largest = math.ceil(len(chosen) / args.tasks)
    wait = 2 * largest * SECONDS_PER_PERSON // WORKERS + 1800
    start = time.time()
    task_of = {k: start_task(app, ["run", "--prefix", p]) for k, p in parts.items()}
    stopped = wait_tasks(app, list(task_of.values()), wait)
    seconds = time.time() - start

    out = OUT / study
    failed = []
    for k in parts:
        download(s3, app["gwas_bucket"], out, k)
        code, reason = stopped[task_of[k]]
        if code is None and reason and reason.startswith("still"):
            failed.append(f"part {k}: {reason}; run summarize --study {study} once it stops")
        elif code != 0:
            failed.append(f"part {k}: exit {code}, {reason or 'see lirical.log'}")
    run = {
        "study": study,
        "image": tag,
        "tasks": args.tasks,
        "seconds": round(seconds),
        "people": len(chosen),
    }
    (out / "run.json").write_text(json.dumps(run, indent=2) + "\n")
    print(f"{args.tasks} tasks, {seconds:.0f}s; files in {out.relative_to(ROOT)}")
    if failed:
        raise SystemExit("; ".join(failed))
    summarize(out, run)


if __name__ == "__main__":
    main()
