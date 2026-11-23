"""Run BIAS-2015 on the Evidence Repository variants, as a Fargate task, and score it next to our
rules.

Usage:
  uv run python scripts/run_bias.py fetch              # once: VEP cache, FASTA, BIAS tables into S3
  uv run python scripts/run_bias.py run                # annotate, classify three ways, score
  uv run python scripts/run_bias.py summarize --study <id>   # the scores again, no task

Run scripts/curate_variants.py --set erepo first: the variants, the expert panels' classes and
codes, and our rules' results all come from its latest run in the app database. Apply
infra/terraform/app/ (bias.tf). Both commands build the bias image with CodeBuild if ECR has no
image with the current tag (a hash of docker/bias.Dockerfile and docker/bias_task.py).

fetch: a task copies Ensembl's VEP 115 GRCh38 cache and FASTA (26 GB) and BIAS-2015's hg38
tables with REVEL and AlphaMissense (2 GB) into s3://<genomics bucket>/reference/. Nothing comes
to the laptop.

run: uploads a VCF of the run's variants, the same dated ClinVar VCF the run used, and three
skip lists (curation/bias.py SKIPS) to studies/bias-<id>/input/; the task annotates with VEP and
runs BIAS once per list. Downloads results.zip and task.log into data/curation/bias/<id>/ and
writes summary.json there: agreement with the expert panels for our rules and each BIAS run on
the same variants, and per criterion against the panels' codes.

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
from psycopg.rows import dict_row

from ehr_rwe_eln.config import DatabaseSettings
from ehr_rwe_eln.curation.bias import SKIPS, as_assessments, read_output, vcf
from ehr_rwe_eln.curation.curate import score
from ehr_rwe_eln.curation.erepo import SCORED, score_criteria

ROOT = Path(__file__).resolve().parent.parent
REFERENCE = ROOT / "data" / "reference"
OUT = ROOT / "data" / "curation" / "bias"
IMAGE_FILES = ["bias.Dockerfile", "bias_task.py"]
# BIAS's codes (constants.evaluated_codes), and ours, for the per-criterion table.
CODES = ["PVS1", "PS1", "PS3", "PS4", "PM1", "PM2", "PM4", "PM5", "PP2", "PP3", "PP5"]
CODES += ["BA1", "BS1", "BS2", "BS3", "BP1", "BP3", "BP4", "BP6", "BP7"]


def terraform_outputs(stack: str) -> dict:
    out = subprocess.run(  # noqa: S603  (fixed command; stack is "app")
        ["terraform", f"-chdir={ROOT / 'infra' / 'terraform' / stack}", "output", "-json"],  # noqa: S607
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return {k: v["value"] for k, v in json.loads(out).items()}


def image_tag() -> str:
    """The same hash as bias.tf's local.bias_image_tag."""
    digests = "".join(
        hashlib.sha256((ROOT / "docker" / f).read_bytes()).hexdigest() for f in IMAGE_FILES
    )
    return hashlib.sha256(digests.encode()).hexdigest()[:12]


def ensure_image(app: dict, tag: str) -> None:
    ecr = boto3.client("ecr")
    try:
        ecr.describe_images(repositoryName=app["bias_repository"], imageIds=[{"imageTag": tag}])
        return
    except ecr.exceptions.ImageNotFoundException:
        pass
    context = io.BytesIO()
    with zipfile.ZipFile(context, "w") as z:
        for f in IMAGE_FILES:
            z.write(ROOT / "docker" / f, f)
    key = f"build/bias-{tag}.zip"
    boto3.client("s3").put_object(Bucket=app["gwas_bucket"], Key=key, Body=context.getvalue())
    codebuild = boto3.client("codebuild")
    build = codebuild.start_build(
        projectName=app["gwas_codebuild_project"],
        sourceLocationOverride=f"{app['gwas_bucket']}/{key}",
        environmentVariablesOverride=[
            {"name": "DOCKERFILE", "value": "bias.Dockerfile", "type": "PLAINTEXT"},
            {"name": "REPOSITORY", "value": app["bias_repository_url"], "type": "PLAINTEXT"},
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


def run_task(app: dict, command: list[str]) -> tuple[int | None, str | None, float]:
    ecs = boto3.client("ecs")
    start = time.time()
    task = ecs.run_task(
        cluster=app["cluster"],
        taskDefinition=app["bias_task_definition"],
        launchType="FARGATE",
        networkConfiguration={
            "awsvpcConfiguration": {
                "subnets": app["public_subnet_ids"],
                "securityGroups": [app["app_security_group_id"]],
                "assignPublicIp": "ENABLED",
            }
        },
        overrides={"containerOverrides": [{"name": "bias", "command": command}]},
    )["tasks"][0]["taskArn"]
    print(f"task {task.split('/')[-1]}: {' '.join(command)}; logs: /ecs/ehr-rwe-eln, bias/")
    ecs.get_waiter("tasks_stopped").wait(
        cluster=app["cluster"], tasks=[task], WaiterConfig={"Delay": 30, "MaxAttempts": 480}
    )
    stopped = ecs.describe_tasks(cluster=app["cluster"], tasks=[task])["tasks"][0]
    container = stopped["containers"][0]
    reason = container.get("reason") or stopped.get("stoppedReason")
    return container.get("exitCode"), reason, time.time() - start


def erepo_run() -> tuple[int, dict, list[dict]]:
    """The latest Evidence Repository rules run: its ID, sources, and assessments. Literature
    runs share the variant set; a rules run's sources name the Evidence Repository file."""
    with DatabaseSettings().connect() as con:
        con.row_factory = dict_row
        run = con.execute(
            "SELECT run_id, sources FROM curation.run WHERE variant_set = 'erepo'"
            " AND sources ? 'erepo' ORDER BY run_id DESC LIMIT 1"
        ).fetchone()
        if run is None:
            raise SystemExit("no erepo run: run scripts/curate_variants.py --set erepo first")
        rows = con.execute(
            "SELECT variant_id, gene, expected, classification, met, evidence"
            " FROM curation.assessment WHERE run_id = %s ORDER BY variant_id",
            [run["run_id"]],
        ).fetchall()
    return run["run_id"], run["sources"], rows


def summarize(out: Path, run: dict) -> None:
    """summary.json: our rules and each BIAS run, scored on the variants BIAS returned."""
    run_id, _, ours = erepo_run()
    with zipfile.ZipFile(out / "results.zip") as z:
        outputs = {name: read_output(z.read(f"{name}.tsv").decode()) for name in SKIPS}
    results = {}
    for name, found in outputs.items():
        theirs, missing = as_assessments(ours, found)
        results[name] = {"skipped": SKIPS[name], "missing": len(missing), "theirs": theirs}
    # Score everyone on the variants every BIAS run returned, so the columns compare.
    common = set.intersection(*({a["variant_id"] for a in r["theirs"]} for r in results.values()))
    shared = [a for a in ours if a["variant_id"] in common]

    def scored(rows: list[dict]) -> dict:
        s = score(rows)
        genes = {
            g: {"agreement": v["agreement"], "variants": v["variants"]}
            for g, v in s["by_gene"].items()
        }
        return {
            "agreement": s["agreement"],
            "reversals": s["reversals"],
            "confusion": s["confusion"],
            "by_gene": genes,
            "criteria_vs_panel": score_criteria(rows, CODES),
        }

    summary = {
        **run,
        "erepo_run": run_id,
        "variants": len(ours),
        "scored": len(shared),
        "rules": scored(shared) | {"criteria_vs_panel": score_criteria(shared, SCORED)},
        **{
            name: {
                "skipped": r["skipped"],
                "missing": r["missing"],
                **scored([a for a in r["theirs"] if a["variant_id"] in common]),
            }
            for name, r in results.items()
        },
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(f"{len(shared)} of {len(ours)} variants scored (every BIAS run returned them)")
    for name in ("rules", *SKIPS):
        s = summary[name]
        print(f"  {name:<24} agreement {s['agreement']:.1%}, reversals {s['reversals']}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["fetch", "run", "summarize"])
    parser.add_argument("--study", help="summarize: the run's ID, as in data/curation/bias/")
    args = parser.parse_args()

    if args.command == "summarize":
        out = OUT / args.study
        keep = ("study", "image", "clinvar", "seconds")
        run = {k: v for k, v in json.loads((out / "summary.json").read_text()).items() if k in keep}
        summarize(out, run)
        return

    app = terraform_outputs("app")
    tag = image_tag()
    if tag != app["bias_image_tag"]:
        raise SystemExit(
            f"image files changed ({tag}, Terraform has {app['bias_image_tag']}):"
            " plan and apply infra/terraform/app first"
        )
    ensure_image(app, tag)

    if args.command == "fetch":
        code, reason, seconds = run_task(app, ["fetch"])
        print(f"exit {code} after {seconds:.0f}s")
        if code != 0:
            raise SystemExit(reason or "the fetch failed; see the task's log")
        return

    _, sources, ours = erepo_run()
    clinvar = REFERENCE / "clinvar" / f"clinvar_{sources['clinvar']}.vcf.gz"
    inputs = io.BytesIO()
    with zipfile.ZipFile(inputs, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("variants.vcf", vcf([a["variant_id"] for a in ours]))
        z.write(clinvar, "clinvar.vcf.gz")
        z.write(f"{clinvar}.tbi", "clinvar.vcf.gz.tbi")
        for name, codes in SKIPS.items():
            z.writestr(f"skips/{name}.txt", "".join(f"{c}\n" for c in codes))
    study = time.strftime("%Y%m%d-%H%M%S")
    prefix = f"studies/bias-{study}"
    s3 = boto3.client("s3")
    s3.put_object(
        Bucket=app["gwas_bucket"], Key=f"{prefix}/input/inputs.zip", Body=inputs.getvalue()
    )
    print(f"{len(ours)} variants, ClinVar {sources['clinvar']}; {prefix}", flush=True)
    code, reason, seconds = run_task(app, ["run", "--prefix", prefix])

    out = OUT / study
    out.mkdir(parents=True)
    for name in ("results.zip", "task.log"):
        try:
            s3.download_file(app["gwas_bucket"], f"{prefix}/output/{name}", str(out / name))
        except s3.exceptions.ClientError:
            print(f"no {name}")
    print(f"exit {code} after {seconds:.0f}s; files in {out.relative_to(ROOT)}")
    if code != 0:
        raise SystemExit(reason or "the task failed; see task.log")
    summarize(
        out,
        {"study": study, "image": tag, "clinvar": sources["clinvar"], "seconds": round(seconds)},
    )


if __name__ == "__main__":
    main()
