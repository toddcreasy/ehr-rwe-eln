import gzip
from datetime import date

import pytest

from ehr_rwe_eln.cohort.cdm import create_cdm
from ehr_rwe_eln.genomics.omop import (
    ID_OFFSET,
    check_against_truth,
    dna_name,
    load_genomic_vocabulary,
    read_panel_genotypes,
    write_panel_measurements,
)

HEADER = {
    "concept": "concept_id\tconcept_name\tdomain_id\tvocabulary_id\tconcept_class_id"
    "\tstandard_concept\tconcept_code\tvalid_start_date\tvalid_end_date\tinvalid_reason",
    "concept_class": "concept_class_id\tconcept_class_name\tconcept_class_concept_id",
    "vocabulary": "vocabulary_id\tvocabulary_name\tvocabulary_reference\tvocabulary_version"
    "\tvocabulary_concept_id",
    "concept_synonym": "concept_id\tconcept_synonym_name\tlanguage_concept_id",
    "concept_relationship": "concept_id_1\tconcept_id_2\trelationship_id\tvalid_start_date"
    "\tvalid_end_date\tinvalid_reason",
    "concept_ancestor": "ancestor_concept_id\tdescendant_concept_id\tmin_levels_of_separation"
    "\tmax_levels_of_separation",
}
GENOMIC = [
    (100, "BRCA1 (BRCA1 DNA repair associated) gene variant measurement", "Gene Variant", "672"),
    (
        101,
        "BRCA1 on GRCh38 chr17: Substitution in position 43091012 of C replaced by T measurement",
        "Gene DNA Variant",
        "OMOP1",
    ),
    (
        102,
        "BRCA1 transcript: Duplication of position 2778 measurement",
        "Gene RNA Variant",
        "OMOP2",
    ),
]
VARIANTS = [
    {"id": "chr17:43091012:C:T", "gene": "BRCA1", "refseq": "NM_007294.4", "hgvsc": "c.4117G>A"},
    {"id": "chr17:43092752:C:CA", "gene": "BRCA1", "refseq": "NM_007294.4", "hgvsc": "c.2778dup"},
    {"id": "chr17:43104262:CT:C", "gene": "BRCA1", "refseq": "NM_007294.4", "hgvsc": "c.302-2del"},
    {"id": "chr17:43044391:G:A", "gene": "BRCA1"},  # VEP gave no MANE HGVS
]


def bundle(tmp_path):
    """A tiny Athena download: three OMOP Genomic concepts plus one LOINC concept the load must
    skip, and a link to a concept staging does not have."""
    rows = {
        "concept": [
            f"{i}\t{n}\tMeasurement\tOMOP Genomic\t{k}\tS\t{c}\t20240216\t20991231\t"
            for i, n, k, c in GENOMIC
        ]
        + ["900\tnewer LOINC\tMeasurement\tLOINC\tLab Test\tS\t1-1\t20240216\t20991231\t"],
        "concept_class": ["Gene Variant\tGene Variant\t0", "Lab Test\tLab Test\t0"],
        "vocabulary": ["OMOP Genomic\tOMOP Genomic\tOMOP generated\tOMOP Genomic 20240216\t0"],
        "concept_synonym": ["102\tNM_007294.4:c.2778dup\t0", "900\tskip me\t0"],
        "concept_relationship": [
            "101\t100\tIs a\t20240216\t20991231\t",
            "101\t555\tIs a\t20240216\t20991231\t",  # 555 is not loaded
        ],
        "concept_ancestor": ["100\t101\t1\t1"],
    }
    for table, lines in rows.items():
        (tmp_path / f"{table.upper()}.csv").write_text("\n".join([HEADER[table], *lines]) + "\n")
    return tmp_path


@pytest.fixture
def con(pg, tmp_path):
    create_cdm(pg)
    pg.execute(
        "INSERT INTO cdm.concept VALUES (0, 'No matching concept', 'Metadata', 'None', 'Undefined',"
        " NULL, 'No matching concept', '1970-01-01', '2099-12-31', NULL),"
        " (45880311, 'Heterozygous', 'Meas Value', 'LOINC', 'Answer', 'S', 'LA6706-1',"
        " '2000-01-01', '2099-12-31', NULL),"
        " (45878253, 'Homozygous', 'Meas Value', 'LOINC', 'Answer', 'S', 'LA6705-3',"
        " '2000-01-01', '2099-12-31', NULL)"
    )
    pg.execute("INSERT INTO cdm.relationship VALUES ('Is a', 'Is a', '0', '0', 'Subsumes', 0)")
    pg.execute(
        "INSERT INTO cdm.observation_period VALUES (1, 7, '2010-01-01', '2020-06-30', 32817),"
        " (2, 7, '2021-01-01', '2023-03-31', 32817), (3, 8, '2015-01-01', '2019-12-31', 32817)"
    )
    # A Synthea row and an ELN row the panel load must never touch.
    for measurement_id in (5, 2_000_000_001):
        pg.execute(
            "INSERT INTO cdm.measurement (measurement_id, person_id, measurement_concept_id,"
            " measurement_date, measurement_type_concept_id) VALUES (%s, 7, 0, '2020-01-01', 0)",
            [measurement_id],
        )
    load_genomic_vocabulary(pg, bundle(tmp_path))
    return pg


def test_only_omop_genomic_is_loaded_and_unlinkable_rows_are_skipped(pg, tmp_path):
    create_cdm(pg)
    pg.execute(  # the synonyms' language concept
        "INSERT INTO cdm.concept VALUES (0, 'x', 'Metadata', 'None', 'Undefined', NULL, 'x',"
        " '1970-01-01', '2099-12-31', NULL)"
    )
    pg.execute("INSERT INTO cdm.relationship VALUES ('Is a', 'Is a', '0', '0', 'Subsumes', 0)")
    added = load_genomic_vocabulary(pg, bundle(tmp_path))
    assert added == {
        "concept_class": 1,  # Gene Variant only; Lab Test belongs to LOINC's concept
        "vocabulary": 1,
        "concept": 3,
        "concept_synonym": 1,
        "concept_relationship": 1,
        "concept_ancestor": 1,
        "relationships_skipped": 1,
    }
    assert pg.execute("SELECT count(*) FROM cdm.concept WHERE concept_id = 900").fetchone() == (0,)
    # A second run adds nothing.
    assert set(load_genomic_vocabulary(pg, bundle(tmp_path)).values()) == {0, 1}


def test_dna_names_only_for_substitutions():
    assert dna_name("BRCA1", "chr17:43091012:C:T") == GENOMIC[1][1]
    assert dna_name("BRCA1", "chr17:43092752:C:CA") is None


def test_each_carrier_gets_the_most_specific_concept_and_its_genotype(con, tmp_path):
    vcf = tmp_path / "panel.vcf.gz"
    with gzip.open(vcf, "wt") as f:
        f.write(
            "##fileformat=VCFv4.2\n#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tS1\tS2\n"
        )
        for v in VARIANTS:
            chromosome, position, ref, alt = v["id"].split(":")
            genotypes = {"chr17:43044391:G:A": "1/1\t0/1"}.get(v["id"], "0/1\t0/0")
            f.write(
                f"{chromosome}\t{position}\t{v['id']}\t{ref}\t{alt}\t.\tPASS\t.\tGT\t{genotypes}\n"
            )
    genotypes = read_panel_genotypes(vcf)
    assert len(genotypes) == 5
    counts = write_panel_measurements(con, VARIANTS, genotypes, {"S1": 7, "S2": 8})
    assert counts == {
        "measurements": 5,
        "carrier_genotypes": 5,
        "variants_dna_concept": 1,
        "variants_transcript_concept": 1,
        "variants_gene_concept": 2,
        "variants_no_concept": 0,
    }
    rows = con.execute(
        "SELECT person_id, measurement_concept_id, measurement_date, value_as_concept_id,"
        " measurement_source_value, measurement_source_concept_id FROM cdm.measurement"
        " WHERE measurement_id >= %s AND measurement_id < 2000000000 ORDER BY measurement_id",
        [ID_OFFSET],
    ).fetchall()
    end_7, end_8 = date(2023, 3, 31), date(2019, 12, 31)  # each person's last period end
    assert rows == [
        (7, 100, end_7, 45878253, "chr17:43044391:G:A", 0),  # gene concept, homozygous
        (8, 100, end_8, 45880311, "chr17:43044391:G:A", 0),
        (7, 101, end_7, 45880311, "NM_007294.4:c.4117G>A", 0),  # DNA concept by position
        (7, 102, end_7, 45880311, "NM_007294.4:c.2778dup", 0),  # transcript concept by HGVS
        (7, 100, end_7, 45880311, "NM_007294.4:c.302-2del", 0),
    ]
    # Rerunning replaces the panel rows and leaves the Synthea and ELN rows.
    write_panel_measurements(con, VARIANTS, genotypes, {"S1": 7, "S2": 8})
    assert con.execute("SELECT count(*) FROM cdm.measurement").fetchone() == (7,)
    truth = [
        {"id": "chr17:43091012:C:T", "carriers": 1, "carrier_subjects": ["SUBJ-1"]},
        {"id": "chr17:43044391:G:A", "carriers": 2},
        {"id": "chr17:43092752:C:CA", "carriers": 1, "carrier_subjects": ["SUBJ-2"]},
    ]
    check = check_against_truth(con, truth, {"SUBJ-1": 7, "SUBJ-2": 8})
    assert check == {"carriers": 4, "missing": 1, "extra": 1, "variants_wrong_count": 0}
