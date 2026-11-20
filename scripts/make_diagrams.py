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


W, H = 1240, 1020
# Everything below the runtime panel moves down this far, to fit the monitor under the database.
SHIFT = 70
NH, DW = 56, 190
C = [60, 290, 520, 750, 980]
s = header(
    W,
    H,
    "ehr-rwe-eln: one OMOP database, seven modules, all on one machine",
    "Synthea patients and Athena vocabularies become an OMOP CDM v5.4 database in Postgres. Data "
    "quality checks, target trial emulation, synthetic data releases, and a synthetic genotype "
    "study read it; the ELN bridge writes lab results into it with Claude; variant curation "
    "classifies the study's clinical panel, with literature evidence proposed by Claude. A "
    "FastAPI app serves the results on 127.0.0.1.",
)
s.append('<text x="40" y="26" class="t" font-size="15" font-weight="700">ehr-rwe-eln</text>')
s.append(
    '<text x="140" y="26" class="s">Dashed boxes are outside the machine. '
    "Open the SVG on its own and hover a box for what it does and why.</text>"
)

# Runtime.
RT = 90
mt = RT + NH // 2
s.append(
    panel(
        40,
        40,
        1160,
        130 + SHIFT,
        "Docker Compose, every port on 127.0.0.1",
        "docker compose up -d starts the database, the app, and the privacy monitor. No cloud "
        "account; the only "
        "outside service is the Anthropic API, on your own key. There is no sign-in, which is "
        "why nothing listens beyond this machine.",
    )
)
s += [
    node(
        C[0],
        RT,
        DW,
        NH,
        "outside",
        "Browser",
        "http://127.0.0.1:8000",
        "The dashboards: data quality, target trials, ELN extraction, and synthetic releases.",
    ),
    node(
        C[1],
        RT,
        DW,
        NH,
        "runtime",
        "app container",
        "FastAPI /api + static Next.js",
        "One container serves the API under /api and the frontend at /. The frontend is a "
        "Next.js static export, so no Node server runs. Routes for data quality, trials, ELN, "
        "synthetic data, and the agent at POST /api/agent.",
        REPO + "src/ehr_rwe_eln/api/main.py",
    ),
    node(
        C[2],
        RT,
        DW,
        NH,
        "runtime",
        "db container",
        "Postgres 18 + pgvector 0.8.7",
        "One database, ehr_rwe_eln, with 23,421 people. Schemas: cdm, dq, tte, eln, synth. "
        "Tests use ehr_rwe_eln_test. Data lives in the ehr-rwe-eln-db volume.",
        REPO + "docker-compose.yml",
    ),
    node(
        C[3],
        RT,
        DW,
        NH,
        "ops",
        "scripts/*.py",
        "uv run on the host",
        "Every build and analysis step is a script run with uv run python scripts/<name>.py. "
        "Each writes to ehr_rwe_eln.",
        REPO + "scripts",
    ),
    node(
        C[4],
        RT,
        DW,
        NH,
        "runtime",
        "hail container",
        "genomics profile, on request",
        "Hail pins pandas below 3, PySpark 3.5, and Java 11, so it gets its own 2.4 GB image, "
        "built only by docker compose run --rm --build hail. No ports; it reads and writes "
        "data/genomics.",
        REPO + "docker/hail.Dockerfile",
    ),
    arrow([(C[0] + DW, mt), (C[1], mt)], "HTTP", C[0] + DW + 8, mt - 6),
    arrow([(C[1] + DW, mt), (C[2], mt)], "read", C[1] + DW + 8, mt - 6),
    arrow([(C[3], mt), (C[2] + DW, mt)], "write", C[2] + DW + 8, mt - 6),
    node(
        C[2],
        RT + NH + 18,
        DW,
        NH,
        "runtime",
        "monitor container",
        "privacy checks every 24h",
        "Reruns the privacy attacks on every release when a source table or the synth code has "
        "changed since the last check, and skips otherwise. Each run is a row in "
        "synth.monitor_run; the last one shows on /synth/. Set MONITOR_INTERVAL_HOURS in .env.",
        REPO + "src/ehr_rwe_eln/synth/monitor.py",
    ),
    arrow(
        [(C[2] + DW / 2, RT + NH + 18), (C[2] + DW / 2, RT + NH)],
        "read, write reports",
        C[2] + DW / 2 + 8,
        RT + NH + 13,
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
        "writes lab results back into them.",
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
        "cdm schema, Postgres",
        "The one database every module shares: person, visits, conditions, drugs, "
        "measurements, eras, cohorts, and the ELN's specimen and measurement rows.",
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
        "2,384 DQD checks",
        "Every check in OHDSI DataQualityDashboard v2.9.0, grouped by the Kahn framework "
        "(conformance, completeness, plausibility), scored, and matched against DQD itself.",
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
        "control outcomes.",
        MOD + "trial_emulation.md",
    ),
    node(
        C[3],
        R[2],
        DW,
        NH,
        "module",
        "Synthetic data",
        "DP releases, 2 specs",
        "Differentially private Bayesian network and DP-SGD autoencoder releases, an "
        "independent-columns baseline, and a 30% holdout to judge them against.",
        MOD + "synthetic_data.md",
    ),
    node(
        C[3],
        R[3],
        DW,
        NH,
        "module",
        "Synthetic genomics",
        "msprime study, GWAS",
        "5,000 adults on three simulated chromosomes, with an odds ratio of 1.4 planted on "
        "hypertension. A GWAS is checked against the planted effect. A clinical panel puts "
        "real ClinVar variants at their GRCh38 positions in the same people.",
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
        "ClinGen expert panels. Claude proposes literature evidence, every quote checked in code; "
        "HPO phenotype scores add context; a curator decides on /curation/. Results in the "
        "curation schema.",
        MOD + "curation.md",
    ),
    node(
        C[4],
        R[0],
        DW,
        NH,
        "data",
        "dq schema",
        "results per run, dashboard",
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
        "bias report per protocol",
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
        "releases, reports, data cards",
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
        "data/genomics",
        "VCF, PLINK, dbGaP tables",
        "Laid out as dbGaP distributes a study. The registry linking study codes to persons is "
        "written apart, to data/registry/.",
        MOD + "genomics.md",
    ),
    node(
        C[4],
        R[4],
        DW,
        NH,
        "runtime",
        "Hail GWAS",
        "MatrixTable, cross-check",
        "Reruns the GWAS in Hail and compares score statistics variant by variant with the "
        "Python GWAS.",
        REPO + "scripts/hail_gwas.py",
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
        "lint-test and secrets passing, and is squash-merged.",
        "https://github.com/toddcreasy/ehr-rwe-eln/pulls",
    ),
    node(
        C[2],
        RQ,
        DW,
        NH,
        "ops",
        "GitHub Actions",
        "lint-test, secrets",
        "lint-test: uv sync --locked, ruff, and pytest against the same pgvector image as "
        "Compose. secrets: gitleaks over every commit and every file, for keys, tokens, "
        "passwords, usernames, and email addresses.",
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
        "Golden cases for the agent, ELN extraction, and literature evidence against Claude. "
        "Slow and billed, so never in CI.",
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
        ("runtime", "Runtime", "containers"),
        ("ops", "Operations", "scripts, checks"),
        ("outside", "Outside", "external source"),
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
SHIFT_SCHEMA = 230
s = header(
    1240,
    860 + SHIFT_SCHEMA,
    "ehr-rwe-eln database: OMOP tables in cdm, one schema per module",
    "One Postgres database, ehr_rwe_eln. The cdm schema holds the OMOP CDM v5.4 tables: clinical "
    "events keyed to person, derived eras and cohorts, and the Athena vocabularies keyed to "
    "concept. The dq, tte, eln, synth, and curation schemas hold each module's results. Genotypes, "
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
        "Postgres database ehr_rwe_eln",
        "Every module reads and writes this one database. Alembic migrations create the module "
        "schemas and record their version in public.alembic_version; scripts/build_omop.py "
        "builds cdm. A second patient population would be a second CDM schema here, not a "
        "second database.",
    )
)

# cdm.
s.append(
    panel(
        55,
        70,
        735,
        515,
        "cdm schema: OMOP CDM v5.4",
        "The OHDSI standard tables. 17 foreign keys point at person and 118 at concept.",
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
        "Module schemas",
        "Each module's results, created by Alembic migrations. Arrows are foreign keys.",
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
        "Outside this database",
        "Files under data/, which is gitignored, and the test database.",
    )
)
outside = [
    (
        "ehr_rwe_eln_test",
        "same schemas, pytest only",
        "Where pytest writes and rolls back, so tests never touch ehr_rwe_eln. Holds no patients.",
        REPO + "tests/conftest.py",
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
        ("module", "Module table", "dq, tte, eln, synth, curation"),
        ("outside", "Outside", "files, test database"),
    ]
):
    s.append(node(60 + i * 230, 780, DW, NH, kind, name, sub, f"{name}: {sub}"))
s.append("</g>")
s.append("</svg>")
(OUT / "schema.svg").write_text("\n".join(s) + "\n")
print("wrote", OUT / "schema.svg")
