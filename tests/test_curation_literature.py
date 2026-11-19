import json
from types import SimpleNamespace

import pytest

import ehr_rwe_eln.curation.literature as literature
from ehr_rwe_eln.curation.literature import (
    Claim,
    ProposalFailed,
    Proposals,
    find_variant,
    names,
    one_letter,
    passages,
    prompt,
    propose,
    score_claims,
    verify,
)


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    monkeypatch.setattr(literature.time, "sleep", lambda s: None)


def test_variant_names_include_older_numbering():
    assert one_letter("p.Arg1699Gln") == "p.R1699Q" and one_letter("p.Gly324AlafsTer46") is None
    ldlr = names("LDLR", "c.680A>T", "p.Asp227Glu", None)
    assert "D206E" in ldlr and "Asp206Glu" in ldlr  # numbered without the signal peptide
    brca1 = names("BRCA1", "c.5096G>A", "p.Arg1699Gln", "rs41293459")
    assert {"R1699Q", "p.R1699Q", "rs41293459", "5215G>A"} <= set(brca1)  # BIC is c. + 119
    assert "6174G>A" in names("BRCA2", "c.5946G>A", None, None)  # BIC is c. + 228
    assert "W45X" in names("LDLR", "c.198G>A", "p.Trp66Ter", None)
    assert not any(n[0].isdigit() for n in names("MLH1", "c.5096G>A", None, None))  # no BIC


def fake_get(responses: dict, calls: list):
    def get(url):
        calls.append(url)
        for key, body in responses.items():
            if key in url:
                return json.dumps(body).encode()
        raise AssertionError(f"unexpected URL {url}")

    return get


def test_litvar_match_needs_the_gene_and_the_exact_change(tmp_path):
    calls = []
    get = fake_get(
        {
            "query=BRCA1%20p.R1699Q": [
                {"_id": "litvar@other##", "gene": ["BRCA2"], "hgvs": "p.R1699Q"},  # wrong gene
                {
                    "_id": "litvar@rs41293459##",
                    "gene": ["BRCA1"],
                    "hgvs": "p.R1699Q",
                    "rsid": "rs41293459",
                },
            ],
            "rs41293459": {"pmids": [111, 222]},
        },
        calls,
    )
    found = find_variant("BRCA1", "c.5096G>A", "p.Arg1699Gln", tmp_path / "v.json", get)
    assert found == {"id": "litvar@rs41293459##", "rsid": "rs41293459", "pmids": ["111", "222"]}
    assert find_variant("BRCA1", "c.5096G>A", "p.Arg1699Gln", tmp_path / "v.json", get) == found
    assert len(calls) == 2  # the second lookup is answered from the cache


def test_litvar_refuses_a_different_variant_under_the_same_c_name(tmp_path):
    # LitVar2 suggests p.D510E for APC c.1626G>C: another transcript's numbering, not this variant.
    get = fake_get(
        {
            "query=APC%20p.Q542H": [],
            "query=APC%20c.1626G%3EC": [
                {"_id": "x", "gene": ["APC"], "hgvs": "p.D510E", "name": "p.D510E"}
            ],
        },
        [],
    )
    assert find_variant("APC", "c.1626G>C", "p.Gln542His", tmp_path / "v.json", get) is None
    assert json.loads((tmp_path / "v.json").read_text()) == {"APC|c.1626G>C|p.Gln542His": None}


def test_passages_keep_what_names_the_variant(tmp_path, monkeypatch):
    monkeypatch.setattr(literature, "PASSAGE_CHARS", 60)
    doc = lambda pmid, date, passages_: {"id": pmid, "date": date, "passages": passages_}  # noqa: E731
    body = {
        "PubTator3": [
            doc(
                "1",
                "2019-05-01",
                [
                    {
                        "infons": {"section_type": "ABSTRACT"},
                        "text": "We assayed R1699Q and found loss of function.",
                    },
                    {
                        "infons": {"section_type": "METHODS"},
                        "text": "Cells were grown in standard medium.",
                    },
                    {
                        "infons": {"section_type": "REF"},
                        "text": "Smith J. R1699Q in families. 2001.",
                    },
                ],
            ),
            doc(
                "2",
                "2023-01-01",
                [
                    {
                        "infons": {"section_type": "RESULTS"},
                        "text": "word " * 30 + "the c.5096G>A carrier had cancer " + "word " * 30,
                    }
                ],
            ),
        ]
    }
    calls = []
    get = fake_get({"pubtator3": body}, calls)
    variant = names("BRCA1", "c.5096G>A", "p.Arg1699Gln", None)
    found = passages(["1", "2"], variant, "BRCA1|v", tmp_path / "p.json", get)
    assert [(p["pmid"], p["section"]) for p in found] == [("2", "RESULTS"), ("1", "ABSTRACT")]
    assert found[0]["text"].startswith("... ") and "c.5096G>A" in found[0]["text"]
    assert len(found[0]["text"]) <= 60 + 8
    passages(["1", "2"], variant, "BRCA1|v", tmp_path / "p.json", get)
    assert len(calls) == 1  # cached
    passages(["1", "2"], [*variant, "5215G>A"], "BRCA1|v", tmp_path / "p.json", get)
    assert len(calls) == 2  # new names, new search


def test_prompt_tags_each_passage_with_its_paper():
    text = prompt(
        "BRCA1",
        "c.5096G>A",
        "p.Arg1699Gln",
        [{"pmid": "1", "year": "2019", "section": "ABSTRACT", "text": "R1699Q"}],
    )
    assert text.startswith("Variant: BRCA1 c.5096G>A, p.Arg1699Gln, p.R1699Q")
    assert '<passage pmid="1" year="2019" section="ABSTRACT">\nR1699Q\n</passage>' in text


SENT = [
    {
        "pmid": "1",
        "year": "2019",
        "section": "ABSTRACT",
        "text": "We assayed R1699Q.  It abolished  BRCT binding in a calibrated assay.",
    },
]


def claim(pmid="1", quote="It abolished BRCT binding in a calibrated assay.", criterion="PS3"):
    return Claim(criterion=criterion, strength="strong", pmid=pmid, quote=quote, rationale="r")


def test_only_claims_quoting_a_passage_sent_are_verified():
    proposals = Proposals(
        claims=[
            claim(),  # exact, though the passage has double spaces
            claim(quote="it ABOLISHED brct binding in a calibrated assay"),  # case, no period
            claim(quote="It disrupted BRCT binding."),  # paraphrase
            claim(pmid="9"),  # a paper that was not sent
        ]
    )
    verified, rejected = verify(proposals, SENT)
    assert len(verified) == 2
    assert [r["why"] for r in rejected] == [
        "quote is not in the passages sent from that paper",
        "PMID was not among the passages sent",
    ]


def fake_client(stop_reason="end_turn", parsed=None):
    usage = SimpleNamespace(
        input_tokens=100,
        output_tokens=20,
        cache_read_input_tokens=None,
        cache_creation_input_tokens=50,
    )
    response = SimpleNamespace(stop_reason=stop_reason, parsed_output=parsed, usage=usage)
    seen = {}

    def parse(**kwargs):
        seen.update(kwargs)
        return response

    return SimpleNamespace(messages=SimpleNamespace(parse=parse)), seen


def test_propose_constrains_the_reply_and_reports_usage():
    client, seen = fake_client(parsed=Proposals(claims=[claim()]))
    proposals, used = propose("Variant: X", client, "claude-opus-5-5")
    assert seen["output_format"] is Proposals and seen["model"] == "claude-opus-5-5"
    assert seen["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert used == {"input": 100, "output": 20, "cache_read": 0, "cache_write": 50}
    assert proposals.claims[0].criterion == "PS3"
    client, _ = fake_client(stop_reason="max_tokens")
    with pytest.raises(ProposalFailed, match="max_tokens"):
        propose("Variant: X", client, "claude-opus-5-5")


def test_claims_are_scored_against_the_panel_codes():
    verified = lambda *cs: [{"criterion": c, "strength": s} for c, s in cs]  # noqa: E731
    scored = score_claims(
        [
            ({"met": ["PS3", "PP1"], "not_met": []}, verified(("PS3", "strong"))),
            ({"met": ["PS4_Supporting"], "not_met": []}, verified(("PS4", "moderate"))),
            ({"met": [], "not_met": ["BS3"]}, verified(("BS3", "strong"))),
        ]
    )
    assert scored["PS3"] == {"agreed": 1, "same_strength": 1}
    assert scored["PS4"] == {"agreed": 1, "same_strength": 0}
    assert scored["PP1"] == {"missed": 1}
    assert scored["BS3"] == {"extra_marked_not_met": 1}
