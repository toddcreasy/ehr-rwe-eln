"""Run Exomiser on every study subject's panel variants and HPO terms, as a Fargate task.

Usage:
  uv run python scripts/run_exomiser.py fetch            # once per data release, about an hour
  uv run python scripts/run_exomiser.py run [--limit N] [--tasks K]
  uv run python scripts/run_exomiser.py summarize --study <id>   # run.json again, no tasks

Run scripts/generate_panel.py and scripts/match_phenotypes.py first (subject_hpo.tsv), and apply
infra/terraform/app/ (exomiser.tf). Both commands build the exomiser image with CodeBuild if ECR
has no image with the current tag (a hash of docker/exomiser.Dockerfile and
docker/exomiser_task.py).

fetch: a task downloads Exomiser's hg38 and phenotype data (33 GB) from the address in its release
notes straight into s3://<genomics bucket>/reference/exomiser/<release>/. Nothing comes to the
laptop.

run: writes one sample file and VCF per person (curation/exomiser.py), split into K slices
(--tasks, default 1; --limit N runs the first N people and some carriers, to try it). Each slice
goes to studies/exomiser-<id>/part-<k>/input/ and runs as its own task, all at once; each task
unpacks the data itself (about 15 minutes), then takes about 4.5 seconds a person. 50 tasks need
the Fargate vCPU quota in exomiser.tf. Downloads each slice's results.zip and exomiser.log into
data/genomics/exomiser/<id>/part-<k>/, and checks how often each pathogenic carrier's planted gene
comes first. Exomiser's data release includes ClinVar, so its variant score knows which panel
variants are pathogenic; the phenotype score is the part to read. Per gene, it also compares
Exomiser's phenotype score with our Resnik score (phenotype_scores.tsv) on the same people: the
AUC for picking out the pathogenic carriers among everyone with a panel variant in the gene.
Writes data/genomics/exomiser/<id>/run.json.

summarize: the same checks on a run already downloaded.

Needs AWS credentials (aws sso login).
"""

import argparse
import hashlib
import io
import json
import subprocess
import time
import zipfile
from pathlib import Path

import boto3
import numpy as np
import polars as pl
from botocore.config import Config

from ehr_rwe_eln.curation.exomiser import (
    check_planted,
    phenotype_auc,
    read_results_zip,
    write_inputs,
)
from ehr_rwe_eln.genomics.omop import read_panel_genotypes

ROOT = Path(__file__).resolve().parent.parent
STUDY = ROOT / "data" / "genomics"
OUT = STUDY / "exomiser"
IMAGE_FILES = ["exomiser.Dockerfile", "exomiser_task.py"]
RELEASE = "2609"


def terraform_outputs(stack: str) -> dict:
    out = subprocess.run(  # noqa: S603  (fixed command; stack is "app")
        ["terraform", f"-chdir={ROOT / 'infra' / 'terraform' / stack}", "output", "-json"],  # noqa: S607
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return {k: v["value"] for k, v in json.loads(out).items()}


def image_tag() -> str:
    """The same hash as exomiser.tf's local.exomiser_image_tag."""
    digests = "".join(
        hashlib.sha256((ROOT / "docker" / f).read_bytes()).hexdigest() for f in IMAGE_FILES
    )
    return hashlib.sha256(digests.encode()).hexdigest()[:12]


def ensure_image(app: dict, tag: str) -> None:
    ecr = boto3.client("ecr")
    try:
        ecr.describe_images(repositoryName=app["exomiser_repository"], imageIds=[{"imageTag": tag}])
        return
    except ecr.exceptions.ImageNotFoundException:
        pass
    context = io.BytesIO()
    with zipfile.ZipFile(context, "w") as z:
        for f in IMAGE_FILES:
            z.write(ROOT / "docker" / f, f)
    key = f"build/exomiser-{tag}.zip"
    boto3.client("s3").put_object(Bucket=app["gwas_bucket"], Key=key, Body=context.getvalue())
    codebuild = boto3.client("codebuild")
    build = codebuild.start_build(
        projectName=app["gwas_codebuild_project"],
        sourceLocationOverride=f"{app['gwas_bucket']}/{key}",
        environmentVariablesOverride=[
            {"name": "DOCKERFILE", "value": "exomiser.Dockerfile", "type": "PLAINTEXT"},
            {"name": "REPOSITORY", "value": app["exomiser_repository_url"], "type": "PLAINTEXT"},
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
        taskDefinition=app["exomiser_task_definition"],
        launchType="FARGATE",
        networkConfiguration={
            "awsvpcConfiguration": {
                "subnets": app["public_subnet_ids"],
                "securityGroups": [app["app_security_group_id"]],
                "assignPublicIp": "ENABLED",
            }
        },
        overrides={"containerOverrides": [{"name": "exomiser", "command": command}]},
    )["tasks"][0]["taskArn"]
    print(f"task {task.split('/')[-1]}: {' '.join(command)}; logs: /ecs/ehr-rwe-eln, exomiser/")
    return task


def wait_tasks(app: dict, tasks: list[str]) -> dict[str, tuple[int | None, str | None]]:
    """Waits until every task stops (at most 100, 4 hours); each task's exit code and reason."""
    ecs = boto3.client("ecs")
    ecs.get_waiter("tasks_stopped").wait(
        cluster=app["cluster"], tasks=tasks, WaiterConfig={"Delay": 30, "MaxAttempts": 480}
    )
    out = {}
    for t in ecs.describe_tasks(cluster=app["cluster"], tasks=tasks)["tasks"]:
        container = t["containers"][0]
        out[t["taskArn"]] = (
            container.get("exitCode"),
            container.get("reason") or t.get("stoppedReason"),
        )
    return out


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
            "hpo_release": r["hpo_release"],
            "hpo_ids": r["hpo_ids"].split(",") if r["hpo_ids"] else [],
        }
        for r in table.iter_rows(named=True)
    ]


def planted() -> dict[str, set[str]]:
    """Each pathogenic carrier's sample ID and planted genes (one person carries two), from the
    panel's answer key."""
    mapping = dict(pl.read_csv(STUDY / "subject_sample_mapping.tsv", separator="\t").iter_rows())
    truth = json.loads((STUDY / "panel_truth.json").read_text())["variants"]
    out: dict[str, set[str]] = {}
    for v in truth:
        if v["role"] == "pathogenic":
            for s in v["carrier_subjects"]:
                out.setdefault(mapping[s], set()).add(v["gene"])
    return out


def resnik() -> dict[str, dict[str, float]]:
    """Our phenotype score per sample and panel gene, from scripts/match_phenotypes.py."""
    mapping = dict(pl.read_csv(STUDY / "subject_sample_mapping.tsv", separator="\t").iter_rows())
    scores = pl.read_csv(STUDY / "phenotype_scores.tsv", separator="\t")
    genes = [c for c in scores.columns if c not in ("subject_id", "hpo_terms")]
    return {
        mapping[r["subject_id"]]: {g: r[g] for g in genes} for r in scores.iter_rows(named=True)
    }


def summarize(out: Path, ran: set[str], run: dict) -> None:
    """run.json: how often each score puts a planted gene first, and the per-gene AUCs."""
    results: dict[str, dict] = {}
    for z in sorted(out.glob("part-*/results.zip")):
        results |= read_results_zip(z)
    carriers = {s: g for s, g in planted().items() if s in ran}
    summary = {
        **run,
        "people_with_results": len(results),
        "planted_gene_first": check_planted(results, carriers),
        "phenotype_auc_by_gene": phenotype_auc(
            results, carriers, resnik(), np.random.default_rng(0)
        ),
    }
    (out / "run.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["fetch", "run", "summarize"])
    parser.add_argument("--limit", type=int, help="run the first N people only")
    parser.add_argument("--tasks", type=int, default=1, help="split the people across K tasks")
    parser.add_argument("--study", help="summarize: the run's ID, as in data/genomics/exomiser/")
    args = parser.parse_args()

    if args.command == "summarize":
        out = OUT / args.study
        run = json.loads((out / "run.json").read_text())
        keep = ("study", "image", "data_release", "tasks", "seconds")
        run = {k: v for k, v in run.items() if k in keep + ("people", "no_calls", "no_hpo_terms")}
        # The people who ran are the ones with results (a person with no calls never runs).
        ran = {s for z in out.glob("part-*/results.zip") for s in read_results_zip(z)}
        summarize(out, ran, run)
        return

    app = terraform_outputs("app")
    tag = image_tag()
    if tag != app["exomiser_image_tag"]:
        raise SystemExit(
            f"image files changed ({tag}, Terraform has {app['exomiser_image_tag']}):"
            " plan and apply infra/terraform/app first"
        )
    ensure_image(app, tag)

    if args.command == "fetch":
        start = time.time()
        task = start_task(app, ["fetch", "--release", RELEASE])
        code, reason = wait_tasks(app, [task])[task]
        print(f"exit {code} after {time.time() - start:.0f}s")
        if code != 0:
            raise SystemExit(reason or "the fetch failed; see the task's log")
        return

    chosen = people()
    carriers = planted()
    if args.limit:
        # The first N people, and always some pathogenic carriers, so a trial checks something.
        first = {p["sample_id"] for p in chosen[: args.limit]}
        first |= set(sorted(carriers)[: max(1, args.limit // 10)])
        chosen = [p for p in chosen if p["sample_id"] in first]
    genotypes = read_panel_genotypes(STUDY / "panel.vcf.gz")
    study = time.strftime("%Y%m%d-%H%M%S")
    s3 = boto3.client("s3")
    counts: dict[str, int] = {}
    parts = {}
    for k in range(args.tasks):
        inputs, part_counts = write_inputs(chosen[k :: args.tasks], genotypes, RELEASE)
        for key, value in part_counts.items():
            counts[key] = counts.get(key, 0) + value
        prefix = f"studies/exomiser-{study}/part-{k}"
        s3.put_object(Bucket=app["gwas_bucket"], Key=f"{prefix}/input/inputs.zip", Body=inputs)
        parts[k] = prefix
    print(", ".join(f"{k.replace('_', ' ')} {v}" for k, v in counts.items()))

    start = time.time()
    task_of = {
        k: start_task(app, ["run", "--release", RELEASE, "--prefix", p]) for k, p in parts.items()
    }
    stopped = wait_tasks(app, list(task_of.values()))
    seconds = time.time() - start

    out = OUT / study
    failed = []
    for k, prefix in parts.items():
        part = out / f"part-{k}"
        part.mkdir(parents=True)
        for name in ("results.zip", "exomiser.log"):
            try:
                s3.download_file(app["gwas_bucket"], f"{prefix}/output/{name}", str(part / name))
            except s3.exceptions.ClientError:
                print(f"part {k}: no {name}")
        code, reason = stopped[task_of[k]]
        if code != 0:
            failed.append(f"part {k}: exit {code}, {reason or 'see exomiser.log'}")
    print(f"{args.tasks} tasks, {seconds:.0f}s; files in {out.relative_to(ROOT)}")
    if failed:
        raise SystemExit("; ".join(failed))

    run = {
        "study": study,
        "image": tag,
        "data_release": RELEASE,
        "tasks": args.tasks,
        "seconds": round(seconds),
        **counts,
    }
    summarize(out, {p["sample_id"] for p in chosen}, run)


if __name__ == "__main__":
    main()
