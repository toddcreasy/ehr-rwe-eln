# Terraform

Three stacks, each with its own state file in one S3 bucket, `ehr-rwe-eln-tfstate-<account ID>`.

| Stack | What it holds | State key |
|---|---|---|
| `bootstrap/` | The state bucket itself (versioned, encrypted, private, old versions expire after 90 days) | `bootstrap/terraform.tfstate` |
| `foundation/` | VPC, S3 Tables lake with Lake Formation and the Glue catalog, Redshift Serverless, Aurora Serverless v2, the $100 budget, the CloudTrail trail | `foundation/terraform.tfstate` |
| `app/` | ECR, the public ECS Express Mode service, the bastion and monitor task definitions, the daily monitor schedule, the alarms, Bedrock invocation logging, and their IAM roles. Reads `foundation/` outputs through `terraform_remote_state` | `app/terraform.tfstate` |

Two of these cover the whole account, not just this project: the CloudTrail trail (`foundation/audit.tf`, every Region, a year in `ehr-rwe-eln-cloudtrail-<account ID>`) and Bedrock invocation logging (`app/bedrock_logging.tf`, every Bedrock call in us-east-1, prompts and responses as text, 30 days in `/bedrock/invocations`). Each is one setting per account, so no other repo should manage them.

Alarms, all to the `ehr-rwe-eln-alerts` SNS topic: daily tokens past 80% of the limit, 3 or more app 5xx responses in 5 minutes, 3 or more Bedrock throttles or server errors on `MODEL` in 5 minutes.

Every resource is tagged `project = ehr-rwe-eln`; the budget counts only those.

## Run a stack

The backend bucket name holds the account ID, so it is passed at init, not written in the repo. Each provider sets `allowed_account_ids`, so a plan against any other account fails before it reads anything: `bootstrap/` and `foundation/` take `account_id` in `terraform.tfvars`, and `app/` reads it from `state_bucket`.

CI's `terraform` job runs `fmt`, `validate`, TFLint, and Trivy on every PR, with no AWS credentials. A Trivy finding that is a deliberate choice gets a `# trivy:ignore:<ID> <reason>` comment above the resource.

```sh
cd infra/terraform/foundation
cp terraform.tfvars.example terraform.tfvars      # first time; fill in, gitignored
terraform init -backend-config="bucket=ehr-rwe-eln-tfstate-$(aws sts get-caller-identity --query Account --output text)"
terraform plan -out=foundation.tfplan
terraform apply foundation.tfplan                  # only after the plan is reviewed
```

## How the state bucket was made

The bucket can't hold its own state before it exists. `bootstrap/` was applied once with local state, then `terraform init -migrate-state -backend-config="bucket=..."` moved its state into the bucket and the local file was deleted. Never re-run bootstrap without the backend config: it would try to create the bucket again.

## Reading the lake from Redshift

Three things let an IAM identity query the OMOP tables in Redshift, all set up once:

1. Lake Formation grants (`lake.tf`): `DESCRIBE` on the `cdm` database and `SELECT`, `DESCRIBE` on its tables, for each role in `lake_admin_arns`. Being a Lake Formation admin allows granting, not reading.
2. A Glue resource link, `omop_cdm` (`lake.tf`): Redshift's auto-mounted `awsdatacatalog` only walks the default Glue catalog, so it reaches `s3tablescatalog/ehr-rwe-eln-omop` through this pointer. Queries name `awsdatacatalog.omop_cdm.<table>`.
3. A Redshift grant, outside Terraform: `GRANT USAGE ON DATABASE awsdatacatalog` to the identity's `IAMR:` user, run as `rwe_admin`. The statement and how to run it are in `infra/redshift/grants.sql`.

S3 Tables only drops a table with purge (which deletes its data files); PyIceberg's `drop_table` fails, `purge_table` works.

## Reaching the private databases

Aurora and Redshift have no public endpoint. From a laptop, use the Data APIs, which take SQL over HTTPS with your AWS login:

```sh
aws rds-data execute-statement --resource-arn "$(terraform output -raw aurora_cluster_arn)" \
  --secret-arn "$(terraform output -raw aurora_master_secret_arn)" --database ehr_rwe_eln --sql "select 1"
aws redshift-data execute-statement --workgroup-name ehr-rwe-eln --database ehr_rwe_eln --sql "select 1"
```

Aurora pauses after 5 idle minutes; the first query after a pause takes about 15 seconds. Aurora has pgvector 0.8.2 (local Compose: 0.8.7). The Redshift Data API signs in with your IAM identity, so it needs no secret.

The app and monitor sign in to Aurora as `app` (migration 019) with a 15-minute IAM token (`DB_IAM_AUTH=true`, `rds-db:connect` on that user only): read and write on the six module schemas, no DDL. Migrations and data loads run as `postgres`. Express Mode still injects `DB_PASSWORD` into the app container, unused: it keeps a secret once given even when the block is removed (`app/service.tf`).

A migration can also run through the RDS Data API, without the tunnel and without handling the database password. Run its `upgrade()` statements in one Data API transaction and set `alembic_version` in the same transaction (how 019 was applied on 2026-11-20).

## Deploy the app

The service runs the image tag in `app/terraform.tfvars`; tags are immutable, and each is the git commit it was built from. The image builds on AWS, never on the laptop: CodeBuild project `ehr-rwe-eln-app` (`app/app_build.tf`) builds the repository's `Dockerfile` on an x86 host. Every task here is x86, the app included (decided 2026-11-22; it ran on ARM until then).

```sh
git checkout main && git pull
uv run python scripts/build_app_image.py   # a few cents; prints the tag
# set image_tag = "<TAG>" in infra/terraform/app/terraform.tfvars, then plan and apply app/
```

The runner needs a clean working tree. It uploads `git archive` of HEAD (tracked files only, so never `.env` or `data/`) to `build/app-<commit>.zip` in the genomics bucket and skips the build if ECR already has the tag. Images up to `1b0e4c3` were ARM, built on the laptop with `docker buildx`.

The first deploy took about 25 minutes: Express Mode builds the load balancer and certificate before it starts a task. Express Mode gives the task a public IP in the public subnets, which is how it pulls from ECR with no NAT gateway. `terraform output app_url` is the public HTTPS URL. A brand-new hostname can stay unresolvable on a Mac that looked it up too early (macOS caches the miss); `sudo dscacheutil -flushcache; sudo killall -HUP mDNSResponder` clears it.

## GWAS on AWS

PLINK 2 and REGENIE run in an x86 image (`docker/gwas.Dockerfile`); REGENIE ships no ARM build, so nothing is built or run on the laptop (`app/gwas.tf`):

- **AWS CodeBuild**: a build service that runs commands on a short-lived AWS host, billed per minute. Project `ehr-rwe-eln-gwas` builds an image on x86 from `build/<name>-<tag>.zip` in the bucket and pushes it to ECR; the runner names the Dockerfile and repository, so the same project builds the GWAS and Exomiser images.
- **Fargate task** `ehr-rwe-eln-gwas`: X86_64, 2 vCPUs, 8 GB, on demand in the app cluster. Its role reads and writes only `studies/*` in bucket `ehr-rwe-eln-genomics-<account>`, which is private and TLS only. Objects under `studies/` and `build/` expire after 30 days; `reference/` (Exomiser's data) is kept.

The image tag is a hash of `docker/gwas.Dockerfile` and `docker/gwas_task.py`, computed the same way in Terraform and in `scripts/run_regenie.py`; changing either file means plan and apply `app/` first. The runner builds the image if ECR lacks the tag (about 5 minutes), uploads the study, runs the task, and downloads the results. A run on 5,000 people and 26,361 variants took 201 seconds, a few cents.

## Exomiser on AWS

Exomiser 15.1.0 (Java 21) runs in its own x86 image, `docker/exomiser.Dockerfile`, built by the same CodeBuild project into ECR repository `ehr-rwe-eln-exomiser` (`app/exomiser.tf`); the CLI zip is checked against its SHA-256 at build time. The image tag is a hash of the Dockerfile and `docker/exomiser_task.py`, computed the same way in Terraform and in `scripts/run_exomiser.py`.

- **Data, once per release**: `run_exomiser.py fetch` runs a task that downloads release 2609 (hg38 20.0 GB, phenotype 13.3 GB) from the address in Exomiser's release notes into `reference/exomiser/2609/`. The host publishes no checksums, so the task checks each zip's size against the server's and tests the archive, then stores its SHA-256 in the object's metadata. 38 minutes, nothing through the laptop.
- **Fargate task** `ehr-rwe-eln-exomiser`: X86_64, 4 vCPUs, 16 GB (12 GB Java heap), 200 GiB of task disk. Its role reads and writes only `studies/*` and `reference/exomiser/*` in the genomics bucket. Each task copies both zips, checks them against the stored SHA-256, unpacks them (about 15 minutes), then runs Exomiser's batch command on its slice of people, about 4.5 seconds a person.
- **Parallel runs**: `run --tasks K` splits the people into K slices under `studies/exomiser-<id>/part-<k>/` and runs them at once. Fargate counts vCPUs running at once across the account, so K is capped by that quota: 6 tasks under 30 vCPU. The full run, 5,000 people in 6 tasks, took 75 minutes, about $2. `exomiser.tf` requests 210 vCPU for 50 tasks, about 25 minutes (see [Account limits hit](#account-limits-hit)).

## BIAS on AWS

BIAS-2015 v3.0.0 runs on Ensembl's own VEP 115 image, pinned by digest, in `docker/bias.Dockerfile`; the BIAS source tarball is checked against its SHA-256 at build time. The same CodeBuild project builds it into ECR repository `ehr-rwe-eln-bias` (`app/bias.tf`), and the image tag is a hash of the Dockerfile and `docker/bias_task.py`, as for the others.

- **Reference data, once**: `run_bias.py fetch` runs a task that downloads the VEP 115 GRCh38 cache (25 GB) and the genome FASTA from EBI's Ensembl mirror in parallel 64 MB ranges, checks each file against Ensembl's `CHECKSUMS`, and stores it in `reference/vep/115/`; BIAS's 2026.03.01 tables with REVEL and AlphaMissense go to `reference/bias/2026.03.01/`. The main Ensembl FTP site gave 0.27 MB/s; the mirror about 21 MB/s.
- **Fargate task** `ehr-rwe-eln-bias`: X86_64, 4 vCPUs, 16 GB, 200 GiB of task disk. Its role reads and writes only `studies/*`, `reference/vep/*`, and `reference/bias/*` (the fetch writes the reference data). Each run copies gnomAD v4.1 exomes one chromosome at a time from AWS's public gnomAD bucket (`gnomad-public-us-east-1`, unsigned) and keeps only the run's positions with `tabix -R`: the image's htslib cannot read over HTTPS. Then it unpacks the cache, runs VEP once, and BIAS once per skip list.
- **A run**: 883 variants, 935 seconds, about 6 cents of Fargate time.

## Synthetic releases on AWS

`scripts/synthesize.py` and `scripts/evaluate_synth.py` run as Fargate task `ehr-rwe-eln-synth` (`app/synth.tf`): X86_64, 4 vCPUs, 16 GB, about 25 cents an hour. `scripts/run_synth.py <script> [args]` starts one and prints its log when it stops.

- **Image**: `docker/synth.Dockerfile`, Python with the locked dependencies and the `synth` group, no project code. Built by the gwas CodeBuild project into ECR repository `ehr-rwe-eln-synth`; the tag is a hash of the Dockerfile, `docker/synth_task.py`, `pyproject.toml`, and `uv.lock`, so only a dependency change needs a new image and an apply.
- **Code**: each run uploads `git archive` of HEAD to `build/source-<commit>.zip` (the tree must be clean), and the task runs that commit's script with `CODE_VERSION` set to it, which each release records.
- **Role** `ehr-rwe-eln-synth`: the monitor's lake access (its own Redshift user and Lake Formation grants, `infra/redshift/grants.sql`), Aurora as `app`, and `build/source-*` read-only.
- **A run**: the first, on 2026-11-22, rescored all 22 releases from the lake (20 trial redraws for each of 7 trial releases) in 21 minutes, about 9 cents. Every report matched the laptop's to rounding except MST's trial redraws (see the methodology, section 5).

## Public demo limits

The app has no sign-in. What bounds it, as in glia-nav:

| Limit | Where | Value |
|---|---|---|
| Daily token limit on `/api/agent` | `DAILY_TOKEN_LIMIT`, `agent.daily_usage` (`src/ehr_rwe_eln/api/limits.py`) | 150,000 tokens a day (US Eastern), then 429 until midnight |
| Per-address limit on `/api/agent` | In the task's memory, keyed on the last `X-Forwarded-For` entry | 10 calls an hour |
| Curator decisions | `PUBLIC_DEMO=true` | 403 |
| Tasks | Express Mode scaling | Exactly 1 |
| Daily token alarm | CloudWatch metric `ehr-rwe-eln/AgentTokens` from the `agent run` log lines | Email past 120,000 in a UTC day (SNS; confirm the subscription email) |
| Budget | `foundation/budget.tf` | $100 a month, credits excluded, email at 50% and 80% actual and 100% forecast |
| Redshift | `foundation/redshift.tf` | 120 RPU-hours a month (about $45 at list price), then the workgroup stops |
| Logs | `/ecs/ehr-rwe-eln` | 30 days |

`GET /api/usage` shows today's allowance. Visitors never touch Redshift: the API reads only Aurora.

## Tunnel to Aurora

For migrations and data copies with local tools. The bastion task sleeps an hour and has ECS Exec on; Systems Manager forwards a local port to Aurora through it. Nothing listens on the internet. Needs the Session Manager plugin (`brew install --cask session-manager-plugin`).

```sh
cd infra/terraform/app
SUBNETS=$(terraform output -json public_subnet_ids | python3 -c "import json,sys;print(','.join(json.load(sys.stdin)))")
T=$(aws ecs run-task --cluster ehr-rwe-eln --task-definition ehr-rwe-eln-bastion --launch-type FARGATE \
  --enable-execute-command --network-configuration \
  "awsvpcConfiguration={subnets=[$SUBNETS],securityGroups=[$(terraform output -raw app_security_group_id)],assignPublicIp=ENABLED}" \
  --query "tasks[0].taskArn" --output text)
aws ecs wait tasks-running --cluster ehr-rwe-eln --tasks "$T"
RUNTIME=$(aws ecs describe-tasks --cluster ehr-rwe-eln --tasks "$T" --query "tasks[0].containers[0].runtimeId" --output text)
aws ssm start-session --target "ecs:ehr-rwe-eln_${T##*/}_${RUNTIME}" \
  --document-name AWS-StartPortForwardingSessionToRemoteHost \
  --parameters "{\"host\":[\"$(terraform -chdir=../foundation output -raw aurora_endpoint)\"],\"portNumber\":[\"5432\"],\"localPortNumber\":[\"15432\"]}"
```

Then, in another shell, with the password from the Aurora secret in `DB_PASSWORD`: `DB_HOST=127.0.0.1 DB_PORT=15432 uv run alembic upgrade head`. Stop the bastion when done (`aws ecs stop-task --cluster ehr-rwe-eln --task "$T"`) and end the session.

On 2026-11-20 this ran the 18 migrations and copied the module data (data-only `pg_dump` of `dq`, `tte`, `synth`, `curation`, `eln`; 17 tables, row counts identical to local). The monitor task then ran once on the lake: 13 releases checked, no flags.

## Account limits hit

- VPCs per region: default 5. Raised to 10 on 2026-11-19 through Service Quotas (`L-F678F1CE`), approved within 30 minutes.
- Fargate On-Demand vCPUs running at once (`L-3032A538`): default 6, 30 on this account. 210 requested on 2026-11-22 through Terraform (`aws_servicequotas_service_quota.fargate_vcpu` in `app/exomiser.tf`); AWS opened a support case and asked for the architecture (X86_64), operating system (Linux), and use case, answered the same day. Applied that day (the support case still showed open).
