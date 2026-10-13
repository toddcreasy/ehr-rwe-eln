from datetime import UTC, datetime

from ehr_rwe_eln.synth.bayes_net import plan, synthesize
from ehr_rwe_eln.synth.card import render_card
from ehr_rwe_eln.synth.fidelity import fidelity_report
from ehr_rwe_eln.synth.privacy import privacy_report
from tests.test_synth import AGE, DRUG, FLAG, spec, toy

SPEC = spec(AGE, FLAG, DRUG)


def release_record(s, release, measurements, rows, holdout_rows, seed=0) -> dict:
    return {
        "release_id": 7,
        "created_at": datetime(2026, 10, 13, tzinfo=UTC),
        "spec_name": s.name,
        "method": release.method,
        "epsilon": release.epsilon,
        "seed": seed,
        "spec": s.model_dump(mode="json"),
        "measurements": plan(measurements),
        "source_database": "test_db",
        "source_rows": 3000,
        "holdout_rows": holdout_rows,
        "rows": rows,
        "code_version": "abc1234",
    }


def full_card() -> str:
    train, holdout = toy(3000, 1), toy(1000, 2)
    out, measurements = synthesize(train, SPEC, SPEC.releases[0])
    fidelity = fidelity_report(train, out, SPEC.columns)
    fidelity["noise_floor"] = fidelity_report(train, holdout, SPEC.columns)["summary"]
    privacy = privacy_report(train, holdout, out, SPEC)
    copied = privacy_report(train, holdout, train, SPEC)
    privacy["copy_of_training_data"] = {
        "distance_to_closest_record": copied["distance_to_closest_record"],
        "membership_inference": copied["membership_inference"],
        "attribute_gap_mean": copied["attribute_inference"]["gap_mean"],
        "attribute_gap_max": copied["attribute_inference"]["gap_max"],
    }
    record = release_record(SPEC, SPEC.releases[0], measurements, len(out), 1000)
    return render_card(record, {"fidelity": fidelity, "privacy": privacy})


def test_card_has_every_section_and_the_provenance():
    card = full_card()
    for heading in (
        "# Data card: synthetic release 7",
        "## Intended use",
        "## How it was made",
        "## Privacy spend",
        "## Fidelity",
        "## Privacy risk",
        "## Limitations",
    ):
        assert heading in card
    assert "`test_db` at code version `abc1234`" in card
    assert "| lisinopril | drug, concepts 2 | 0, 1 | hypertension |" in card
    assert "| Histogram of age x hypertension (20 cells) | epsilon 0.3333 |" in card
    assert "anyone with the seed can regenerate the noise" in card
    assert "Only the relationships named as parents are kept" in card
    assert "-0.0%" not in card


def test_card_without_a_holdout_says_what_it_cannot_show():
    s = spec(AGE, FLAG, DRUG)
    train = toy(2000)
    out, measurements = synthesize(train, s, s.releases[0])
    fidelity = fidelity_report(train, out, s.columns)
    fidelity["noise_floor"] = None
    record = release_record(s, s.releases[0], measurements, len(out), 0, seed=None)
    card = render_card(record, {"fidelity": fidelity})
    assert "no noise floor" in card and "Not assessed" in card
    assert "none (secure noise)" in card and "regenerate the noise" not in card


def test_trial_warning_appears_with_spurious_draws():
    s = spec(AGE, FLAG, DRUG)
    train = toy(2000)
    out, measurements = synthesize(train, s, s.releases[0])
    estimate = {
        "persons": 2000, "treated": 1000, "events_treated": 10, "events_comparator": 9,
        "crude_hazard_ratio": 1.1, "hazard_ratio": 1.0, "robust_ci": (0.5, 2.0),
        "not_estimable": None,
    }  # fmt: skip
    trial = {
        "real": estimate,
        "release": {**estimate, "hazard_ratio": 3.0, "robust_ci": (1.2, 7.5)},
        "release_covers_real": False,
        "repeated": {
            "draws": 20,
            "estimable": 0.9,
            "covers_real": 0.5,
            "spurious_effect": 0.4,
            "hazard_ratio_median": 1.4,
            "hazard_ratio_10th_90th": [0.6, 3.1],
            "events_median": 21,
        },  # fmt: skip
    }
    record = release_record(s, s.releases[0], measurements, len(out), 0)
    card = render_card(record, {"trial": trial})
    assert "40% of draws at this setting showed an effect the real data does not" in card
    assert "| This release | 19 | 3.00 (1.20 to 7.50) |" in card
