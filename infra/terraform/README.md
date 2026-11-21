# Terraform

Three stacks, each with its own state file in one S3 bucket, `ehr-rwe-eln-tfstate-<account ID>`.

| Stack | What it holds | State key |
|---|---|---|
| `bootstrap/` | The state bucket itself (versioned, encrypted, private, old versions expire after 90 days) | `bootstrap/terraform.tfstate` |
| `foundation/` | VPC, S3 Tables lake with Lake Formation and the Glue catalog, Redshift Serverless, Aurora Serverless v2, the $100 budget | `foundation/terraform.tfstate` |
| `app/` | ECR, the public ECS Express Mode service, the bastion and monitor task definitions, the daily monitor schedule, the daily token alarm, and their IAM roles. Reads `foundation/` outputs through `terraform_remote_state` | `app/terraform.tfstate` |

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

## Deploy the app

The service runs the image tag in `app/terraform.tfvars`; tags are immutable, and each is the git commit it was built from.

```sh
REPO=$(terraform -chdir=infra/terraform/app output -raw ecr_repository_url)
TAG=$(git rev-parse --short HEAD)
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin "${REPO%%/*}"
docker buildx build --platform linux/arm64 -t "$REPO:$TAG" --push .
# set image_tag = "<TAG>" in infra/terraform/app/terraform.tfvars, then plan and apply app/
```

The first deploy took about 25 minutes: Express Mode builds the load balancer and certificate before it starts a task. Express Mode gives the task a public IP in the public subnets, which is how it pulls from ECR with no NAT gateway. `terraform output app_url` is the public HTTPS URL. A brand-new hostname can stay unresolvable on a Mac that looked it up too early (macOS caches the miss); `sudo dscacheutil -flushcache; sudo killall -HUP mDNSResponder` clears it.

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
| Redshift | `foundation/redshift.tf` | 60 RPU-hours a month, then the workgroup stops |
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
