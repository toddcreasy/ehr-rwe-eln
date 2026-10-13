import json

from fhir.resources.R4B.bundle import Bundle

from ehr_rwe_eln.eln.fhir import build_bundle

# The fixture from the OMOP tests: S-A dated, S-B undated, S-C an unknown subject, S-Z no sample.
from tests.test_eln_omop import con  # noqa: F401


def by_type(bundle: Bundle, resource_type: str) -> list:
    return [e for e in bundle.entry if e.resource.get_resource_type() == resource_type]


def test_specimens_and_observations(con):  # noqa: F811
    bundle = build_bundle(con)
    specimens, observations = by_type(bundle, "Specimen"), by_type(bundle, "Observation")
    assert [s.resource.identifier[0].value for s in specimens] == ["S-A", "S-B"]
    a, b = (s.resource for s in specimens)
    assert a.type.coding[0].code == "119364003"
    assert a.subject.identifier.value == "1"
    assert str(a.collection.collectedDateTime) == "2021-01-05"
    # No stated collection date: none in FHIR, where OMOP used the entry's date.
    assert b.collection is None

    values = [(o.resource.code.text, float(o.resource.valueQuantity.value)) for o in observations]
    assert values == [
        ("creatinine", 1.1),
        ("crp", 2.2),
        ("crp", 5.0),
        ("il6", 3.0),
    ]
    creatinine, _, crp_b, il6 = (o.resource for o in observations)
    assert creatinine.code.coding[0].code == "2160-0"
    assert creatinine.valueQuantity.code == "mg/dL"
    assert str(creatinine.effectiveDateTime) == "2021-01-05"
    assert crp_b.effectiveDateTime is None
    # FHIR codes come from ANALYTE_LOINC, not the vocabulary tables: IL-6 is coded here.
    assert il6.code.coding[0].code == "26881-3"
    specimen_urls = {s.fullUrl for s in specimens}
    assert all(o.resource.specimen.reference in specimen_urls for o in observations)
    assert crp_b.specimen.reference == specimens[1].fullUrl


def test_bundle_round_trips_and_is_stable(con):  # noqa: F811
    first = build_bundle(con).model_dump_json(exclude_none=True)
    assert build_bundle(con).model_dump_json(exclude_none=True) == first
    parsed = Bundle.model_validate(json.loads(first))
    assert parsed.type == "collection"
    assert len(parsed.entry) == 6
