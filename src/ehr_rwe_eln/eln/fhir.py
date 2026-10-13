"""Export the stored ELN extractions as one FHIR R4 Bundle: a Specimen per sample, and an
Observation per result that references its Specimen.

The rows are the ones the OMOP write uses (omop.stage), coded with the same SNOMED, LOINC, and
UCUM codes, so the two outputs agree. One difference: OMOP needs a date, so a sample without a
stated collection date gets its entry's date there; FHIR does not, so here the date is left out.

Models come from fhir.resources' R4B package (the release defaults to R5). R4B changed no
Specimen or Observation element from R4. The bundle holds no Patient resources; subjects are
referenced by their OMOP person_id. Resource ids are name-based UUIDs, so reruns give the same
bundle.
"""

import uuid

import psycopg
from fhir.resources.R4B.bundle import Bundle, BundleEntry
from fhir.resources.R4B.observation import Observation
from fhir.resources.R4B.specimen import Specimen

from ehr_rwe_eln.eln.omop import ANALYTE_LOINC, SPECIMEN_SNOMED, stage

SNOMED = "http://snomed.info/sct"
LOINC = "http://loinc.org"
UCUM = "http://unitsofmeasure.org"
CATEGORY = "http://terminology.hl7.org/CodeSystem/observation-category"
# Identifier systems this repo owns.
SAMPLE_ID = "urn:ehr-rwe-eln:sample-id"
PERSON_ID = "urn:ehr-rwe-eln:omop-person-id"
NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "urn:ehr-rwe-eln:eln")


def _urn(*parts: str) -> str:
    return f"urn:uuid:{uuid.uuid5(NAMESPACE, '/'.join(parts))}"


def _concept(system: str, code: str | None, text: str) -> dict:
    # An unmapped value keeps its text and no coding, as FHIR allows.
    return {"coding": [{"system": system, "code": code}], "text": text} if code else {"text": text}


def build_bundle(con: psycopg.Connection) -> Bundle:
    stage(con)
    samples = con.execute(
        "SELECT sample_id, person_id, specimen_type, specimen_date, date_from_entry"
        " FROM eln_samples ORDER BY specimen_id"
    ).fetchall()
    # Joined to the samples, so a result whose sample is missing is skipped, as in OMOP.
    results = con.execute(
        "SELECT r.sample_id, r.analyte, r.value, r.unit FROM eln_results r"
        " JOIN eln_samples s USING (sample_id) ORDER BY s.specimen_id, r.analyte"
    ).fetchall()

    entries, subjects, collected = [], {}, {}
    for sample_id, person_id, specimen_type, day, date_from_entry in samples:
        subjects[sample_id] = {"identifier": {"system": PERSON_ID, "value": str(person_id)}}
        collected[sample_id] = None if date_from_entry else day.isoformat()
        collection = {"collectedDateTime": collected[sample_id]} if collected[sample_id] else None
        specimen = Specimen(
            identifier=[{"system": SAMPLE_ID, "value": sample_id}],
            type=_concept(SNOMED, SPECIMEN_SNOMED.get(specimen_type), specimen_type),
            subject=subjects[sample_id],
            collection=collection,
        )
        entries.append(BundleEntry(fullUrl=_urn("specimen", sample_id), resource=specimen))
    for sample_id, analyte, value, unit in results:
        observation = Observation(
            status="final",
            category=[{"coding": [{"system": CATEGORY, "code": "laboratory"}]}],
            code=_concept(LOINC, ANALYTE_LOINC.get((analyte, unit)), analyte),
            subject=subjects[sample_id],
            effectiveDateTime=collected[sample_id],
            valueQuantity={"value": value, "unit": unit, "system": UCUM, "code": unit},
            specimen={"reference": _urn("specimen", sample_id)},
        )
        entries.append(
            BundleEntry(fullUrl=_urn("observation", sample_id, analyte), resource=observation)
        )
    return Bundle(type="collection", entry=entries or None)
