"""Build frontend/ as static files and upload them to the Amplify app.

    uv run python scripts/deploy_frontend.py

The Amplify app has no Git connection, so this script is how a build goes live.
User pool IDs and the app ID come from the BackendStack and FrontendStack outputs.
"""

import io
import os
import subprocess  # noqa: S404
import time
import urllib.request
import zipfile
from pathlib import Path

import boto3

REGION = "us-east-1"
FRONTEND = Path(__file__).resolve().parents[1] / "frontend"


def outputs(cfn, stack_name: str) -> dict[str, str]:
    stack = cfn.describe_stacks(StackName=stack_name)["Stacks"][0]
    return {o["OutputKey"]: o["OutputValue"] for o in stack["Outputs"]}


def main() -> None:
    cfn = boto3.client("cloudformation", region_name=REGION)
    backend = outputs(cfn, "ehr-rwe-eln-BackendStack")
    frontend = outputs(cfn, "ehr-rwe-eln-FrontendStack")

    env = os.environ | {
        "NEXT_PUBLIC_USER_POOL_ID": backend["UserPoolId"],
        "NEXT_PUBLIC_USER_POOL_CLIENT_ID": backend["UserPoolClientId"],
    }
    subprocess.run(["npm", "ci"], cwd=FRONTEND, check=True)  # noqa: S603, S607
    subprocess.run(["npm", "run", "build"], cwd=FRONTEND, env=env, check=True)  # noqa: S603, S607

    buffer = io.BytesIO()
    out = FRONTEND / "out"
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in out.rglob("*"):
            if path.is_file():
                zf.write(path, path.relative_to(out))

    amplify = boto3.client("amplify", region_name=REGION)
    app_id = frontend["AmplifyAppId"]
    deployment = amplify.create_deployment(appId=app_id, branchName="main")
    request = urllib.request.Request(  # noqa: S310
        deployment["zipUploadUrl"], data=buffer.getvalue(), method="PUT"
    )
    urllib.request.urlopen(request).close()  # noqa: S310
    job_id = deployment["jobId"]
    amplify.start_deployment(appId=app_id, branchName="main", jobId=job_id)

    while True:
        status = amplify.get_job(appId=app_id, branchName="main", jobId=job_id)["job"]["summary"][
            "status"
        ]
        if status not in ("PENDING", "PROVISIONING", "RUNNING"):
            break
        time.sleep(5)
    print(f"deployment {job_id}: {status}")
    print(frontend["WebUrl"])
    if status != "SUCCEED":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
