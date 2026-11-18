"""Draw docs/architecture.svg: what runs where, how data moves between the modules, and the checks.

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


W, H = 1240, 920
NH, DW = 56, 190
C = [60, 290, 520, 750, 980]
s = header(
    W,
    H,
    "ehr-rwe-eln: one OMOP database, six modules, all on one machine",
    "Synthea patients and Athena vocabularies become an OMOP CDM v5.4 database in Postgres. Data "
    "quality checks, target trial emulation, synthetic data releases, and a synthetic genotype "
    "study read it; the ELN bridge writes lab results into it with Claude. A FastAPI app serves "
    "the results on 127.0.0.1.",
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
        130,
        "Docker Compose, every port on 127.0.0.1",
        "docker compose up -d starts the database and the app. No cloud account; the only "
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
        "One Postgres holds two databases built the same way: ehr_rwe_eln (1,172 people) and "
        "ehr_rwe_eln_tte (23,421 people, for trial emulation, synthetic data, and genomics). "
        "Schemas: cdm, dq, tte, eln, synth. Data lives in the ehr-rwe-eln-db volume.",
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
        "Each writes to the database DB_NAME names.",
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
]

# Modules.
R = [240, 320, 400, 480, 560]
m = [r + NH // 2 for r in R]
s.append(
    panel(
        40,
        190,
        1160,
        440,
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
        "arguments give the same people: 1,172 for the default build, 23,421 for trial emulation.",
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
        "Anthropic API",
        "Claude Opus 5.5, your key",
        "The only outside service. Extraction runs through the Message Batches API at half "
        "price. ANTHROPIC_API_KEY lives only in .env.",
        "https://docs.claude.com",
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
        "hypertension. A GWAS is checked against the planted effect.",
        MOD + "genomics.md",
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

# Quality checks.
RQ = 685
mq = RQ + NH // 2
s.append(panel(40, 650, 1160, 110, "Quality checks", "What runs before code reaches main."))
s += [
    node(
        C[0],
        RQ,
        DW,
        NH,
        "ops",
        "pre-commit",
        "ruff, secrets, file checks",
        "Lint, format, YAML, large-file, and private-key checks before a commit lands.",
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
        "lint-test passing, and is squash-merged.",
        "https://github.com/toddcreasy/ehr-rwe-eln/pulls",
    ),
    node(
        C[2],
        RQ,
        DW,
        NH,
        "ops",
        "GitHub Actions",
        "lint-test, Postgres service",
        "uv sync --locked, ruff, and pytest against the same pgvector image as Compose.",
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
        "Golden cases for the agent and ELN extraction against Claude. Slow and billed, so "
        "never in CI.",
        REPO + "evals",
    ),
    arrow([(C[0] + DW, mq), (C[1], mq)]),
    arrow([(C[1] + DW, mq), (C[2], mq)]),
    arrow([(C[2] + DW, mq), (C[3], mq)]),
]

# Legend.
LY = 780
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
s.append("</svg>")
(OUT / "architecture.svg").write_text("\n".join(s) + "\n")
print("wrote", OUT / "architecture.svg")
