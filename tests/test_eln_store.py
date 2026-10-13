from datetime import date
from types import SimpleNamespace as NS

from ehr_rwe_eln.eln.batch import OUTPUT_FORMAT, batch_requests, read_result
from ehr_rwe_eln.eln.models import Extraction, Result, Sample
from ehr_rwe_eln.eln.store import extractions, load_entries, load_subjects, pending, save_extraction

GOOD = Extraction(
    samples=[Sample(sample_id="S-1", subject_id="HTN-0001", specimen_type="serum")],
    results=[Result(sample_id="S-1", analyte="crp", value=2.2, unit="mg/L")],
)


def succeeded(text: str, stop_reason: str = "end_turn") -> NS:
    message = NS(stop_reason=stop_reason, content=[NS(type="text", text=text)])
    return NS(custom_id="E1", result=NS(type="succeeded", message=message))


def test_batch_requests_carry_the_entry_id_and_the_schema():
    request = batch_requests({"ELN-00001": "body"}, "claude-haiku-5-5")[0]
    assert request["custom_id"] == "ELN-00001"
    assert request["params"]["output_config"]["format"] == OUTPUT_FORMAT
    assert request["params"]["messages"] == [{"role": "user", "content": "body"}]


def test_read_result_validates_or_explains():
    assert read_result(succeeded(GOOD.model_dump_json())) == (GOOD, None)
    assert read_result(succeeded('{"samples": []}'))[1].startswith("invalid extraction")
    assert read_result(succeeded("", "max_tokens")) == (None, "stop_reason max_tokens")
    errored = NS(custom_id="E1", result=NS(type="errored", error=NS(type="overloaded_error")))
    assert read_result(errored) == (None, "errored overloaded_error")
    assert read_result(NS(custom_id="E1", result=NS(type="expired"))) == (None, "expired")


def test_store_round_trip_and_failed_extractions_are_pending_again(pg, dq_schema):
    load_subjects(pg, {"HTN-0001": 7})
    rows = [(f"E{i}", "t", "a", date(2020, 1, 1), f"body {i}") for i in (1, 2, 3)]
    load_entries(pg, rows)
    load_entries(pg, rows)  # loading again changes nothing
    assert list(pending(pg)) == ["E1", "E2", "E3"]

    save_extraction(pg, "E1", "m", "b1", GOOD, None)
    save_extraction(pg, "E2", "m", "b1", None, "expired")
    assert pending(pg) == {"E2": "body 2", "E3": "body 3"}
    assert extractions(pg) == {"E1": GOOD}

    save_extraction(pg, "E2", "m", "b2", GOOD, None)
    assert list(pending(pg)) == ["E3"]
    assert pg.execute("SELECT person_id FROM eln.subject").fetchall() == [(7,)]
