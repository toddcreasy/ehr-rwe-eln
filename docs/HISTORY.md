# How it got here

The decisions behind `ehr-rwe-eln` (electronic health records, real world evidence, electronic lab notebooks), in the order they were made: what was chosen, what it was chosen over, and what later changed and why. Back to the [README](../README.md). The step-by-step record (checklists, commands, numbers) is in [SETUP.md](SETUP.md); this page is the reasoning. Terms are defined in the [glossary](GLOSSARY.md).

The project went from AWS (Amazon Web Services) to the laptop and back in seven weeks. The move back did not undo the work done locally: the modules built locally run on AWS today, mostly unchanged, because the second move kept the code paths and swapped what sits under them.

## Contents

1. [October 7: a platform from a template, on AWS](#october-7-a-platform-from-a-template-on-aws)
2. [October 12: local first](#october-12-local-first)
3. [October 12 to 13: the modules, built locally](#october-12-to-13-the-modules-built-locally)
4. [November 18 to 19: one database, governance, and variant curation](#november-18-to-19-one-database-governance-and-variant-curation)
5. [November 19: an industry comparison, and back to AWS](#november-19-an-industry-comparison-and-back-to-aws)
6. [November 19 to 23: the move, in six steps](#november-19-to-23-the-move-in-six-steps)
7. [November 23 to 24: cost fixes and the last comparison](#november-23-to-24-cost-fixes-and-the-last-comparison)
8. [Decisions that were reversed](#decisions-that-were-reversed)
9. [Alternatives turned down](#alternatives-turned-down)
10. [What carried through](#what-carried-through)

## October 7: a platform from a template, on AWS

The project started from the `aws/BUILD.md` template in [project-template](https://github.com/toddcreasy/project-template/tree/main/aws): eleven phases (0 to 10), each with a checklist and a STOP gate that had to pass before the next began. Infrastructure first, domain work after.

| Slot | Chosen | Over | Why |
|---|---|---|---|
| Infrastructure as code | AWS CDK (Cloud Development Kit), in Python | Terraform | The same language as the app |
| Database | Aurora Serverless v2 PostgreSQL + pgvector | A separate vector database | One database for tables and vector search; pauses to zero when idle |
| App hosting | ECS (Elastic Container Service) Express Mode | App Runner | AWS closed App Runner to new customers and points to Express Mode |
| Agent | Strands Agents SDK (software development kit) on Bedrock AgentCore Runtime | Running the agent inside the web backend | First-class Bedrock support; the agent got its own identity and scaling |
| Tools | AgentCore Gateway, publishing API (application programming interface) routes as MCP (Model Context Protocol) tools | Tools written into the agent | Tools stay portable across frameworks |
| Sign-in | Cognito, frontend on Amplify Hosting | Hand-built auth | Authentication is a solved problem |
| Deploys | GitHub Actions through an OIDC (OpenID Connect) role | Stored AWS keys | Nothing long-lived to leak |

Phases 0 to 6 landed that day; the frontend with Cognito sign-in, and CI (continuous integration), followed on October 12. Most of what the build taught was in the traps it hit, now written into SETUP.md: Cost Explorer must be on from day one or the budget alarm can never fire; GitHub's OIDC subjects now carry numeric IDs (identifiers), so an older trust policy is denied while the job hangs; a Bedrock Guardrail's versions are immutable, so a changed policy needs a new logical ID; a guardrail block ends the agent loop before typed output exists, so a naive handler turns a working safety control into a 500; Aurora takes about 15 seconds to wake, so every timeout outside it must be longer.

## October 12: local first

Five days in, with only module 1 built, the project left AWS. The goal: anyone can clone the repo and run every module without an AWS account. That changed the platform every later module was built on.

- **DuckDB to PostgreSQL.** The OMOP (Observational Medical Outcomes Partnership) tables had gone into DuckDB first, using OHDSI's (Observational Health Data Sciences and Informatics) own DuckDB DDL (data definition language). The app was going to have concurrent writers and vector search, which a single-writer file does not fit, so PostgreSQL with pgvector replaced both DuckDB and Aurora. Version 17 at first, to match Aurora, then 18 the same day, once Aurora was gone.
- **Bedrock to the Anthropic API.** Each user brought an API key.
- **Strands to the Anthropic SDK's tool runner.** The same tools and typed output with no extra framework, and dropping Strands took the locked packages from 115 to 90.
- **Dropped:** the Guardrail, AgentCore (Runtime, Gateway, Observability, Evaluations), S3 (Simple Storage Service), Secrets Manager, Cognito, Budgets, and CDK. Cognito had shipped that morning. The app bound to 127.0.0.1 with no sign-in; FastAPI served the static frontend; everything ran in Docker Compose.
- **Python 3.14**, the same day.

The AWS stacks were torn down that day and `infra/` was deleted.

## October 12 to 13: the modules, built locally

Module 1 was ported from DuckDB to Postgres; the rest were built in small PRs (pull requests) over two days, each checked against a reference rather than trusted.

- **Cohort pipeline**, built before the move and ported after it. A Python ETL (extract, transform, load) from Synthea to OMOP, compared table by table with OHDSI's ETL-Synthea on the same input. Every difference is explained, and two are bugs in ETL-Synthea, which is why the Python ETL stayed even after the project adopted OHDSI's R tools.
- **Data quality.** A Python port of every DataQualityDashboard (DQD) check, compared with DQD 2.9.0 in R until the two matched check for check. Chosen so the checks would run without R; [replaced by DQD itself](#november-19-to-23-the-move-in-six-steps) once R came into the project.
- **Trial emulation.** Protocols in YAML (YAML Ain't Markup Language), propensity weights, survival estimates, and negative control outcomes. Weighted with a not-estimable check, so the module says "not estimable" instead of printing a number when the arms do not overlap.
- **ELN (electronic lab notebook) bridge.** Claude extracting samples and results into typed models, scored for precision and recall against generated entries with known answers. Extraction ran on the small model of a two-tier setup (`MODEL_SMALL`, `MODEL_LARGE`) through the Message Batches API at half price. The hard set caught two rules the prompt missed; the adversarial set found that prompt injections asking for a fabricated sample worked on 6 of 11 entries until the prompt said entry text is data, never instructions.
- **Synthetic data.** A differentially private Bayesian network and a DP-SGD (differentially private stochastic gradient descent) autoencoder, a holdout, and fidelity, utility, trial parity, and privacy attack reports, each with a data card.
- **Synthetic genomics.** An msprime genotype study with a planted effect and a GWAS (genome-wide association study), with Hail in its own container as the cross-check, since Hail pins pandas, PySpark, and Java versions nothing else here wants.

## November 18 to 19: one database, governance, and variant curation

After a month away, the second round started with the setup and then added the largest module.

- **One model.** The small and large tiers became one `MODEL`, Claude Opus 5.5, for every call: nothing left to choose between. Every eval passed on it, in 6 minutes instead of about 10 seconds.
- **One data database.** A 1,172-person database and a 23,421-person one became a single 23,421-person `ehr_rwe_eln`. Trial emulation needs the larger population, and the app read one database at a time, so half its pages were always empty.
- **Docs: MkDocs, then GitHub Pages.** A MkDocs site was added and removed the same day. GitHub's file view draws an SVG (Scalable Vector Graphics) file as a flat image, so the interactive diagram lost its hover text and links; GitHub Pages serving `docs/` from `main` keeps them, with no site to build.
- **Synthetic data governance.** Exports recorded with their recipient, withdrawals that rewrite a release's card and draft notices, confirmed deletions, guards that refuse risky steps on a real source, and a monitor that reruns the privacy attacks when a source or the code changes. Tested and not kept: race with an age parent in the Bayesian network, which hurt the smallest races at epsilon 1. Kept: a VAE (variational autoencoder) conditional on age, which fixed how many older people there are but not how realistic they are.
- **Variant curation.** A clinical panel of real ClinVar variants planted in the synthetic people, then ACMG/AMP (American College of Medical Genetics and Genomics, Association for Molecular Pathology) rules with each gene's ClinGen expert panel thresholds, scored against ClinVar expert panels it never reads. Claude proposes literature evidence, but every PMID (PubMed identifier) and quote is checked in code, and proposals change no class until a curator accepts them on `/curation/`. HPO (Human Phenotype Ontology) phenotype scores show as context, never as PP4 (the ACMG criterion for a phenotype specific to the gene) evidence, because carriers were planted by condition.
- **RWE (real world evidence) Workbench.** The web app got a name, chosen over Counterpart, which collides with Counterpart Health.

## November 19: an industry comparison, and back to AWS

A comparison with how industry and OHDSI actually do this work (kept in the maintainer's notes) asked, for each part, whether the standard tool would do it better. Most of the answers pointed the same way.

The deciding fact was OHDSI's own tooling. HADES (Health Analytics Data-to-Evidence Suite), OHDSI's R packages, reaches databases through DatabaseConnector, which supports Redshift but not Athena, and OHDSI's AWS reference architecture keeps OMOP in Redshift or in S3 under Lake Formation. Running DQD, CohortMethod, and TrialEmulation as OHDSI ships them meant an engine they connect to. So the project went back to AWS, but not to the first build's shape:

| Question | Decided | Over | Why |
|---|---|---|---|
| Where OMOP lives | Lake only: Iceberg in S3 Tables, read through Redshift Serverless | OMOP in Aurora, or in both | An open table format any engine reads; Aurora holds app state and module results, never OMOP |
| How OMOP gets there | Build in a staging Postgres, publish, reconcile every column | Writing Iceberg from the ETL | The checked ETL stays as it is; the lake is always a copy of a verified build |
| Infrastructure as code | Terraform | CDK again | The tool of the maintainer's newer projects (methyl-flow) |
| Model | Claude Opus 4.6 on Bedrock | Opus 5.5 on the Anthropic API | IAM (Identity and Access Management) auth and one bill; Opus 5.5, 4.8, and 4.7 returned AccessDenied for this account. Every eval reran on 4.6 and matched |
| Data | Stay with Synthea | Full MIMIC-IV (Medical Information Mart for Intensive Care, version IV); the open demo is allowed | The repo's data rule, PhysioNet's limits on sending data to LLM (large language model) APIs, and no outpatient follow-up |
| Agent framework | The SDK's tool runner, LangGraph only for literature curation | LangChain throughout | Literature curation is the one flow shaped like a graph, pausing for a curator |
| Budget | $100 a month | The first build's $50 | Redshift, a lake, and on-demand jobs |

## November 19 to 23: the move, in six steps

One PR per step, with the local stack running each part until its step landed.

1. **Terraform foundation**: VPC (virtual private cloud), the S3 Tables lake with Glue and Lake Formation, Redshift Serverless, Aurora, the budget.
2. **OMOP in the lake.** 39 tables, 60,890,645 rows, and 1,038 column checks through Redshift; both cohorts reproduce.
3. **Readers on Redshift.** Every OMOP reader goes through `connect_omop()`, in SQL (Structured Query Language) that runs on both Redshift and Postgres, and a comparison script requires identical tables from both for every protocol, negative control, and synthetic data spec. Writers stay on staging and republish.
4. **The app on ECS Express Mode, as a public demo.** Cognito was planned and dropped (2026-11-20): a portfolio demo is more useful without a login, as in the maintainer's glia-nav project. It is bounded instead: a daily token limit and 10 calls an hour per address on `/api/agent`, curator decisions off, one task, and alarms.
5. **Claude on Bedrock.** Extraction became direct calls a few at a time, since Bedrock has no Message Batches API.
6. **The standard tools**, one PR each:
   - **DQD in R replaced the Python port** (2026-11-20). Both ran the same 2,384 checks and failed the same 14; the port only copied DQD, and DQD's maintainers ship new checks. The port was deleted.
   - **CohortMethod and TrialEmulation** (2026-11-21). The Python trial emulation stays as the readable version behind `/tte/`; CohortMethod is the OHDSI check; TrialEmulation fills the per-protocol gap neither had.
   - **The agent's tools.** The agent stayed in the ECS app rather than AgentCore Runtime: its calls are short and stateless, with no sign-in. Two of its four tools read concept counts precomputed in Aurora, with counts under 11 suppressed, so a public call never reaches Redshift; the other two read stored trial emulation and data quality results. MCP is offered only locally, over stdio (standard input and output). A Bedrock Guardrail checks every call.
   - **stdpopsim and REGENIE.** Three simulated populations, each person's from their OMOP race, so the GWAS has real confounding to correct: uncorrected, it found 12 false loci. PLINK 2 and REGENIE run on Fargate; the Python score test stays as the readable check.
   - **Exomiser and BIAS-2015.** Exomiser's data includes ClinVar, so its variant score already knows the answers; only its phenotype score is a fair test. BIAS-2015 became the baseline for the rules, run with and without its ClinVar-based criteria for the same reason.
   - **MST (maximum spanning tree) and AIM (adaptive and iterative mechanism).** On `mbi`, the authors' library, over the packaged alternatives (dpmm needs Python below 3.12, SmartNoise an old Opacus). AIM is best on the person summary and worse than MST on the small trial table; the release that shows it is kept as the example.

Two platform changes came out of this step. **x86 everywhere** (2026-11-22): REGENIE ships no ARM (Arm processor) build, so the GWAS ran on x86, and the app, which had run on ARM, moved too, so one architecture covers every task. **Images built by CodeBuild**: nothing heavy builds or runs in local Docker; each task's image tag is a hash of its Dockerfile and task script, so the image is the record of what ran.

## November 23 to 24: cost fixes and the last comparison

- **Redshift's cap: 60, 120 (2026-11-22), then 150 (2026-11-23) RPU-hours (Redshift Processing Unit hours) a month.** November's 60 ran out during the synthesizer work and stopped every lake reader, including the daily privacy monitor.
- **Ending Redshift sessions.** A Data API session is billed until it ends, and each one held 8 RPUs for its hour of keep-alive. `RedshiftSession` now ends its session when its block ends, and `run_tte.py` reads every table first so the session closes before the fits and the bootstrap.
- **LIRICAL (Likelihood Ratio Interpretation of Clinical Abnormalities)**, the last comparison (2026-11-23 to 24). Run phenotype only, since with a VCF (Variant Call Format) file it reads ClinVar the same way Exomiser does. Its raw likelihood ratio falls with every extra HPO term, and carriers have more terms, so it ranked carriers below everyone else (AUC, area under the curve, 0.12 on BRCA2); each gene is scored by its disease's rank in the person's own list instead. It agrees with Exomiser on MSH2 and is the weakest of the three phenotype rankings here. Its license is non-commercial, so it runs unmodified in a private image and stays out of `/curation/`.

## Decisions that were reversed

| Decision | When | Changed to | When | Why |
|---|---|---|---|---|
| Everything on AWS (CDK, Aurora, AgentCore, Cognito) | 2026-10-07 | Local first, Docker Compose | 2026-10-12 | Anyone could run it without an AWS account |
| Local first | 2026-10-12 | AWS again, with OMOP in a lakehouse | 2026-11-19 | OHDSI's R tools connect to Redshift; a public demo |
| OMOP in DuckDB | 2026-10-12 | PostgreSQL + pgvector | 2026-10-12 | Concurrent writers and vector search |
| PostgreSQL 17 | 2026-10-12 | PostgreSQL 18 | 2026-10-12 | 17 only matched Aurora, which was gone |
| Strands Agents on AgentCore | 2026-10-07 | The Anthropic SDK's tool runner, in the app | 2026-10-12 | No extra framework; 25 fewer packages |
| Bedrock | 2026-10-07 | Anthropic API | 2026-10-12 | No AWS account needed |
| Anthropic API | 2026-10-12 | Bedrock, Opus 4.6 | 2026-11-20 | IAM auth and one bill; Opus 5.5 not enabled for this account |
| Two model tiers | 2026-10-07 | One `MODEL` | 2026-11-18 | Nothing left to choose between |
| Message Batches for extraction | 2026-10-13 | Direct calls | 2026-11-20 | Bedrock has no batch API |
| Cognito sign-in | 2026-10-12 | No sign-in, local only | 2026-10-12 | Bound to 127.0.0.1; Cognito planned again for the second move and dropped on 2026-11-20 for a bounded public demo |
| Python port of DQD | 2026-10-12 | DQD itself, in R | 2026-11-20 | The port only copied it; DQD gets new checks |
| Two databases | 2026-10-13 | One, 23,421 people | 2026-11-18 | Trial emulation needs the size; the app read one |
| MkDocs site | 2026-11-18 | GitHub Pages serving `docs/` | 2026-11-18 | The diagram's hover and links survive |
| msprime, one population | 2026-10-13 | stdpopsim, three populations | 2026-11-21 | Structure the GWAS has to correct |
| ARM Fargate for the app | 2026-11-20 | x86 everywhere | 2026-11-22 | REGENIE has no ARM build |
| Redshift cap 60 RPU-hours | 2026-11-19 | 150 | 2026-11-23 | 60 ran out and stopped every reader |

## Alternatives turned down

| Alternative | For | Why not |
|---|---|---|
| OHDSI's ETL-Synthea, in R | The cohort pipeline | Ours is checked against it and fixes two of its bugs |
| Eunomia as the data | Everything | A prebuilt OMOP sample would skip the ETL module; it became the HADES smoke test instead |
| Athena for HADES | Warehouse SQL | DatabaseConnector does not support it |
| MIMIC-IV, full | Real-world data | The data rule, PhysioNet's LLM limits, no outpatient follow-up |
| Aetion | Trial emulation | Commercial, no public access |
| SAIGE (Scalable and Accurate Implementation of Generalized mixed model) as the main GWAS | Genomics | REGENIE is the common choice in pharma; SAIGE pays off for rare binary outcomes (still optional) |
| LD (linkage disequilibrium) score regression | Genomics | Needs genome-wide SNPs (single nucleotide polymorphisms) and a reference panel; 9 Mb (megabases) of simulated genome is too small |
| ClinGen VCI (Variant Curation Interface), Franklin, VarSome | Variant curation | A curation web app, and two commercial tools whose terms block bulk use |
| InterVar | A curation baseline | Needs ANNOVAR's non-commercial terms; BIAS-2015 is free and benchmarked on the same Evidence Repository |
| Mastermind, VarChat | Literature | Mastermind is licensed; VarChat is an LLM summary app, the same job as ours without the quote checks |
| Phen2Gene | Phenotype ranking | Exomiser covers it |
| AgentCore Runtime for the agent, on the second move | The agent | Short stateless calls, no sign-in, already on ECS |
| `langchain-aws` | Literature curation | Claude through the project's own client, one code path |
| NAT (network address translation) gateways and interface endpoints | Networking | They would cost more than the whole budget; tasks get public IPs (Internet Protocol addresses) in public subnets |
| Kubernetes, LiteLLM, a dedicated vector database | The platform | The wrong scale for a personal project |

## What carried through

Some rules never changed through either move, and most of the work rests on them.

- **Synthetic data only**, and no clinical claims in code, docs, or the app.
- **Checked against a reference.** The ETL against ETL-Synthea, the lake against staging column by column, the Python data quality port against DQD until DQD replaced it, trial emulation against CohortMethod, the GWAS against Hail and a planted effect, curation against ClinVar and ClinGen expert panels, every LLM extraction against a labeled set.
- **Claude proposes, code verifies, a person decides.** Extractions are validated against typed models; literature claims are checked for their PMID and quote; nothing Claude writes changes a variant's class without a curator.
- **Negative results reported as plainly as positive ones**: the not-estimable trials, AIM's wrong hazard ratio, LIRICAL ranking below chance.
- **Reproducible**: fixed seeds, pinned versions, immutable image tags, and every outside data release named.
