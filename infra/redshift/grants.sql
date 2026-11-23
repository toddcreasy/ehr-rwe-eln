-- Grants inside Redshift that Terraform cannot manage. Run as the namespace admin (rwe_admin),
-- whose password Redshift keeps in Secrets Manager:
--   aws redshift-data execute-statement --workgroup-name ehr-rwe-eln --database ehr_rwe_eln \
--     --secret-arn "$(terraform -chdir=infra/terraform/foundation output -raw redshift_admin_secret_arn)" \
--     --sql "<statement>"
-- Redshift creates an IAMR:<role name> user the first time an IAM role connects; run these after.

-- Lets an IAM-federated user see the auto-mounted Glue catalogs, which reach the lake through the
-- omop_cdm resource link. Lake Formation still decides which tables they can read.
GRANT USAGE ON DATABASE awsdatacatalog TO "IAMR:AWSReservedSSO_AdministratorAccess_3cdbb86f6d3e44fd";

-- The daily privacy monitor's ECS task role (infra/terraform/app). Created up front, with password
-- login disabled, because the grant needs the user to exist before the task's first connection.
CREATE USER "IAMR:ehr-rwe-eln-monitor" PASSWORD DISABLE;
GRANT USAGE ON DATABASE awsdatacatalog TO "IAMR:ehr-rwe-eln-monitor";

-- Step 6c: a writable schema in Redshift's own storage (the lake stays read-only) for OHDSI
-- cohort tables that CohortMethod and other HADES packages read. scripts/write_cohorts.py fills it.
CREATE SCHEMA IF NOT EXISTS results;
GRANT USAGE, CREATE ON SCHEMA results TO "IAMR:AWSReservedSSO_AdministratorAccess_3cdbb86f6d3e44fd";

-- The synth task's role (infra/terraform/app/synth.tf), which makes and evaluates synthetic
-- releases from the lake. Same as the monitor's.
CREATE USER "IAMR:ehr-rwe-eln-synth" PASSWORD DISABLE;
GRANT USAGE ON DATABASE awsdatacatalog TO "IAMR:ehr-rwe-eln-synth";
