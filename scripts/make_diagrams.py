"""Draw docs/architecture.svg (what runs where, how data moves between the modules, the checks) and
docs/schema.svg (the database's schemas, tables, and keys).

Each box has a hover note and links to its docs or source when the SVG is opened in a browser.
GitHub shows it as a plain image. The drawing helpers follow methyl-flow's make_diagrams.py.

Run: uv run python scripts/make_diagrams.py [--out docs]
"""

import argparse
import html
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--out", type=Path, default=Path("docs"))
OUT = parser.parse_args().out
STYLE = {
    "module": ("#F1ECFB", "#7A57C9", ""),
    "runtime": ("#FFF4E5", "#E0862B", ""),
    "data": ("#E7F3EC", "#2F8F5B", ""),
    "ops": ("#EEF1F5", "#6B7A8C", ""),
    "outside": ("#FFFFFF", "#8A8F98", ' stroke-dasharray="6 4"'),
}
REPO = "https://github.com/toddcreasy/ehr-rwe-eln/blob/main/"
MOD = REPO + "docs/modules/"
FONT = "-apple-system, BlinkMacSystemFont, Segoe UI, Helvetica, Arial, sans-serif"
CSS = (
    ".t{fill:#1F2933}.s{fill:#52606D;font-size:11px}"
    ".g{fill:#3E4C59;font-size:12px;font-weight:600;letter-spacing:.04em;text-transform:uppercase}"
    ".e{fill:#3E4C59;font-size:10.5px}"
    "a:hover rect.n{stroke-width:2.5}g.h:hover rect.n{stroke-width:2.5}"
)
ARROW = (
    '<defs><marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
    'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#3E4C59"/></marker></defs>'
)


def esc(text):
    return html.escape(text, quote=True)


def header(width, height, title, desc):
    return [
        f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
        f'width="{width}" height="{height}" viewBox="0 0 {width} {height}" font-family="{FONT}">',
        f"<title>{esc(title)}</title>",
        f"<desc>{esc(desc)}</desc>",
        ARROW,
        f'<rect width="{width}" height="{height}" fill="#FFFFFF"/>',
        f"<style>{CSS}</style>",
    ]


def panel(x, y, w, h, label, note):
    return (
        f'<g><title>{esc(note)}</title><rect x="{x}" y="{y}" width="{w}" height="{h}" rx="10" '
        f'fill="#FAFBFC" stroke="#CBD2D9" stroke-width="1"/>'
        f'<text x="{x + 14}" y="{y + 20}" class="g">{esc(label)}</text></g>'
    )


def node(x, y, w, h, kind, name, sub, note, link=None):
    fill, stroke, dash = STYLE[kind]
    cx = x + w / 2
    body = (
        f"<title>{esc(note)}</title>"
        f'<rect class="n" x="{x}" y="{y}" width="{w}" height="{h}" rx="8" fill="{fill}" '
        f'stroke="{stroke}" stroke-width="1.5"{dash}/>'
        f'<text x="{cx}" y="{y + h / 2 - 4}" text-anchor="middle" class="t" font-size="13" '
        f'font-weight="700">{esc(name)}</text>'
        f'<text x="{cx}" y="{y + h / 2 + 13}" text-anchor="middle" class="s">{esc(sub)}</text>'
    )
    if link:
        return f'<a xlink:href="{esc(link)}" href="{esc(link)}" target="_blank">{body}</a>'
    return f'<g class="h">{body}</g>'


def arrow(points, label="", lx=None, ly=None, anchor="start"):
    pts = " ".join(f"{x},{y}" for x, y in points)
    out = (
        f'<g><polyline points="{pts}" fill="none" stroke="#3E4C59" stroke-width="1.5" '
        f'marker-end="url(#arr)"/>'
    )
    if label:
        out += f'<text x="{lx}" y="{ly}" class="e" text-anchor="{anchor}">{esc(label)}</text>'
    return out + "</g>"


W, H = 1240, 1160
# Everything below the AWS and laptop panels moves down this far.
SHIFT = 210
NH, DW = 56, 190
C = [60, 290, 520, 750, 980]
s = header(
    W,
    H,
    "ehr-rwe-eln: one OMOP lake, seven modules, on AWS",
    "Synthea patients and Athena vocabularies become an OMOP CDM v5.4 database: built in a "
    "staging Postgres on the laptop, published as Iceberg tables in S3 Tables, and read through "
    "Redshift Serverless. Data quality, target trial emulation, synthetic data releases, and a "
    "synthetic genotype study read it; the ELN bridge writes lab results into it with Claude; "
    "variant curation classifies the study's clinical panel. Module results live in Aurora, "
    "heavy jobs run as Fargate tasks, and the app, RWE Workbench, runs on ECS with Claude on "
    "Amazon Bedrock.",
)
s.append('<text x="40" y="26" class="t" font-size="15" font-weight="700">ehr-rwe-eln</text>')
s.append(
    '<text x="140" y="26" class="s">Dashed boxes are outside the project. '
    "Open the SVG on its own and hover a box for what it does and why.</text>"
)

# AWS.
RA, RB = 90, 172
ma, mb = RA + NH // 2, RB + NH // 2
s.append(
    panel(
        40,
        40,
        1160,
        210,
        "AWS, us-east-1, all in Terraform",
        "infra/terraform: bootstrap/ (state bucket), foundation/ (network, lake, Redshift, "
        "Aurora, budget, audit), app/ (ECR, ECS, CodeBuild, Fargate tasks, Guardrail, alarms). "
        "Public subnets only, no NAT gateway: each task gets a public IP.",
    )
)
s += [
    node(
        C[0],
        RA,
        DW,
        NH,
        "outside",
        "Browser",
        "the public demo, no sign-in",
        "The dashboards: data quality, target trials, ELN extraction, synthetic releases, and "
        "variant curation, plus the agent. No sign-in; /api/agent has a daily token limit and "
        "10 calls an hour per address, and curator decisions are off in the demo.",
    ),
    node(
        C[1],
        RA,
        DW,
        NH,
        "runtime",
        "RWE Workbench",
        "ECS Express Mode, 1 x86 task",
        "One container serves the API under /api and the static Next.js frontend at /. ECS "
        "Express Mode builds the load balancer, HTTPS certificate, and URL. The image is built "
        "by CodeBuild and tagged with its git commit.",
        REPO + "infra/terraform/app/service.tf",
    ),
    node(
        C[2],
        RA,
        DW,
        NH,
        "outside",
        "Amazon Bedrock",
        "Claude Opus 4.6, Guardrail",
        "Claude through the Anthropic SDK's AnthropicBedrock client, with IAM credentials (SSO "
        "on the laptop, the task role on ECS); no API key. A Bedrock Guardrail checks every "
        "/api/agent call. Used by the agent, ELN extraction, and literature curation.",
        "https://docs.claude.com/en/docs/build-with-claude/claude-on-amazon-bedrock",
    ),
    node(
        C[3],
        RA,
        DW,
        NH,
        "ops",
        "CodeBuild, ECR",
        "builds every image",
        "CodeBuild builds the app image and each Fargate task's image into its own ECR "
        "repository; task image tags are a hash of their Dockerfile and task script, and tags "
        "are immutable.",
        REPO + "infra/terraform/app/app_build.tf",
    ),
    node(
        C[4],
        RA,
        DW,
        NH,
        "ops",
        "Budget, alarms, audit",
        "$100 a month, email",
        "An AWS Budget on resources tagged project = ehr-rwe-eln, CloudWatch alarms (agent "
        "tokens, app errors, Bedrock errors, Guardrail interventions) to email, and CloudTrail.",
        REPO + "infra/terraform/app/alarms.tf",
    ),
    node(
        C[1],
        RB,
        DW,
        NH,
        "data",
        "Aurora Serverless v2",
        "PostgreSQL 18.6 + pgvector",
        "App state and every module's results (dq, tte, eln, synth, curation), plus omop_stats, "
        "the precomputed concept counts the agent reads, so public calls never reach Redshift. "
        "Never holds OMOP. Pauses to zero when idle.",
        REPO + "infra/terraform/foundation/aurora.tf",
    ),
    node(
        C[2],
        RB,
        DW,
        NH,
        "data",
        "S3 Tables",
        "OMOP as Iceberg, cdm",
        "The OMOP CDM v5.4 tables as Apache Iceberg in an S3 table bucket, namespace cdm, in the "
        "Glue Data Catalog; Lake Formation grants each reader its tables.",
        REPO + "infra/terraform/foundation/lake.tf",
    ),
    node(
        C[3],
        RB,
        DW,
        NH,
        "runtime",
        "Redshift Serverless",
        "SQL on the lake, 150 RPU-h",
        "Every OMOP reader goes through it, in SQL that also runs on the staging Postgres. "
        "Billed per second of compute, capped at 150 RPU-hours a month. A Data API session is "
        "billed until it ends, so RedshiftSession ends it when its block ends.",
        REPO + "infra/terraform/foundation/redshift.tf",
    ),
    node(
        C[4],
        RB,
        DW,
        NH,
        "runtime",
        "Fargate tasks",
        "on demand, x86",
        "Heavy jobs leave the laptop: gwas (PLINK 2 and REGENIE), exomiser, lirical, bias "
        "(BIAS-2015), and synth (synthetic releases and their reports); monitor, the privacy "
        "checks, daily at 11:00 UTC; and bastion, the tunnel to Redshift. Billed only while a "
        "task runs. Genomics inputs and outputs are in the genomics bucket.",
        REPO + "infra/terraform/app",
    ),
    arrow([(C[0] + DW, ma), (C[1], ma)], "HTTPS", C[0] + DW + 4, ma - 6),
    arrow([(C[1] + DW, ma), (C[2], ma)], "agent", C[1] + DW + 8, ma - 6),
    arrow(
        [(C[1] + DW / 2, RA + NH), (C[1] + DW / 2, RB)], "read, write", C[1] + DW / 2 + 8, RB - 8
    ),
    arrow([(C[2] + DW, mb), (C[3], mb)]),
    arrow([(C[4], mb), (C[3] + DW, mb)]),
]

# Laptop.
RL = 300
s.append(
    panel(
        40,
        265,
        1160,
        110,
        "The laptop",
        "Scripts, the ETL's staging database, and the R and Hail containers. Nothing heavy runs "
        "in local Docker; the containers here are for R's and Hail's own toolchains.",
    )
)
s += [
    node(
        C[0],
        RL,
        DW,
        NH,
        "ops",
        "MCP server",
        "stdio, for Claude Code",
        "The agent's four read-only tools for Claude Code, over stdio (agents/mcp_server.py, "
        ".mcp.json). Nothing serves MCP on the public demo.",
        REPO + "src/ehr_rwe_eln/agents/mcp_server.py",
    ),
    node(
        C[1],
        RL,
        DW,
        NH,
        "runtime",
        "Compose Postgres",
        "ETL staging and pytest",
        "Postgres 18 + pgvector 0.8.7 in Docker Compose, ports on 127.0.0.1. The ETL, cohorts, "
        "and the ELN bridge write OMOP here; publish_omop.py copies it to the lake and "
        "reconcile_lake.py checks every column. pytest uses ehr_rwe_eln_test.",
        REPO + "docker-compose.yml",
    ),
    node(
        C[2],
        RL,
        DW,
        NH,
        "runtime",
        "hades container",
        "OHDSI R tools",
        "R 4.6.1 and Java 21 with OHDSI HADES: DataQualityDashboard, CohortMethod, and "
        "TrialEmulation. scripts/hades.py starts the bastion task, opens a tunnel, and connects "
        "over JDBC with a one-hour IAM password.",
        REPO + "docker/hades.Dockerfile",
    ),
    node(
        C[3],
        RL,
        DW,
        NH,
        "ops",
        "scripts/*.py",
        "uv run, start every job",
        "Every build and analysis step is a script: uv run python scripts/<name>.py. The run_*.py "
        "scripts build an image if needed, start Fargate tasks, wait, and download the results.",
        REPO + "scripts",
    ),
    node(
        C[4],
        RL,
        DW,
        NH,
        "runtime",
        "hail container",
        "GWAS cross-check",
        "Hail pins pandas below 3, PySpark 3.5, and Java 11, so it has its own image, built only "
        "on request. Reruns the GWAS and compares it with REGENIE's.",
        REPO + "docker/hail.Dockerfile",
    ),
    arrow(
        [
            (C[1] + DW, RL + 16),
            (C[2] - 12, RL + 16),
            (C[2] - 12, RB + NH - 10),
            (C[2], RB + NH - 10),
        ]
    ),
    arrow(
        [(C[2] + DW, RL + 16), (C[3] - 14, RL + 16), (C[3] - 14, RB + NH - 6), (C[3], RB + NH - 6)]
    ),
    arrow(
        [(C[3] + DW, RL + 16), (C[4] - 14, RL + 16), (C[4] - 14, RB + NH - 6), (C[4], RB + NH - 6)]
    ),
]
s.append(f'<g transform="translate(0,{SHIFT})">')

# Modules.
R = [240, 320, 400, 480, 560]
m = [r + NH // 2 for r in R]
s.append(
    panel(
        40,
        190,
        1160,
        470,
        "Modules and data flow",
        "The cohort pipeline builds the OMOP tables every other module reads. The ELN bridge "
        "and the genomics panel write rows back into them.",
    )
)
s += [
    node(
        C[0],
        R[0],
        DW,
        NH,
        "outside",
        "Synthea 3.3.0",
        "synthetic patients, CSV",
        "Open-source synthetic patient generator. Seed and reference date are fixed, so the same "
        "arguments give the same people: 23,421 by default.",
        "https://github.com/synthetichealth/synthea",
    ),
    node(
        C[0],
        R[1],
        DW,
        NH,
        "outside",
        "OHDSI Athena",
        "standard vocabularies",
        "SNOMED, LOINC, RxNorm, CVX, and ICD10CM, plus Gender, Race, and Ethnicity. Downloaded "
        "under their own licenses and never committed.",
        "https://athena.ohdsi.org",
    ),
    node(
        C[0],
        R[3],
        DW,
        NH,
        "data",
        "ELN entries",
        "300 synthetic, with answers",
        "Free-text lab notebook entries on 200 hypertension subjects, generated with the "
        "extraction each should produce. Default, hard, and adversarial entries (prompt "
        "injections included).",
        REPO + "src/ehr_rwe_eln/eln/synthetic.py",
    ),
    node(
        C[0],
        R[4],
        DW,
        NH,
        "outside",
        "Amazon Bedrock",
        "Claude Opus 4.6, IAM auth",
        "Claude on Bedrock through the Anthropic SDK's AnthropicBedrock client, with AWS "
        "credentials (SSO locally, the task role on ECS); no API key. ELN extraction calls it a "
        "few entries at a time; variant curation sends it passages that name a variant.",
        "https://docs.claude.com/en/docs/build-with-claude/claude-on-amazon-bedrock",
    ),
    node(
        C[1],
        R[0],
        DW,
        NH,
        "module",
        "Cohort pipeline",
        "ETL, eras, cohort YAML",
        "Synthea CSV to OMOP CDM v5.4, checked against OHDSI ETL-Synthea with every difference "
        "explained. Condition "
        "and drug eras, keys and indices, then cohorts built from YAML definitions.",
        MOD + "cohort.md",
    ),
    node(
        C[1],
        R[3],
        DW,
        NH,
        "module",
        "ELN bridge",
        "text to typed records",
        "Claude extracts samples and results into a Pydantic model, validated before anything "
        "is stored. Scored for precision and recall against the known answers.",
        MOD + "eln.md",
    ),
    node(
        C[2],
        R[0],
        DW,
        R[3] + NH - R[0],
        "data",
        "OMOP CDM v5.4",
        "S3 Tables, via Redshift",
        "The one OMOP database every module shares: person, visits, conditions, drugs, "
        "measurements, eras, cohorts, and the ELN's and the panel's rows. Built in the staging "
        "Postgres, published to the lake, read through Redshift.",
        "https://ohdsi.github.io/CommonDataModel/cdm54.html",
    ),
    node(
        C[2],
        R[4],
        DW,
        NH,
        "data",
        "FHIR R4 bundle",
        "Specimen, Observation",
        "The same samples and results as FHIR R4 resources, in data/eln/fhir_bundle.json, for "
        "systems that speak FHIR rather than OMOP.",
        MOD + "eln.md",
    ),
    node(
        C[3],
        R[0],
        DW,
        NH,
        "module",
        "Data quality",
        "DQD 2.9.1, 2,384 checks",
        "OHDSI DataQualityDashboard 2.9.1 in R, in the hades container, against the lake: "
        "conformance, completeness, and plausibility checks (the Kahn framework), loaded into "
        "the dq schema.",
        MOD + "data_quality.md",
    ),
    node(
        C[3],
        R[1],
        DW,
        NH,
        "module",
        "Trial emulation",
        "4 protocols in YAML",
        "Eligibility, strategies, time zero, and outcomes in YAML. Propensity score weights, "
        "weighted Kaplan-Meier risks, Cox hazard ratios, bootstrap intervals, and negative "
        "control outcomes, in Python; OHDSI CohortMethod and TrialEmulation in R as checks.",
        MOD + "trial_emulation.md",
    ),
    node(
        C[3],
        R[2],
        DW,
        NH,
        "module",
        "Synthetic data",
        "DP releases, on Fargate",
        "Differentially private releases from a Bayesian network, a DP-SGD autoencoder, MST, "
        "and AIM, an independent-columns baseline, and a 30% holdout to judge them against. "
        "Made and evaluated by the synth task; the monitor reruns the privacy checks daily.",
        MOD + "synthetic_data.md",
    ),
    node(
        C[3],
        R[3],
        DW,
        NH,
        "module",
        "Synthetic genomics",
        "stdpopsim study, GWAS",
        "5,000 adults on three simulated chromosomes, with an odds ratio of 1.4 planted on "
        "hypertension. A GWAS is checked against the planted effect. A clinical panel puts "
        "real ClinVar variants at their GRCh38 positions in the same people, and its carriers "
        "go back into OMOP as measurement rows.",
        MOD + "genomics.md",
    ),
    node(
        C[3],
        R[4],
        DW,
        NH,
        "module",
        "Variant curation",
        "ACMG rules, expert panels",
        "Classifies the panel's variants with each gene's ClinGen expert panel thresholds, "
        "from gnomAD v4 frequencies and Ensembl VEP consequences, scored against ClinVar and "
        "ClinGen expert panels, and against BIAS-2015 as a baseline. Claude proposes literature "
        "evidence, every quote checked in code; HPO, Exomiser, and LIRICAL phenotype rankings "
        "add context; a curator decides on /curation/. Results in the curation schema.",
        MOD + "curation.md",
    ),
    node(
        C[4],
        R[0],
        DW,
        NH,
        "data",
        "dq schema",
        "Aurora, shown at /dq/",
        "Each run's checks, thresholds, and pass rates, shown at /dq/.",
        MOD + "data_quality.md",
    ),
    node(
        C[4],
        R[1],
        DW,
        NH,
        "data",
        "tte schema",
        "Aurora, shown at /tte/",
        "Attrition, balance, estimates, and negative controls for each protocol, shown at /tte/.",
        MOD + "trial_emulation.md",
    ),
    node(
        C[4],
        R[2],
        DW,
        NH,
        "data",
        "synth schema",
        "Aurora, shown at /synth/",
        "Each release with its provenance, fidelity, utility, trial parity, and privacy risk "
        "reports, plus a data card per release. Shown at /synth/.",
        REPO + "docs/synthetic_data_methodology.md",
    ),
    node(
        C[4],
        R[3],
        DW,
        NH,
        "data",
        "Genomics files",
        "VCF, PLINK, dbGaP tables",
        "Laid out as dbGaP distributes a study, in data/genomics and the genomics bucket, where "
        "the Fargate tasks read them. The registry linking study codes to persons is written "
        "apart, to data/registry/.",
        MOD + "genomics.md",
    ),
    node(
        C[4],
        R[4],
        DW,
        NH,
        "runtime",
        "REGENIE GWAS",
        "Fargate, Hail cross-check",
        "PLINK 2 QC and principal components, then REGENIE, as the gwas Fargate task. Hail "
        "reruns it and compares the results variant by variant.",
        REPO + "scripts/run_regenie.py",
    ),
    arrow([(C[0] + DW, m[0]), (C[1], m[0])], "CSV", C[0] + DW + 8, m[0] - 6),
    arrow(
        [(C[0] + DW, m[1]), (C[1] + DW / 2, m[1]), (C[1] + DW / 2, R[0] + NH)],
        "vocabularies",
        C[0] + DW + 8,
        m[1] - 6,
    ),
    arrow([(C[1] + DW, m[0]), (C[2], m[0])], "ETL", C[1] + DW + 8, m[0] - 6),
    arrow([(C[0] + DW, m[3]), (C[1], m[3])], "text", C[0] + DW + 8, m[3] - 6),
    arrow(
        [(C[0] + DW, m[4]), (C[1] + 40, m[4]), (C[1] + 40, R[3] + NH)],
        "extract",
        C[0] + DW + 8,
        m[4] - 6,
    ),
    arrow([(C[1] + DW, m[3]), (C[2], m[3])], "rows", C[1] + DW + 8, m[3] - 6),
    arrow(
        [(C[1] + DW - 40, R[3] + NH), (C[1] + DW - 40, m[4]), (C[2], m[4])],
        "FHIR R4",
        C[1] + DW - 34,
        m[4] - 6,
    ),
]
for i in range(4):
    s.append(arrow([(C[2] + DW, m[i]), (C[3], m[i])]))
    s.append(arrow([(C[3] + DW, m[i]), (C[4], m[i])]))
s.append(arrow([(C[4] + DW / 2, R[3] + NH), (C[4] + DW / 2, R[4])]))
s.append(arrow([(C[3] + DW / 2, R[3] + NH), (C[3] + DW / 2, R[4])]))
# Below the bottom row: Claude proposes literature evidence for variant curation.
low = R[4] + NH + 18
s.append(
    arrow(
        [
            (C[0] + DW / 2, R[4] + NH),
            (C[0] + DW / 2, low),
            (C[3] + DW / 2, low),
            (C[3] + DW / 2, R[4] + NH),
        ],
        "literature",
        C[0] + DW / 2 + 8,
        low - 6,
    )
)

# Quality checks.
RQ = 715
mq = RQ + NH // 2
s.append(panel(40, 680, 1160, 110, "Quality checks", "What runs before code reaches main."))
s += [
    node(
        C[0],
        RQ,
        DW,
        NH,
        "ops",
        "pre-commit",
        "ruff, secrets, file checks",
        "Lint, format, YAML, large-file, private-key, and gitleaks secret checks before a "
        "commit lands.",
        REPO + ".pre-commit-config.yaml",
    ),
    node(
        C[1],
        RQ,
        DW,
        NH,
        "outside",
        "GitHub",
        "pull request to main",
        "main is protected: every change arrives as a pull request, up to date with main, with "
        "lint-test, secrets, and terraform passing, and is squash-merged.",
        "https://github.com/toddcreasy/ehr-rwe-eln/pulls",
    ),
    node(
        C[2],
        RQ,
        DW,
        NH,
        "ops",
        "GitHub Actions",
        "lint-test, secrets, terraform",
        "lint-test: uv sync --locked, ruff, and pytest against the same pgvector image as "
        "Compose. secrets: gitleaks over every commit and every file, for keys, tokens, "
        "passwords, usernames, and email addresses. terraform: fmt, validate, tflint, trivy.",
        REPO + ".github/workflows",
    ),
    node(
        C[3],
        RQ,
        DW,
        NH,
        "ops",
        "pytest",
        "Compose Postgres, no network",
        "Fast tests on small planted data, each in a rolled-back transaction in its own test "
        "database. Nothing leaves the machine.",
        REPO + "tests",
    ),
    node(
        C[4],
        RQ,
        DW,
        NH,
        "ops",
        "evals",
        "real model, run by hand",
        "Golden cases for the agent, ELN extraction, and literature evidence against Claude on "
        "Bedrock. Slow and billed, so never in CI.",
        REPO + "evals",
    ),
    arrow([(C[0] + DW, mq), (C[1], mq)]),
    arrow([(C[1] + DW, mq), (C[2], mq)]),
    arrow([(C[2] + DW, mq), (C[3], mq)]),
]

# Legend.
LY = 810
s.append(panel(40, LY, 1160, 120, "Key", "Box colors."))
for i, (kind, name, sub) in enumerate(
    [
        ("module", "Module", "Python package"),
        ("data", "Data or output", "database, files"),
        ("runtime", "Runtime", "services, containers"),
        ("ops", "Operations", "scripts, checks"),
        ("outside", "Outside", "not ours"),
    ]
):
    s.append(node(60 + i * 230, LY + 40, DW, NH, kind, name, sub, f"{name}: {sub}"))
s.append("</g>")
s.append("</svg>")
(OUT / "architecture.svg").write_text("\n".join(s) + "\n")
print("wrote", OUT / "architecture.svg")

# Schema: one database, the OMOP tables in cdm, one schema per module, and what lives outside.
CDM = "https://ohdsi.github.io/CommonDataModel/cdm54.html#"
MIG = REPO + "migrations/versions/"
TW, TH = 165, 48
X = [75, 250, 425, 600]
MX = [820, 1030]
MW = 150
# Everything below the module schemas moves down this far, to fit the curation schema.
SHIFT_SCHEMA = 390
s = header(
    1240,
    860 + SHIFT_SCHEMA,
    "ehr-rwe-eln data: OMOP in the lake, one Aurora schema per module",
    "The OMOP CDM v5.4 tables are Iceberg tables in the cdm namespace of an S3 table bucket, read "
    "through Redshift Serverless: clinical events keyed to person, derived eras and cohorts, and "
    "the Athena vocabularies keyed to concept. Aurora PostgreSQL holds each module's results in "
    "the dq, tte, eln, synth, and curation schemas, and the app's own state. Genotypes, "
    "registries, the FHIR bundle, and data cards are files under data/.",
)
s.append('<text x="40" y="26" class="t" font-size="15" font-weight="700">ehr_rwe_eln</text>')
s.append(
    '<text x="140" y="26" class="s">Row counts are from the 23,421-person build. '
    "Open the SVG on its own and hover a table for what it holds.</text>"
)


def label(x, y, text):
    return f'<text x="{x}" y="{y}" class="t" font-size="12" font-weight="600">{esc(text)}</text>'


def table(x, y, kind, name, sub, note, link, w=TW):
    return node(x, y, w, TH, kind, name, sub, note, link)


s.append(
    panel(
        40,
        40,
        1160,
        560 + SHIFT_SCHEMA,
        "OMOP in the lake, module results in Aurora",
        "scripts/build_omop.py builds cdm in the staging Postgres and scripts/publish_omop.py "
        "copies it to the lake. Alembic migrations create the Aurora schemas and record their "
        "version in public.alembic_version. Foreign keys on the left are OMOP's own; Iceberg "
        "does not enforce them. A second patient population would be a second CDM namespace, "
        "not a second database.",
    )
)

# cdm.
s.append(
    panel(
        55,
        70,
        735,
        515,
        "Lake: cdm, OMOP CDM v5.4 in S3 Tables",
        "The OHDSI standard tables, as Apache Iceberg, read through Redshift Serverless. In "
        "OMOP's model, 17 foreign keys point at person and 118 at concept.",
    )
)
s.append(label(75, 112, "Clinical data: every row has person_id, a foreign key to person"))
clinical = [
    ("person", "23,421 people", "One row per patient: birth year, sex, race, ethnicity."),
    (
        "observation_period",
        "one per person",
        "The span of time each person's records cover. Analyses count events only inside it.",
    ),
    ("death", "3,421 rows", "Date and cause for people who died during the simulation."),
    ("visit_occurrence", "1.7M rows", "Encounters: outpatient, inpatient, emergency, and others."),
    ("condition_occurrence", "418K rows", "Diagnoses, coded in SNOMED."),
    ("drug_exposure", "1.9M rows", "Prescriptions and administrations, coded in RxNorm and CVX."),
    ("procedure_occurrence", "2.1M rows", "Procedures, coded in SNOMED."),
    (
        "measurement",
        "16.3M rows",
        "Lab results and vital signs, coded in LOINC. The ELN bridge adds its lab results here.",
    ),
    ("observation", "7.9M rows", "Facts that are not measurements: history, social, survey."),
    ("device_exposure", "41K rows", "Devices used on or implanted in a person."),
    ("specimen", "ELN samples", "Samples from lab notebook entries, written by the ELN bridge."),
    (
        "fact_relationship",
        "sample to result",
        "Links each ELN specimen to the measurements taken from it. Written by the ELN bridge.",
    ),
]
for i, (name, sub, note) in enumerate(clinical):
    s.append(table(X[i % 4], 120 + (i // 4) * 58, "data", name, sub, note, CDM + name))

s.append(label(75, 310, "Derived: built from the clinical tables"))
derived = [
    ("condition_era", "396K rows", "Spans of continuous diagnosis, built by the cohort pipeline."),
    ("drug_era", "213K rows", "Spans of continuous drug use, built by the cohort pipeline."),
    ("cohort", "YAML cohorts", "People and index dates for each cohort definition in YAML."),
    ("cdm_source", "build metadata", "Source name, ETL date, and vocabulary version."),
]
for i, (name, sub, note) in enumerate(derived):
    s.append(table(X[i], 318, "data", name, sub, note, CDM + name))

s.append(label(75, 392, "Vocabularies from Athena: every *_concept_id is a foreign key to concept"))
vocab = [
    (
        "concept",
        "2.0M concepts",
        "Every code from every vocabulary, with its standard concept. A diagnosis or drug in "
        "the clinical tables is a concept_id here.",
    ),
    (
        "concept_relationship",
        "14.0M rows",
        "Mappings between concepts, such as a source code to its standard concept.",
    ),
    (
        "concept_ancestor",
        "11.1M rows",
        "Every concept's ancestors, so a cohort can ask for a drug class instead of each drug.",
    ),
    ("concept_synonym", "2.5M rows", "Alternative names for concepts."),
    ("vocabulary", "45 rows", "SNOMED, LOINC, RxNorm, CVX, ICD10CM, and the small ones."),
    ("domain", "50 rows", "Which table a concept belongs in: Condition, Drug, Measurement."),
    ("concept_class", "433 rows", "Kinds of concept within a vocabulary."),
    ("drug_strength", "210K rows", "Ingredient amounts per drug, for dose calculations."),
]
for i, (name, sub, note) in enumerate(vocab):
    s.append(table(X[i % 4], 400 + (i // 4) * 58, "ops", name, sub, note, CDM + name))
s.append(
    '<text x="75" y="540" class="s">Also defined, empty in this build: provider, care_site, '
    "location, cost, payer_plan_period, note, note_nlp,</text>"
)
s.append(
    '<text x="75" y="556" class="s">visit_detail, episode, episode_event, dose_era, metadata, '
    "source_to_concept_map, cohort_definition, relationship (724 rows).</text>"
)

# Module schemas.
s.append(
    panel(
        805,
        70,
        380,
        515 + SHIFT_SCHEMA,
        "Aurora: module schemas",
        "Each module's results and the app's state, in Aurora Serverless v2 PostgreSQL, created "
        "by Alembic migrations. Arrows are foreign keys.",
    )
)
mods = [
    (
        112,
        "dq: data quality",
        ("dq.run", "one per check run", "When a run happened and its overall scores."),
        ("dq.result", "2,384 per run", "One row per DQD check: threshold, violations, pass."),
        "run_id",
        MIG + "003_dq_results.py",
    ),
    (
        198,
        "tte: target trial emulation",
        ("tte.run", "one per analysis", "When the trial protocols ran, and on how many people."),
        ("tte.report", "one per protocol", "The bias report: attrition, balance, estimates."),
        "run_id",
        MIG + "005_tte_reports.py",
    ),
    (
        284,
        "eln: ELN bridge",
        ("eln.entry", "300 entries", "The free-text lab notebook entries."),
        ("eln.extraction", "one per entry", "What Claude extracted, as validated JSON."),
        "entry_id",
        MIG + "006_eln.py",
    ),
    (
        428,
        "synth: synthetic data",
        ("synth.release", "one per release", "Method, privacy budget, seed, and provenance."),
        ("synth.row", "synthetic rows", "The released rows, as JSON per row."),
        "release_id",
        MIG + "007_synth.py",
    ),
]
for y, title, parent, child, key, link in mods:
    s.append(label(820, y, title))
    s.append(table(MX[0], y + 8, "module", *parent, link, MW))
    s.append(table(MX[1], y + 8, "module", *child, link, MW))
    my = y + 8 + TH // 2
    s.append(arrow([(MX[1], my), (MX[0] + MW, my)]))
    s.append(f'<text x="{MX[0] + MW + 4}" y="{my - 6}" class="e">{key}</text>')
s.append(
    table(
        MX[0],
        350,
        "module",
        "eln.subject",
        "code to person_id",
        "Links each notebook subject code to a person in cdm.person. Kept as data, not a foreign "
        "key, the way a lab keeps its subject registry apart from its notebooks.",
        MIG + "006_eln.py",
        MW,
    )
)
s.append(
    table(
        MX[1],
        494,
        "module",
        "synth.report",
        "fidelity, privacy",
        "Fidelity, utility, trial parity, and privacy risk reports per release.",
        MIG + "008_synth_reports.py",
        MW,
    )
)
s.append(arrow([(MX[1], 518), (MX[0] + MW / 2, 518), (MX[0] + MW / 2, 484)]))
s.append(f'<text x="{MX[0] + MW / 2 + 6}" y="512" class="e">release_id</text>')
s.append(label(820, 572, "curation: variant curation"))
s.append(
    table(
        MX[0],
        580,
        "module",
        "curation.run",
        "one per run",
        "Which variants were curated, every source and version used, and for eval runs the"
        " agreement with ClinVar expert panels.",
        MIG + "013_curation.py",
        MW,
    )
)
s.append(
    table(
        MX[1],
        580,
        "module",
        "curation.assessment",
        "one per variant",
        "Evidence, criteria met and not assessed with reasons, points, and class.",
        MIG + "013_curation.py",
        MW,
    )
)
s.append(arrow([(MX[1], 604), (MX[0] + MW, 604)]))
s.append(f'<text x="{MX[0] + MW + 4}" y="598" class="e">run_id</text>')
s.append(
    table(
        MX[0],
        660,
        "module",
        "curation.proposal",
        "one per claim",
        "Literature evidence Claude proposed, with its PMID and quote, verified or rejected with"
        " the reason. Changes nothing until a curator accepts it.",
        MIG + "015_curation_proposals.py",
        MW,
    )
)
s.append(
    table(
        MX[1],
        660,
        "module",
        "curation.decision",
        "added to, never changed",
        "A curator's decision: who, when, the proposals accepted, the criteria, points, and the"
        " class chosen, with a note when it differs from the score.",
        MIG + "016_curation_decisions.py",
        MW,
    )
)
s.append(
    table(
        MX[0],
        740,
        "module",
        "curation.phenotype",
        "per variant, HPO release",
        "Where each carrier's HPO phenotype score falls among the study's subjects. Context for"
        " the curator, not evidence. No foreign key: matched by variant_id.",
        MIG + "017_curation_phenotype.py",
        MW,
    )
)
s.append(
    table(
        MX[1],
        740,
        "module",
        "curation.exomiser",
        "per variant, data release",
        "Where Exomiser's phenotype score ranks the variant's gene for each carrier. Context for"
        " the curator, not evidence. No foreign key: matched by variant_id.",
        MIG + "022_curation_exomiser.py",
        MW,
    )
)
s.append(label(820, 820, "synth, continued, and the app's own"))
for y, (left, right) in [
    (
        828,
        (
            (
                "synth.monitor_run",
                "one per privacy check",
                "Each scheduled privacy check: which releases it reran and what changed. The "
                "monitor task writes one a day.",
                MIG + "011_synth_monitor.py",
            ),
            (
                "synth.distribution",
                "who got each release",
                "Each release's recipients, its withdrawal, and their confirmations that they "
                "deleted it.",
                MIG + "009_synth_withdrawal.py",
            ),
        ),
    ),
    (
        908,
        (
            (
                "omop_stats",
                "concept counts, build",
                "Person counts per concept, precomputed from the lake by "
                "scripts/build_omop_stats.py, so the agent's public calls never reach Redshift. "
                "Counts under 11 are suppressed and never stored.",
                MIG + "020_omop_stats.py",
            ),
            (
                "agent.daily_usage",
                "tokens per day",
                "Tokens /api/agent spent each day, for the daily limit. The langgraph schema, "
                "not drawn, holds the literature graph's checkpoints.",
                MIG + "018_agent_daily_usage.py",
            ),
        ),
    ),
]:
    s.append(table(MX[0], y, "module", *left, MW))
    s.append(table(MX[1], y, "module", *right, MW))
s.append(arrow([(MX[0] + MW / 2, 660), (MX[0] + MW / 2, 628)]))
s.append(f'<text x="{MX[0] + MW / 2 + 6}" y="648" class="e">run_id</text>')
s.append(arrow([(MX[1] + MW / 2, 660), (MX[1] + MW / 2, 628)]))
s.append(
    f'<text x="{MX[1] + MW / 2 - 6}" y="648" class="e" text-anchor="end">run_id, variant_id</text>'
)
s.append(f'<g transform="translate(0,{SHIFT_SCHEMA})">')

# Outside the database.
s.append(
    panel(
        40,
        620,
        1160,
        110,
        "On the laptop",
        "The staging Postgres and files under data/, which is gitignored.",
    )
)
outside = [
    (
        "Compose Postgres",
        "ETL staging, pytest",
        "The ETL, cohorts, and the ELN bridge write OMOP to ehr_rwe_eln here, and "
        "publish_omop.py copies it to the lake. pytest writes to ehr_rwe_eln_test and rolls "
        "back; it holds no patients.",
        REPO + "docker-compose.yml",
    ),
    (
        "data/genomics",
        "VCF, PLINK, phenotypes",
        "The simulated genotype study, laid out as dbGaP distributes one. GWAS tools read files, "
        "not tables.",
        MOD + "genomics.md",
    ),
    (
        "data/registry",
        "study code to person_id",
        "Links the genomics and ELN study codes to OMOP persons, kept apart from the study files.",
        MOD + "genomics.md",
    ),
    (
        "data/eln",
        "entries, FHIR R4 bundle",
        "The generated entries with their answers, and the FHIR R4 Specimen and Observation "
        "export.",
        MOD + "eln.md",
    ),
    (
        "data/synth/cards",
        "a data card per release",
        "What each synthetic release is, how it was made, and what it is safe to use for.",
        MOD + "synthetic_data.md",
    ),
]
for i, (name, sub, note, link) in enumerate(outside):
    s.append(node(C[i], 655, DW, NH, "outside", name, sub, note, link))

s.append(panel(40, 750, 1160, 100, "Key", "Box colors."))
for i, (kind, name, sub) in enumerate(
    [
        ("data", "OMOP table", "clinical or derived"),
        ("ops", "Vocabulary table", "from Athena"),
        ("module", "Aurora table", "module results, app state"),
        ("outside", "On the laptop", "staging, files"),
    ]
):
    s.append(node(60 + i * 230, 780, DW, NH, kind, name, sub, f"{name}: {sub}"))
s.append("</g>")
s.append("</svg>")
(OUT / "schema.svg").write_text("\n".join(s) + "\n")
print("wrote", OUT / "schema.svg")
