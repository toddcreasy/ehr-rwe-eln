"""Entry point of the synth task (infra/terraform/app/synth.tf): fetch one commit's code and run
one of the synthetic data scripts with it, against the lake (through Redshift) and Aurora.

Task command: <commit> synthesize.py|evaluate_synth.py [script args...]

scripts/run_synth.py uploads `git archive` of the commit to build/source-<commit>.zip in the
genomics bucket, then starts the task. The task has no git checkout, so CODE_VERSION carries the
commit into each release's and report's record.
"""

import io
import os
import re
import subprocess
import sys
import zipfile

import boto3

SCRIPTS = {"synthesize.py", "evaluate_synth.py"}
WORK = "/tmp/work"  # noqa: S108  (the task's own disk; nothing else runs in it)


def main() -> None:
    commit, script, *args = sys.argv[1:]
    if not re.fullmatch(r"[0-9a-f]{7,40}", commit) or script not in SCRIPTS:
        raise SystemExit(f"usage: <commit> {'|'.join(sorted(SCRIPTS))} [args...]")
    body = (
        boto3.client("s3")
        .get_object(Bucket=os.environ["SYNTH_BUCKET"], Key=f"build/source-{commit}.zip")["Body"]
        .read()
    )
    zipfile.ZipFile(io.BytesIO(body)).extractall(WORK)
    env = {**os.environ, "PYTHONPATH": f"{WORK}/src", "CODE_VERSION": commit}
    print(f"running {script} {' '.join(args)} at {commit}", flush=True)
    done = subprocess.run(  # noqa: S603  (script from a fixed list; args go to argparse)
        [sys.executable, f"{WORK}/scripts/{script}", *args], cwd=WORK, env=env, check=False
    )
    raise SystemExit(done.returncode)


if __name__ == "__main__":
    main()
