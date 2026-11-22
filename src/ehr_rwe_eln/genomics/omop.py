"""The clinical panel's carriers as OMOP measurement rows, with OMOP Genomic concepts.

OMOP Genomic is OHDSI's vocabulary of genes and variants, all in the Measurement domain. A
genetic test result is a measurement: measurement_concept_id names what was found (the variant,
or its gene), value_as_concept_id the genotype (LOINC answers Heterozygous and Homozygous). Only
carriers get rows, as a clinical panel report lists only what it found: no row for a variant
means not detected.

Each variant gets the most specific standard concept that exists:
1. its own DNA variant concept, whose name carries its GRCh38 position (SNVs only: the names of
   insertions and deletions follow HGVS, which shifts them right, while VCF shifts them left),
2. its own transcript variant concept, matched by HGVS c. notation on the MANE Select
   transcript (from Ensembl VEP), which is how insertions and deletions match,
3. otherwise its gene's variant concept, with the variant itself in measurement_source_value
   and measurement_source_concept_id 0, OMOP's convention for a source value with no concept.
OMOP Genomic holds about 125,000 standard DNA and transcript variants, mostly from cancer panels,
so most ClinVar variants land on step 3.

The date is each person's observation period end, a stand-in for a sample drawn when the data
were extracted: the panel has no test date, and this one is always inside the person's record.
Rows take ids from ID_OFFSET up, above the Synthea ETL's and below the ELN bridge's (which
deletes from 2,000,000,000 up), and each run replaces them.
"""

import gzip
from pathlib import Path

import psycopg

from ehr_rwe_eln.cohort.cdm import ATHENA_COPY

VOCABULARY = "OMOP Genomic"
ID_OFFSET = 1_900_000_000
ID_END = 2_000_000_000
LAB = 32856  # Type Concept: Lab
GENOTYPE_LOINC = {"0/1": "LA6706-1", "1/1": "LA6705-3"}  # Heterozygous, Homozygous

BUNDLE_TABLES = [
    "concept",
    "concept_class",
    "vocabulary",
    "concept_synonym",
    "concept_relationship",
    "concept_ancestor",
]

# Insert order follows the foreign keys: a new concept class names a concept (of the Concept
# Class vocabulary) that must exist first, and every concept names its class and vocabulary.
LOAD_SQL = [
    (
        "concept_class",
        """INSERT INTO cdm.concept SELECT b.* FROM bundle_concept b
           WHERE b.concept_id IN (SELECT concept_class_concept_id FROM bundle_concept_class
               WHERE concept_class_id IN (SELECT concept_class_id FROM bundle_concept
                   WHERE vocabulary_id = %(v)s))
             AND NOT EXISTS (SELECT 1 FROM cdm.concept c WHERE c.concept_id = b.concept_id)""",
    ),
    (
        "concept_class",
        """INSERT INTO cdm.concept_class SELECT b.* FROM bundle_concept_class b
           WHERE b.concept_class_id IN (SELECT concept_class_id FROM bundle_concept
               WHERE vocabulary_id = %(v)s)
             AND NOT EXISTS (SELECT 1 FROM cdm.concept_class c
                 WHERE c.concept_class_id = b.concept_class_id)""",
    ),
    (
        "vocabulary",
        """INSERT INTO cdm.vocabulary SELECT b.* FROM bundle_vocabulary b
           WHERE b.vocabulary_id = %(v)s
             AND NOT EXISTS (SELECT 1 FROM cdm.vocabulary c
                 WHERE c.vocabulary_id = b.vocabulary_id)""",
    ),
    (
        "concept",
        """INSERT INTO cdm.concept SELECT b.* FROM bundle_concept b
           WHERE b.vocabulary_id = %(v)s
             AND NOT EXISTS (SELECT 1 FROM cdm.concept c WHERE c.concept_id = b.concept_id)""",
    ),
    (
        "concept_synonym",
        """INSERT INTO cdm.concept_synonym SELECT b.* FROM bundle_concept_synonym b
           JOIN cdm.concept c ON c.concept_id = b.concept_id AND c.vocabulary_id = %(v)s
           WHERE EXISTS (SELECT 1 FROM cdm.concept l WHERE l.concept_id = b.language_concept_id)
             AND NOT EXISTS (SELECT 1 FROM cdm.concept_synonym s
                 WHERE s.concept_id = b.concept_id
                   AND s.concept_synonym_name = b.concept_synonym_name
                   AND s.language_concept_id = b.language_concept_id)""",
    ),
    # Links to concepts outside the bundle that staging lacks are skipped (counted below).
    (
        "concept_relationship",
        """INSERT INTO cdm.concept_relationship SELECT b.* FROM bundle_concept_relationship b
           JOIN cdm.concept c1 ON c1.concept_id = b.concept_id_1
           JOIN cdm.concept c2 ON c2.concept_id = b.concept_id_2
           WHERE %(v)s IN (c1.vocabulary_id, c2.vocabulary_id)
             AND EXISTS (SELECT 1 FROM cdm.relationship r
                 WHERE r.relationship_id = b.relationship_id)
             AND NOT EXISTS (SELECT 1 FROM cdm.concept_relationship t
                 WHERE t.concept_id_1 = b.concept_id_1 AND t.concept_id_2 = b.concept_id_2
                   AND t.relationship_id = b.relationship_id)""",
    ),
    (
        "concept_ancestor",
        """INSERT INTO cdm.concept_ancestor SELECT b.* FROM bundle_concept_ancestor b
           JOIN cdm.concept a ON a.concept_id = b.ancestor_concept_id
           JOIN cdm.concept d ON d.concept_id = b.descendant_concept_id
           WHERE %(v)s IN (a.vocabulary_id, d.vocabulary_id)
             AND NOT EXISTS (SELECT 1 FROM cdm.concept_ancestor t
                 WHERE t.ancestor_concept_id = b.ancestor_concept_id
                   AND t.descendant_concept_id = b.descendant_concept_id)""",
    ),
]


def load_genomic_vocabulary(con: psycopg.Connection, bundle: Path) -> dict[str, int]:
    """OMOP Genomic from an Athena download into the cdm vocabulary tables, and nothing else in
    the download (it also carries newer copies of small vocabularies, which stay as loaded).
    Rows already loaded are kept. Returns rows added per table, and links skipped because
    their other concept is not loaded."""
    for table in BUNDLE_TABLES:
        path = bundle / f"{table.upper()}.csv"
        con.execute(f"CREATE TEMP TABLE bundle_{table} (LIKE cdm.{table})")
        with path.open("rb") as f:
            header = f.readline().decode().rstrip("\r\n").split("\t")
            f.seek(0)
            with con.cursor().copy(
                f"COPY bundle_{table} ({', '.join(header)}) FROM STDIN ({ATHENA_COPY})"
            ) as copy:
                while data := f.read(1 << 20):
                    copy.write(data)
    added: dict[str, int] = {}
    for table, sql in LOAD_SQL:
        added[table] = added.get(table, 0) + con.execute(sql, {"v": VOCABULARY}).rowcount
    added["relationships_skipped"] = con.execute(
        """SELECT count(*) FROM bundle_concept_relationship b
           WHERE (b.concept_id_1 IN (SELECT concept_id FROM bundle_concept
                       WHERE vocabulary_id = %s)
               OR b.concept_id_2 IN (SELECT concept_id FROM bundle_concept
                       WHERE vocabulary_id = %s))
             AND NOT EXISTS (SELECT 1 FROM cdm.concept_relationship t
                 WHERE t.concept_id_1 = b.concept_id_1 AND t.concept_id_2 = b.concept_id_2
                   AND t.relationship_id = b.relationship_id)""",
        [VOCABULARY, VOCABULARY],
    ).fetchone()[0]
    for table in BUNDLE_TABLES:
        con.execute(f"DROP TABLE bundle_{table}")
    return added


MAP_SQL = """
CREATE TEMP TABLE panel_concepts AS
WITH genomic AS (
    SELECT concept_id, concept_name, concept_class_id FROM cdm.concept
    WHERE vocabulary_id = %(v)s AND standard_concept = 'S' AND invalid_reason IS NULL
),
dna AS (
    SELECT p.variant_id, min(g.concept_id) AS concept_id FROM panel_variants p
    JOIN genomic g ON g.concept_class_id = 'Gene DNA Variant' AND g.concept_name = p.dna_name
    GROUP BY p.variant_id
),
transcript AS (
    SELECT p.variant_id, min(g.concept_id) AS concept_id FROM panel_variants p
    JOIN cdm.concept_synonym s ON s.concept_synonym_name IN (p.hgvs, p.hgvs_unversioned)
    JOIN genomic g ON g.concept_id = s.concept_id AND g.concept_class_id = 'Gene RNA Variant'
    GROUP BY p.variant_id
),
gene AS (
    SELECT p.variant_id, min(g.concept_id) AS concept_id FROM panel_variants p
    JOIN genomic g ON g.concept_class_id = 'Gene Variant'
        AND g.concept_name LIKE p.gene || ' (%%) gene variant measurement'
    GROUP BY p.variant_id
)
SELECT p.variant_id,
       coalesce(dna.concept_id, transcript.concept_id, gene.concept_id, 0) AS concept_id,
       CASE WHEN dna.concept_id IS NOT NULL THEN 'dna'
            WHEN transcript.concept_id IS NOT NULL THEN 'transcript'
            WHEN gene.concept_id IS NOT NULL THEN 'gene' ELSE 'none' END AS level,
       coalesce(p.hgvs, p.variant_id) AS source_value
FROM panel_variants p
LEFT JOIN dna USING (variant_id)
LEFT JOIN transcript USING (variant_id)
LEFT JOIN gene USING (variant_id)
"""

WRITE_SQL = """
INSERT INTO cdm.measurement (measurement_id, person_id, measurement_concept_id, measurement_date,
    measurement_type_concept_id, value_as_concept_id, measurement_source_value,
    measurement_source_concept_id, value_source_value)
SELECT %(offset)s + row_number() OVER (ORDER BY g.variant_id, g.sample_id),
       r.person_id, m.concept_id, o.end_date, %(lab)s, a.concept_id, m.source_value, 0,
       g.genotype
FROM panel_genotypes g
JOIN panel_concepts m USING (variant_id)
JOIN panel_people r USING (sample_id)
JOIN (SELECT person_id, max(observation_period_end_date) AS end_date
      FROM cdm.observation_period GROUP BY person_id) o USING (person_id)
JOIN cdm.concept a ON a.vocabulary_id = 'LOINC' AND a.concept_code = CASE g.genotype
    WHEN '0/1' THEN %(het)s WHEN '1/1' THEN %(hom)s END
"""


def dna_name(gene: str, variant_id: str) -> str | None:
    """The name OMOP Genomic gives a single-base substitution's DNA variant concept."""
    chromosome, position, ref, alt = variant_id.split(":")
    if len(ref) != 1 or len(alt) != 1:
        return None
    return (
        f"{gene} on GRCh38 {chromosome}: Substitution in position {position} of {ref}"
        f" replaced by {alt} measurement"
    )


def write_panel_measurements(
    con: psycopg.Connection,
    variants: list[dict],
    genotypes: list[tuple[str, str, str]],
    people: dict[str, int],
) -> dict[str, int]:
    """Replace the panel's measurement rows. variants: one dict per panel variant with id,
    gene, and MANE refseq and hgvsc (None where VEP gave none); genotypes: (variant id, sample
    id, genotype) for every carrier; people: sample id to OMOP person_id."""
    con.execute(
        "DROP TABLE IF EXISTS panel_variants, panel_genotypes, panel_people, panel_concepts"
    )
    con.execute(
        "DELETE FROM cdm.measurement WHERE measurement_id >= %s AND measurement_id < %s",
        [ID_OFFSET, ID_END],
    )
    con.execute(
        "CREATE TEMP TABLE panel_variants (variant_id text, gene text, dna_name text,"
        " hgvs text, hgvs_unversioned text)"
    )
    con.execute(
        "CREATE TEMP TABLE panel_genotypes (variant_id text, sample_id text, genotype text)"
    )
    con.execute("CREATE TEMP TABLE panel_people (sample_id text, person_id bigint)")
    with con.cursor() as cur:
        rows = []
        for v in variants:
            hgvs = f"{v['refseq']}:{v['hgvsc']}" if v.get("hgvsc") else None
            unversioned = f"{v['refseq'].split('.')[0]}:{v['hgvsc']}" if hgvs else None
            rows.append((v["id"], v["gene"], dna_name(v["gene"], v["id"]), hgvs, unversioned))
        cur.executemany("INSERT INTO panel_variants VALUES (%s, %s, %s, %s, %s)", rows)
        cur.executemany("INSERT INTO panel_genotypes VALUES (%s, %s, %s)", genotypes)
        cur.executemany("INSERT INTO panel_people VALUES (%s, %s)", people.items())
    con.execute(MAP_SQL, {"v": VOCABULARY})
    written = con.execute(
        WRITE_SQL,
        {
            "offset": ID_OFFSET,
            "lab": LAB,
            "het": GENOTYPE_LOINC["0/1"],
            "hom": GENOTYPE_LOINC["1/1"],
        },
    ).rowcount
    levels = dict(
        con.execute("SELECT level, count(*) FROM panel_concepts GROUP BY level").fetchall()
    )
    return {
        "measurements": written,
        "carrier_genotypes": len(genotypes),
        "variants_dna_concept": levels.get("dna", 0),
        "variants_transcript_concept": levels.get("transcript", 0),
        "variants_gene_concept": levels.get("gene", 0),
        "variants_no_concept": levels.get("none", 0),
    }


def read_panel_genotypes(path: Path) -> list[tuple[str, str, str]]:
    """(variant id, sample id, genotype) for every carrier in a panel VCF (genotype not 0/0)."""
    out = []
    with gzip.open(path, "rt") as f:
        for line in f:
            if line.startswith("##"):
                continue
            cols = line.rstrip("\n").split("\t")
            if line.startswith("#"):
                samples = cols[9:]
                continue
            out += [
                (cols[2], s, gt) for s, gt in zip(samples, cols[9:], strict=True) if gt != "0/0"
            ]
    return out


def check_against_truth(
    con: psycopg.Connection, truth: list[dict], person_of_subject: dict[str, int]
) -> dict[str, int]:
    """The written rows against panel_truth.json: for variants it lists carriers of
    (pathogenic and uncertain), every carrier a row and no one else; for the rest (common
    benign variants, listed by count only), as many rows as carriers. Runs in the session that
    wrote them (reads panel_concepts)."""
    written: dict[str, set[int]] = {}
    for variant_id, person_id in con.execute(
        "SELECT p.variant_id, m.person_id FROM cdm.measurement m"
        " JOIN panel_concepts p ON p.source_value = m.measurement_source_value"
        " AND p.concept_id = m.measurement_concept_id"
        " WHERE m.measurement_id >= %s AND m.measurement_id < %s",
        [ID_OFFSET, ID_END],
    ):
        written.setdefault(variant_id, set()).add(person_id)
    missing = extra = wrong_count = 0
    for v in truth:
        got = written.get(v["id"], set())
        if "carrier_subjects" in v:
            want = {person_of_subject[s] for s in v["carrier_subjects"]}
            missing, extra = missing + len(want - got), extra + len(got - want)
        elif len(got) != v["carriers"]:
            wrong_count += 1
    return {
        "carriers": sum(v["carriers"] for v in truth),
        "missing": missing,
        "extra": extra,
        "variants_wrong_count": wrong_count,
    }
