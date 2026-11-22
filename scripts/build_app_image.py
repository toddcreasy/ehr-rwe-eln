"""Build the app image on AWS CodeBuild (ARM) for the current git commit and push it to ECR.

Usage: uv run python scripts/build_app_image.py

Needs a clean working tree on the commit to deploy, and infra/terraform/app/ applied
(app_build.tf). The source is `git archive` of HEAD, so only tracked files go in: never .env or
data/. Uploads it to build/app-<commit>.zip in the genomics bucket, builds and pushes
<ecr repository>:<commit> unless ECR already has that tag (tags are immutable), and prints the
tag. Then set image_tag in infra/terraform/app/terraform.tfvars and plan and apply app/.

Needs AWS credentials (aws sso login).
"""

import json
import subprocess
import time
from pathlib import Path

import boto3

ROOT = Path(__file__).resolve().parent.parent


def git(*args: str) -> str:
    return subprocess.run(  # noqa: S603  (fixed command)
        ["git", "-C", str(ROOT), *args],  # noqa: S607
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def main() -> None:
    if git("status", "--porcelain", "--untracked-files=no").strip():
        raise SystemExit("uncommitted changes: commit them, so the tag names what is built")
    tag = git("rev-parse", "--short", "HEAD").strip()
    out = subprocess.run(  # noqa: S603  (fixed command)
        ["terraform", f"-chdir={ROOT / 'infra' / 'terraform' / 'app'}", "output", "-json"],  # noqa: S607
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    app = {k: v["value"] for k, v in json.loads(out).items()}
    repository = app["ecr_repository_url"]

    ecr = boto3.client("ecr")
    try:
        ecr.describe_images(
            repositoryName=repository.split("/", 1)[1], imageIds=[{"imageTag": tag}]
        )
        print(f"ECR already has {tag}")
        return
    except ecr.exceptions.ImageNotFoundException:
        pass

    source = subprocess.run(  # noqa: S603  (fixed command)
        ["git", "-C", str(ROOT), "archive", "--format=zip", "HEAD"],  # noqa: S607
        check=True,
        capture_output=True,
    ).stdout
    key = f"build/app-{tag}.zip"
    boto3.client("s3").put_object(Bucket=app["gwas_bucket"], Key=key, Body=source)
    codebuild = boto3.client("codebuild")
    build = codebuild.start_build(
        projectName=app["app_codebuild_project"],
        sourceLocationOverride=f"{app['gwas_bucket']}/{key}",
        environmentVariablesOverride=[{"name": "TAG", "value": tag, "type": "PLAINTEXT"}],
    )["build"]["id"]
    print(
        f"building {repository}:{tag} ({build}), {len(source) / 1e6:.1f} MB of source", flush=True
    )
    start = time.time()
    while True:
        time.sleep(15)
        status = codebuild.batch_get_builds(ids=[build])["builds"][0]["buildStatus"]
        if status != "IN_PROGRESS":
            break
    if status != "SUCCEEDED":
        raise SystemExit(f"build {status}; logs in /codebuild/ehr-rwe-eln-app")
    print(f'pushed {tag} after {time.time() - start:.0f}s; set image_tag = "{tag}" and plan app/')


if __name__ == "__main__":
    main()
