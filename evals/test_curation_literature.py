"""Eval for the curation module's literature step. Calls the real Anthropic API: about $0.15.

    uv run pytest evals/test_curation_literature.py -s

The labeled set is the ClinGen Evidence Repository: expert panel curations with every criterion
the panel applied. The cases are the first variants (in a fixed order) the panel scored with
PS3, BS3, PS4, or PP1 that have passages naming them, from the latest
`scripts/curate_variants.py --set erepo` run and the cached LitVar2 and PubTator3 answers in
data/reference/. Without those it skips.

Two bars: almost every claim must quote a passage that was sent (a quote that is not there is
an invented citation), and most criteria proposed must be ones the panel applied.
"""

from pathlib import Path

import pytest

from ehr_rwe_eln.config import DatabaseSettings
from ehr_rwe_eln.curation.literature import literature_cases, propose, score_claims, verify

pytestmark = pytest.mark.evals

REFERENCE = Path(__file__).resolve().parent.parent / "data" / "reference"
CASES = 6
MIN_VERIFIED = 0.9  # share of claims whose PMID and quote check out
MIN_PRECISION = 0.5  # share of proposed criteria the panel also applied


def test_literature_claims_are_quoted_and_mostly_right():
    try:
        with DatabaseSettings().connect() as con:
            cases, skipped = literature_cases(con, CASES, REFERENCE)
    except Exception as e:  # no database, no erepo run
        pytest.skip(f"no Evidence Repository run to draw cases from: {e}")
    if len(cases) < CASES:
        pytest.skip(f"only {len(cases)} cases with passages (skipped {dict(skipped)})")

    rows, verified_n, rejected_n = [], 0, 0
    for case in cases:
        proposals, _ = propose(case["prompt"])
        verified, rejected = verify(proposals, case["passages"])
        verified_n, rejected_n = verified_n + len(verified), rejected_n + len(rejected)
        rows.append((case["expert"], verified))
        for r in rejected:
            print(f"  rejected {case['gene']} {r['criterion']} PMID {r['pmid']}: {r['why']}")

    scored = score_claims(rows)
    agreed = sum(s.get("agreed", 0) for s in scored.values())
    extra = sum(
        s.get("extra_marked_not_met", 0) + s.get("extra_not_listed", 0) for s in scored.values()
    )
    missed = sum(s.get("missed", 0) for s in scored.values())
    for criterion, s in scored.items():
        print(f"{criterion}: {s}")
    print(
        f"claims: {verified_n} verified, {rejected_n} rejected;"
        f" agreed {agreed}, extra {extra}, missed {missed}"
    )

    total = verified_n + rejected_n
    assert total == 0 or verified_n / total >= MIN_VERIFIED
    assert agreed + extra == 0 or agreed / (agreed + extra) >= MIN_PRECISION
