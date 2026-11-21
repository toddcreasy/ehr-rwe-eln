"""Run PLINK 2 QC, principal components, and REGENIE on data/genomics/ as a Fargate task.

Usage: uv run python scripts/run_regenie.py

Run scripts/generate_genomics.py first, and apply infra/terraform/app/ (gwas.tf). This:
1. builds the gwas image with CodeBuild if ECR has no image with the current tag (the tag is a
   hash of docker/gwas.Dockerfile and docker/gwas_task.py; about 5 minutes the first time),
2. uploads the PLINK set and three small tables to s3://<gwas bucket>/studies/<id>/input/:
   the phenotype, the covariates (age, sex), and who HWE is tested in (self-reported white, the
   largest group),
3. runs the task (docker/gwas_task.py) and waits for it,
4. downloads studies/<id>/output/ into data/genomics/regenie/<id>/.
Then scripts/run_gwas.py reads the PCs and REGENIE's results from the newest of those.

Needs AWS credentials (aws sso login). No Docker on the laptop: the image builds on an x86
CodeBuild host and runs on x86 Fargate.
"""

import hashlib
import io
import json
import subprocess
import time
import zipfile
from pathlib import Path

import boto3
import polars as pl

ROOT = Path(__file__).resolve().parent.parent
DIRECTORY = ROOT / "data" / "genomics"
OUT = DIRECTORY / "regenie"
IMAGE_FILES = ["gwas.Dockerfile", "gwas_task.py"]
HWE_GROUP = "white"


def terraform_outputs(stack: str) -> dict:
    out = subprocess.run(  # noqa: S603  (fixed command; stack is "app")
        ["terraform", f"-chdir={ROOT / 'infra' / 'terraform' / stack}", "output", "-json"],  # noqa: S607
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return {k: v["value"] for k, v in json.loads(out).items()}


def image_tag() -> str:
    """The same hash as gwas.tf's local.gwas_image_tag."""
    digests = "".join(
        hashlib.sha256((ROOT / "docker" / f).read_bytes()).hexdigest() for f in IMAGE_FILES
    )
    return hashlib.sha256(digests.encode()).hexdigest()[:12]


def ensure_image(app: dict, tag: str) -> None:
    ecr = boto3.client("ecr")
    try:
        ecr.describe_images(repositoryName=app["gwas_repository"], imageIds=[{"imageTag": tag}])
        return
    except ecr.exceptions.ImageNotFoundException:
        pass
    context = io.BytesIO()
    with zipfile.ZipFile(context, "w") as z:
        for f in IMAGE_FILES:
            z.write(ROOT / "docker" / f, f)
    boto3.client("s3").put_object(
        Bucket=app["gwas_bucket"], Key=f"build/gwas-{tag}.zip", Body=context.getvalue()
    )
    codebuild = boto3.client("codebuild")
    build = codebuild.start_build(projectName=app["gwas_codebuild_project"])["build"]["id"]
    print(f"building image {tag} ({build})", flush=True)
    while True:
        time.sleep(15)
        status = codebuild.batch_get_builds(ids=[build])["builds"][0]["buildStatus"]
        if status != "IN_PROGRESS":
            break
    if status != "SUCCEEDED":
        raise SystemExit(f"image build {status}; logs in /codebuild/ehr-rwe-eln-gwas")


def write_inputs(staging: Path, phenotype: str) -> None:
    """REGENIE's phenotype and covariate files and PLINK's keep file, all FID IID first (the
    study's FID is its sample ID)."""
    people = pl.read_csv(DIRECTORY / "subject_sample_mapping.tsv", separator="\t").join(
        pl.read_csv(DIRECTORY / "subject_phenotypes.tsv", separator="\t"), on="subject_id"
    )
    ids = [pl.col("sample_id").alias("FID"), pl.col("sample_id").alias("IID")]
    people.select(*ids, pl.col(phenotype)).write_csv(staging / "pheno.tsv", separator="\t")
    people.select(
        *ids, pl.col("age"), (pl.col("sex") == "male").cast(pl.Int8).alias("male")
    ).write_csv(staging / "covariates.tsv", separator="\t")
    people.filter(pl.col("race") == HWE_GROUP).select(*ids).rename({"FID": "#FID"}).write_csv(
        staging / "hwe_keep.tsv", separator="\t"
    )


def main() -> None:
    truth = json.loads((DIRECTORY / "truth.json").read_text())
    app = terraform_outputs("app")
    tag = image_tag()
    if tag != app["gwas_image_tag"]:
        raise SystemExit(
            f"image files changed ({tag}, Terraform has {app['gwas_image_tag']}):"
            " plan and apply infra/terraform/app first"
        )
    ensure_image(app, tag)

    study = time.strftime("%Y%m%d-%H%M%S")
    prefix = f"studies/{study}"
    s3 = boto3.client("s3")
    staging = OUT / "input"
    staging.mkdir(parents=True, exist_ok=True)
    write_inputs(staging, truth["phenotype"])
    for path in [DIRECTORY / f"study.{x}" for x in ("bed", "bim", "fam")] + sorted(
        staging.iterdir()
    ):
        s3.upload_file(str(path), app["gwas_bucket"], f"{prefix}/input/{path.name}")

    ecs = boto3.client("ecs")
    start = time.time()
    task = ecs.run_task(
        cluster=app["cluster"],
        taskDefinition=app["gwas_task_definition"],
        launchType="FARGATE",
        networkConfiguration={
            "awsvpcConfiguration": {
                "subnets": app["public_subnet_ids"],
                "securityGroups": [app["app_security_group_id"]],
                "assignPublicIp": "ENABLED",
            }
        },
        overrides={"containerOverrides": [{"name": "gwas", "command": ["--prefix", prefix]}]},
    )["tasks"][0]["taskArn"]
    print(f"task {task.split('/')[-1]} on {prefix}; logs: /ecs/ehr-rwe-eln, gwas/", flush=True)
    ecs.get_waiter("tasks_stopped").wait(
        cluster=app["cluster"], tasks=[task], WaiterConfig={"Delay": 15, "MaxAttempts": 240}
    )
    described = ecs.describe_tasks(cluster=app["cluster"], tasks=[task])["tasks"][0]
    container = described["containers"][0]

    out = OUT / study
    out.mkdir(parents=True)
    listed = s3.list_objects_v2(Bucket=app["gwas_bucket"], Prefix=f"{prefix}/output/")
    for item in listed.get("Contents", []):
        s3.download_file(app["gwas_bucket"], item["Key"], str(out / item["Key"].split("/")[-1]))
    (out / "run.json").write_text(json.dumps({"study": study, "image": tag}, indent=2) + "\n")
    code = container.get("exitCode")
    print(
        f"exit {code} after {time.time() - start:.0f}s; {len(listed.get('Contents', []))} files"
        f" in {out.relative_to(ROOT)}"
    )
    if code != 0:
        raise SystemExit(container.get("reason") or "the task failed; see its .log files")


if __name__ == "__main__":
    main()
