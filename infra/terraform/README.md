# Terraform

Two stacks, each with its own state file in one S3 bucket, `ehr-rwe-eln-tfstate-<account ID>`.

| Stack | What it holds | State key |
|---|---|---|
| `bootstrap/` | The state bucket itself (versioned, encrypted, private, old versions expire after 90 days) | `bootstrap/terraform.tfstate` |
| `foundation/` | VPC, S3 Tables lake with Lake Formation and the Glue catalog, Redshift Serverless, Aurora Serverless v2, the $100 budget | `foundation/terraform.tfstate` |

Every resource is tagged `project = ehr-rwe-eln`; the budget counts only those.

## Run a stack

The backend bucket name holds the account ID, so it is passed at init, not written in the repo.

```sh
cd infra/terraform/foundation
cp terraform.tfvars.example terraform.tfvars      # first time; fill in, gitignored
terraform init -backend-config="bucket=ehr-rwe-eln-tfstate-$(aws sts get-caller-identity --query Account --output text)"
terraform plan -out=foundation.tfplan
terraform apply foundation.tfplan                  # only after the plan is reviewed
```

## How the state bucket was made

The bucket can't hold its own state before it exists. `bootstrap/` was applied once with local state, then `terraform init -migrate-state -backend-config="bucket=..."` moved its state into the bucket and the local file was deleted. Never re-run bootstrap without the backend config: it would try to create the bucket again.

## Reaching the private databases

Aurora and Redshift have no public endpoint. From a laptop, use the Data APIs, which take SQL over HTTPS with your AWS login:

```sh
aws rds-data execute-statement --resource-arn "$(terraform output -raw aurora_cluster_arn)" \
  --secret-arn "$(terraform output -raw aurora_master_secret_arn)" --database ehr_rwe_eln --sql "select 1"
aws redshift-data execute-statement --workgroup-name ehr-rwe-eln --database ehr_rwe_eln --sql "select 1"
```

Aurora pauses after 5 idle minutes; the first query after a pause takes about 15 seconds. Aurora has pgvector 0.8.2 (local Compose: 0.8.7). The Redshift Data API signs in with your IAM identity, so it needs no secret.

## Account limits hit

- VPCs per region: default 5. Raised to 10 on 2026-11-19 through Service Quotas (`L-F678F1CE`), approved within 30 minutes.
