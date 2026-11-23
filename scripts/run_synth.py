"""Make or evaluate synthetic releases on AWS: one synth task (infra/terraform/app/synth.tf) runs
scripts/synthesize.py or scripts/evaluate_synth.py at the current commit, against the lake and
Aurora, and this prints its log.

Usage: uv run python scripts/run_synth.py synthesize.py [--spec path/to/spec.yaml] [--method aim]
       uv run python scripts/run_synth.py evaluate_synth.py

Needs a clean working tree (the commit is what runs, and what each release records) and
infra/terraform/app/ applied. Builds the image first if ECR lacks it; if the dependencies
changed since the last apply, says to plan and apply app/. Uploads `git archive` of HEAD to
build/source-<commit>.zip in the genomics bucket (only tracked files: never .env or data/).
The task costs about 25 cents an hour (4 vCPU, 16 GB, x86 Fargate).

Needs AWS credentials (aws sso login).
"""

import hashlib
import io
import json
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import boto3

ROOT = Path(__file__).resolve().parent.parent
IMAGE_FILES = ["docker/synth.Dockerfile", "docker/synth_task.py", "pyproject.toml", "uv.lock"]


def git(*args: str) -> str:
    return subprocess.run(  # noqa: S603  (fixed command)
        ["git", "-C", str(ROOT), *args],  # noqa: S607
        check=True,
        capture_output=True,
    ).stdout.decode()


def terraform_outputs() -> dict:
    out = subprocess.run(  # noqa: S603  (fixed command)
        ["terraform", f"-chdir={ROOT / 'infra' / 'terraform' / 'app'}", "output", "-json"],  # noqa: S607
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return {k: v["value"] for k, v in json.loads(out).items()}


def image_tag() -> str:
    """The same hash as synth.tf's local.synth_image_tag."""
    digests = "".join(hashlib.sha256((ROOT / f).read_bytes()).hexdigest() for f in IMAGE_FILES)
    return hashlib.sha256(digests.encode()).hexdigest()[:12]


def ensure_image(app: dict, tag: str) -> None:
    ecr = boto3.client("ecr")
    try:
        ecr.describe_images(repositoryName=app["synth_repository"], imageIds=[{"imageTag": tag}])
        return
    except ecr.exceptions.ImageNotFoundException:
        pass
    context = io.BytesIO()
    with zipfile.ZipFile(context, "w") as z:
        for f in IMAGE_FILES:
            z.write(ROOT / f, Path(f).name)
    key = f"build/synth-{tag}.zip"
    boto3.client("s3").put_object(Bucket=app["gwas_bucket"], Key=key, Body=context.getvalue())
    codebuild = boto3.client("codebuild")
    build = codebuild.start_build(
        projectName=app["gwas_codebuild_project"],
        sourceLocationOverride=f"{app['gwas_bucket']}/{key}",
        environmentVariablesOverride=[
            {"name": "DOCKERFILE", "value": "synth.Dockerfile", "type": "PLAINTEXT"},
            {"name": "REPOSITORY", "value": app["synth_repository_url"], "type": "PLAINTEXT"},
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


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    if git("status", "--porcelain", "--untracked-files=no").strip():
        raise SystemExit("uncommitted changes: commit them, so the release records what ran")
    app = terraform_outputs()
    tag = image_tag()
    if tag != app["synth_image_tag"]:
        raise SystemExit(f"dependencies changed (image {tag}, task {app['synth_image_tag']}):"
                         " plan and apply infra/terraform/app/ first")  # fmt: skip
    ensure_image(app, tag)

    commit = git("rev-parse", "--short", "HEAD").strip()
    source = subprocess.run(  # noqa: S603  (fixed command)
        ["git", "-C", str(ROOT), "archive", "--format=zip", "HEAD"],  # noqa: S607
        check=True,
        capture_output=True,
    ).stdout
    boto3.client("s3").put_object(
        Bucket=app["gwas_bucket"], Key=f"build/source-{commit}.zip", Body=source
    )

    ecs = boto3.client("ecs")
    command = [commit, *sys.argv[1:]]
    task = ecs.run_task(
        cluster=app["cluster"],
        taskDefinition=app["synth_task_definition"],
        launchType="FARGATE",
        networkConfiguration={
            "awsvpcConfiguration": {
                "subnets": app["public_subnet_ids"],
                "securityGroups": [app["app_security_group_id"]],
                "assignPublicIp": "ENABLED",
            }
        },
        overrides={"containerOverrides": [{"name": "synth", "command": command}]},
    )["tasks"][0]["taskArn"]
    task_id = task.split("/")[-1]
    print(f"task {task_id}: {' '.join(command)}; logs: /ecs/ehr-rwe-eln, synth/synth/{task_id}")
    start = time.time()
    ecs.get_waiter("tasks_stopped").wait(
        cluster=app["cluster"], tasks=[task], WaiterConfig={"Delay": 30, "MaxAttempts": 480}
    )
    stopped = ecs.describe_tasks(cluster=app["cluster"], tasks=[task])["tasks"][0]
    code = stopped["containers"][0].get("exitCode")

    logs = boto3.client("logs")
    kwargs = {"logGroupName": "/ecs/ehr-rwe-eln", "logStreamName": f"synth/synth/{task_id}",
              "startFromHead": True}  # fmt: skip
    while True:
        try:
            page = logs.get_log_events(**kwargs)
        except logs.exceptions.ResourceNotFoundException:
            break
        for event in page["events"]:
            print(event["message"])
        if page["nextForwardToken"] == kwargs.get("nextToken"):
            break
        kwargs["nextToken"] = page["nextForwardToken"]
    reason = stopped["containers"][0].get("reason") or stopped.get("stoppedReason")
    minutes = (time.time() - start) / 60
    print(f"exit {code} after {minutes:.0f} minutes" + (f" ({reason})" if code != 0 else ""))
    raise SystemExit(0 if code == 0 else 1)


if __name__ == "__main__":
    main()
