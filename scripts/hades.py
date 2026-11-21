"""Run an R script in the hades container (OHDSI HADES) against the lake on Redshift.

Usage: uv run python scripts/hades.py smoke_lake.R [script args...]
       uv run python scripts/hades.py --local smoke_eunomia.R    # no tunnel, no AWS

The Redshift workgroup is private and HADES connects over JDBC, so this:
1. starts the bastion task (ECS Exec on; it stops itself after an hour),
2. opens a Systems Manager tunnel from 127.0.0.1:15439 to Redshift's port 5439,
3. gets a temporary Redshift password for the caller's IAM identity (one hour, user IAMR:...),
   so no Redshift password is stored anywhere and HADES has exactly the caller's lake grants,
4. runs `docker compose run --rm hades <script>` with REDSHIFT_* set,
5. stops the bastion and closes the tunnel, whatever the script did. A thread sends a few bytes
   through the tunnel every 5 minutes, so Session Manager's 20-minute idle limit never closes it
   during a long query.

Needs AWS credentials (aws sso login), Docker, and the Session Manager plugin. Scripts live in
r/; the container sees r/ as /work/r and data/hades/ as /work/data/hades.
"""

import argparse
import contextlib
import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import boto3

from ehr_rwe_eln.config import LakeSettings

ROOT = Path(__file__).resolve().parent.parent
LOCAL_PORT = 15439
# Session Manager closes a session after 20 idle minutes, and a long Redshift query sends nothing
# back until it finishes (CohortMethod's covariate build on 2026-11-20 did, and lost the tunnel).
KEEPALIVE_S = 300
# PostgreSQL's SSLRequest, which Redshift answers with one byte: traffic through the tunnel with
# no login.
SSL_REQUEST = bytes([0, 0, 0, 8, 4, 210, 22, 47])


def terraform_outputs(stack: str) -> dict:
    out = subprocess.run(  # noqa: S603  (fixed command; stack is "app" or "foundation")
        ["terraform", f"-chdir={ROOT / 'infra' / 'terraform' / stack}", "output", "-json"],  # noqa: S607
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return {k: v["value"] for k, v in json.loads(out).items()}


def wait_for_port(port: int, timeout_s: int = 60) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(1)
    raise TimeoutError(f"tunnel did not open on port {port}")


def keep_tunnel_alive(port: int, stop: threading.Event) -> None:
    """Every KEEPALIVE_S, a short connection through the tunnel, so it never sits idle."""
    while not stop.wait(KEEPALIVE_S):
        with contextlib.suppress(OSError), socket.create_connection(("127.0.0.1", port), 10) as s:
            s.sendall(SSL_REQUEST)
            s.recv(1)


def run_container(script: str, args: list[str], env: dict) -> int:
    (ROOT / "data" / "hades").mkdir(parents=True, exist_ok=True)
    cmd = ["docker", "compose", "--profile", "hades", "run", "--rm", "hades", script, *args]
    # Fixed docker command; script names a file in r/, run inside the container.
    return subprocess.run(cmd, cwd=ROOT, env={**os.environ, **env}).returncode  # noqa: S603


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--local", action="store_true", help="run without the tunnel or AWS")
    parser.add_argument("script")
    parser.add_argument("args", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.local:
        sys.exit(run_container(args.script, args.args, {}))

    settings = LakeSettings()
    app, foundation = terraform_outputs("app"), terraform_outputs("foundation")
    ecs = boto3.client("ecs", region_name=settings.aws_region)
    task = ecs.run_task(
        cluster=app["cluster"],
        taskDefinition=app["bastion_task_definition"],
        launchType="FARGATE",
        enableExecuteCommand=True,
        networkConfiguration={
            "awsvpcConfiguration": {
                "subnets": app["public_subnet_ids"],
                "securityGroups": [app["app_security_group_id"]],
                "assignPublicIp": "ENABLED",
            }
        },
    )["tasks"][0]["taskArn"]
    tunnel = None
    stop_keepalive = threading.Event()
    try:
        print("starting the bastion", flush=True)
        ecs.get_waiter("tasks_running").wait(cluster=app["cluster"], tasks=[task])
        described = ecs.describe_tasks(cluster=app["cluster"], tasks=[task])["tasks"][0]
        runtime_id = described["containers"][0]["runtimeId"]
        target = f"ecs:{app['cluster']}_{task.split('/')[-1]}_{runtime_id}"
        # The ECS Exec agent can take a few seconds after RUNNING to accept sessions.
        time.sleep(10)
        params = {
            "host": [foundation["redshift_endpoint"]],
            "portNumber": ["5439"],
            "localPortNumber": [str(LOCAL_PORT)],
        }
        tunnel = subprocess.Popen(  # noqa: S603  (fixed aws command, values from Terraform)
            [  # noqa: S607
                "aws",
                "ssm",
                "start-session",
                "--region",
                settings.aws_region,
                "--target",
                target,
                "--document-name",
                "AWS-StartPortForwardingSessionToRemoteHost",
                "--parameters",
                json.dumps(params),
            ],
            stdout=subprocess.DEVNULL,
            # Its own process group: the aws command starts session-manager-plugin, which would
            # outlive a plain terminate() and keep the port (and our output pipe) open.
            start_new_session=True,
        )
        wait_for_port(LOCAL_PORT)
        print(f"tunnel open on 127.0.0.1:{LOCAL_PORT}", flush=True)
        threading.Thread(
            target=keep_tunnel_alive, args=(LOCAL_PORT, stop_keepalive), daemon=True
        ).start()

        serverless = boto3.client("redshift-serverless", region_name=settings.aws_region)
        creds = serverless.get_credentials(
            workgroupName=settings.redshift_workgroup,
            dbName=settings.redshift_database,
            durationSeconds=3600,
        )
        env = {
            "REDSHIFT_SERVER": f"host.docker.internal/{settings.redshift_database}",
            "REDSHIFT_PORT": str(LOCAL_PORT),
            "REDSHIFT_USER": creds["dbUser"],
            "REDSHIFT_PASSWORD": creds["dbPassword"],
            "CDM_SCHEMA": settings.redshift_lake_schema,
        }
        code = run_container(args.script, args.args, env)
    finally:
        # The bastion first: on 2026-11-20 the tunnel had already died, killpg raised, and the
        # bastion was left running.
        stop_keepalive.set()
        ecs.stop_task(cluster=app["cluster"], task=task, reason="hades.py finished")
        if tunnel is not None:
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.killpg(tunnel.pid, signal.SIGTERM)
        print("tunnel closed, bastion stopped", flush=True)
    sys.exit(code)


if __name__ == "__main__":
    main()
