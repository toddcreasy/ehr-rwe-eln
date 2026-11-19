import pytest

from ehr_rwe_eln.curation.curate import curate, save_run, score, sources
from ehr_rwe_eln.curation.rules import Band, assess, classify, label, load_rules, ptc_codon
from ehr_rwe_eln.curation.vep import annotate, exons
from ehr_rwe_eln.genomics.gnomad import details

RULES = load_rules()


def freq(faf=None, af=0.001, ac=10, grpmax_af=0.001):
    return {"ac": ac, "an": 1_000_000, "af": af, "faf95": faf, "grpmax_af": grpmax_af}


def vep(consequence="missense_variant", hgvsp=None, exon="3/10", intron=None, hgvsc="c.1A>G"):
    return {
        "gene": "X",
        "transcript": "ENST1",
        "consequences": [consequence],
        "hgvsc": hgvsc,
        "hgvsp": hgvsp,
        "exon": exon,
        "intron": intron,
    }


def labels(result):
    return sorted(c["label"] for c in result["met"])


def test_bands_respect_their_bounds_and_count_absence_as_rare():
    above = Band(strength="stand_alone", measure="faf95", above=0.001)
    at_least = Band(strength="stand_alone", measure="faf95", at_least=0.001)
    assert not above.met(freq(faf=0.001)) and at_least.met(freq(faf=0.001))
    assert not above.met(None)  # absent from gnomAD is never common
    rare = Band(strength="supporting", measure="af", below=0.00002)
    assert rare.met(None) and rare.met(freq(af=0.0)) and not rare.met(freq(af=0.00002))
    absent = Band(strength="supporting", measure="absent")
    assert absent.met(None) and absent.met(freq(ac=0)) and not absent.met(freq(ac=1))


def test_apc_pm2_depends_on_the_allele_count():
    apc = RULES.genes["APC"]
    assert labels(assess("APC", apc, freq(af=0.000004, ac=1), None, [])) == ["PM2_Supporting"]
    assert labels(assess("APC", apc, freq(af=0.000004, ac=6), None, [])) == []
    assert labels(assess("APC", apc, freq(af=0.000003, ac=5), None, [])) == ["PM2_Supporting"]


def test_brca_frequency_criteria_follow_enigma():
    brca1 = RULES.genes["BRCA1"]
    assert assess("BRCA1", brca1, freq(faf=0.0011), None, [])["classification"] == "Benign"
    at_ba1 = assess("BRCA1", brca1, freq(faf=0.001), None, [])  # BA1 needs more than 0.1%
    assert labels(at_ba1) == ["BS1"] and at_ba1["points"] == -4
    assert labels(assess("BRCA1", brca1, freq(faf=0.00005), None, [])) == ["BS1_Supporting"]
    assert labels(assess("BRCA1", brca1, None, None, [])) == ["PM2_Supporting"]
    assert labels(assess("BRCA1", brca1, freq(faf=None, af=0.000001, ac=1), None, [])) == []


def test_ldlr_pm2_is_moderate_on_the_grpmax_frequency():
    ldlr = RULES.genes["LDLR"]
    assert labels(assess("LDLR", ldlr, freq(grpmax_af=0.0002), None, [])) == ["PM2"]
    assert labels(assess("LDLR", ldlr, freq(grpmax_af=0.00021), None, [])) == []


def test_ba1_stands_alone_without_bs1():
    result = assess("LDLR", RULES.genes["LDLR"], freq(faf=0.3, af=0.3, grpmax_af=0.4), None, [])
    assert labels(result) == ["BA1"] and result["points"] is None


def test_ptc_codon_reads_nonsense_and_frameshift_names():
    assert ptc_codon("p.Arg1443Ter") == 1443
    assert ptc_codon("p.Gly324AlafsTer46") == 369
    assert ptc_codon("p.Leu12fs") is None and ptc_codon("p.Thr82Ile") is None


def test_mlh1_pvs1_follows_the_codon_cut_offs():
    mlh1 = RULES.genes["MLH1"]
    stop = lambda codon: vep("stop_gained", f"p.Arg{codon}Ter", exon="19/19")  # noqa: E731
    assert labels(assess("MLH1", mlh1, freq(), stop(753), [])) == ["PVS1"]  # even in the last exon
    assert labels(assess("MLH1", mlh1, freq(), stop(755), [])) == ["PVS1_Moderate"]
    past = assess("MLH1", mlh1, freq(), stop(757), [])
    assert (
        labels(past) == [] and "past the panel's PVS1 cut-offs" in past["not_assessed"][0]["reason"]
    )
    shifted = vep("frameshift_variant", "p.Gly700AlafsTer60")  # stops at codon 759
    assert labels(assess("MLH1", mlh1, freq(), shifted, [])) == []


def test_generic_pvs1_leaves_last_exon_truncations_to_the_curator():
    ldlr = RULES.genes["LDLR"]
    early = assess("LDLR", ldlr, None, vep("stop_gained", "p.Glu13Ter", exon="2/18"), [])
    assert labels(early) == ["PM2", "PVS1"] and early["classification"] == "Pathogenic"
    late = assess("LDLR", ldlr, None, vep("stop_gained", "p.Lys830Ter", exon="18/18"), [])
    assert labels(late) == ["PM2"]
    assert "last exon" in late["not_assessed"][0]["reason"]
    assert not late["not_assessed"][0]["decided"]  # left to the curator, not ruled out


def test_splice_pvs1_depends_on_the_skipped_exon_keeping_the_frame():
    ldlr, lengths = RULES.genes["LDLR"], [90, 100, 99, 120, 80]
    donor = vep("splice_donor_variant", intron="2/4", exon=None, hgvsc="c.200+1G>A")
    acceptor = vep("splice_acceptor_variant", intron="2/4", exon=None, hgvsc="c.201-1G>A")
    assert labels(assess("LDLR", ldlr, freq(), donor, lengths)) == ["PVS1"]  # exon 2, 100 nt
    in_frame = assess("LDLR", ldlr, freq(), acceptor, lengths)  # skips exon 3, 99 nt
    assert labels(in_frame) == [] and "keeps the frame" in in_frame["not_assessed"][0]["reason"]
    first = vep("splice_donor_variant", intron="1/4", exon=None)
    reason = assess("LDLR", ldlr, freq(), first, lengths)["not_assessed"][0]["reason"]
    assert "first or last" in reason


def test_enigma_table_sets_pvs1_and_pm5_by_exon():
    brca1, brca2 = RULES.genes["BRCA1"], RULES.genes["BRCA2"]
    early = assess("BRCA2", brca2, None, vep("stop_gained", "p.Glu13Ter", exon="2/27"), [])
    assert labels(early) == ["PM2_Supporting", "PM5_Strong", "PVS1"]
    assert early["classification"] == "Pathogenic"  # 8 + 4 + 1
    # BRCA1 exon 9: the natural isoform skipping exons 8 and 9 rescues function.
    rescued = assess(
        "BRCA1",
        brca1,
        None,
        vep("frameshift_variant", "p.Thr208AsnfsTer29", exon="9/23", hgvsc="c.623_624del"),
        [],
    )
    assert labels(rescued) == ["PM2_Supporting"]
    assert (
        rescued["not_assessed"][0]["decided"] and "PVS1_N/A" in rescued["not_assessed"][0]["reason"]
    )
    # The last exon is split by the premature stop's codon: before 3310 counts, after not.
    last = lambda hgvsp: assess("BRCA2", brca2, None, vep("stop_gained", hgvsp, exon="27/27"), [])  # noqa: E731
    assert "PVS1" in labels(last("p.Glu3309Ter"))
    assert "PVS1" not in labels(last("p.Lys3326Ter"))


def test_enigma_table_sets_splice_sites_by_the_exact_change():
    brca1, brca2 = RULES.genes["BRCA1"], RULES.genes["BRCA2"]
    splice = lambda hgvsc: vep("splice_donor_variant", intron="5/22", exon=None, hgvsc=hgvsc)  # noqa: E731
    small = assess("BRCA1", brca1, freq(), splice("c.301+1G>T"), [])
    # Table 4 rates the site Supporting; Table 9's calibrated assays found normal function.
    assert labels(small) == ["BS3", "PVS1_Supporting"]
    assert small["classification"] == "Likely benign"  # 1 - 4
    rescued = assess("BRCA2", brca2, freq(), splice("c.425+1G>A"), [])
    assert labels(rescued) == [] and rescued["not_assessed"][0]["decided"]
    deleted = assess("BRCA1", brca1, freq(), splice("c.302-2del"), [])
    assert labels(deleted) == ["PVS1"] and "one-base deletion" in deleted["met"][0]["reason"]
    assert labels(assess("BRCA1", brca1, freq(), splice("c.301+1del"), [])) == ["PVS1_Supporting"]
    # At c.4097-1 the table gives some substitutions very strong and others supporting.
    disputed = assess("BRCA1", brca1, freq(), splice("c.4097-1del"), [])
    assert labels(disputed) == [] and not disputed["not_assessed"][0]["decided"]
    unlisted = assess("BRCA1", brca1, freq(), splice("c.999+5G>A"), [])
    assert labels(unlisted) == [] and not unlisted["not_assessed"][0]["decided"]


def test_enigma_functional_table_adds_ps3_or_bs3():
    brca1 = RULES.genes["BRCA1"]
    missense = lambda hgvsc: vep("missense_variant", "p.X", hgvsc=hgvsc)  # noqa: E731
    damaging = assess("BRCA1", brca1, None, missense("c.100C>T"), [])  # p.(Pro34Ser), LOF
    assert labels(damaging) == ["PM2_Supporting", "PS3"]
    normal = assess("BRCA1", brca1, freq(), missense("c.100C>G"), [])  # p.(Pro34Ala), FUNC
    assert labels(normal) == ["BS3"] and normal["classification"] == "Likely benign"
    unclear = assess("BRCA1", brca1, freq(), missense("c.100C>A"), [])  # p.(Pro34Thr), INT
    assert labels(unclear) == [] and unclear["not_assessed"][-1]["code"] == "PS3/BS3"
    assert assess("LDLR", RULES.genes["LDLR"], freq(), missense("c.100C>T"), [])["met"] == []


def test_apc_pvs1_counts_truncations_by_codon_not_exon():
    apc = RULES.genes["APC"]
    stop = lambda hgvsp, exon: assess("APC", apc, freq(), vep("stop_gained", hgvsp, exon=exon), [])  # noqa: E731
    assert labels(stop("p.Gln433Ter", "10/16")) == ["PVS1"]
    assert labels(stop("p.Gln1935SerfsTer35", "16/16")) == ["PVS1"]  # last exon still counts
    early = stop("p.Gln12AlafsTer3", "2/16")
    assert labels(early) == [] and early["not_assessed"][0]["decided"]
    assert labels(stop("p.Tyr2646Ter", "16/16")) == []
    splice = vep("splice_donor_variant", intron="3/15", exon=None, hgvsc="c.220+1G>A")
    result = assess("APC", apc, freq(), splice, [90, 100, 99])
    assert labels(result) == [] and "for the curator" in result["not_assessed"][0]["reason"]


def test_points_map_to_classes_at_every_boundary():
    def met(*codes):
        return [{"code": c, "strength": s} for c, s in codes]

    strong = ("PVS1", "strong")
    assert classify(met(("PVS1", "very_strong"), ("PM2", "moderate")))["classification"] == (
        "Pathogenic"
    )
    assert classify(met(("PVS1", "very_strong"), ("PM2", "supporting")))["points"] == 9
    assert classify(met(strong, ("PM2", "moderate")))["classification"] == "Likely pathogenic"
    assert (
        classify(met(strong, ("PM2", "supporting")))["classification"] == "Uncertain significance"
    )
    assert classify([])["classification"] == "Uncertain significance"
    assert classify(met(("BS1", "supporting")))["classification"] == "Likely benign"
    assert (
        classify(met(("BS1", "strong"), ("BS1", "moderate")))["classification"] == "Likely benign"
    )
    assert classify(met(("BS1", "strong"), ("BS1", "strong")))["classification"] == "Benign"
    assert classify(met(("BA1", "stand_alone")))["classification"] == "Benign"


def test_labels_name_a_changed_strength():
    assert label("PVS1", "very_strong") == "PVS1"
    assert label("PVS1", "moderate") == "PVS1_Moderate"
    assert label("BS1", "supporting") == "BS1_Supporting"


def test_gnomad_details_take_grpmax_from_non_bottlenecked_groups(tmp_path):
    def post(query, variables):
        joint = {
            "ac": 30,
            "an": 100_000,
            "faf95": {"popmax": 0.0004, "popmax_population": "afr"},
            "populations": [
                {"id": "afr", "ac": 10, "an": 10_000},
                {"id": "fin", "ac": 15, "an": 5_000},  # bottlenecked: left out of grpmax
                {"id": "nfe", "ac": 5, "an": 50_000},
            ],
        }
        return {"data": {"v0": {"joint": joint}, "v1": {"joint": {"ac": 0, "an": 0}}}}

    found = details(["1-1-A-G", "1-2-A-G"], tmp_path / "d.json", post=post, wait=0)
    assert found["1-1-A-G"]["grpmax_af"] == 0.001 and found["1-1-A-G"]["faf95"] == 0.0004
    assert found["1-2-A-G"] is None


def test_vep_reads_the_mane_select_transcript_of_a_listed_gene(tmp_path):
    calls = []

    def request(path, body=None):
        calls.append(path)
        if path.startswith("/lookup"):
            exons_ = [{"start": 100, "end": 199}, {"start": 300, "end": 349}]
            return {"strand": -1, "Exon": exons_}
        return [
            {
                "id": "17-5-C-T",
                "transcript_consequences": [
                    {"gene_symbol": "BRCA1", "transcript_id": "ENST2", "mane_select": None},
                    {
                        "gene_symbol": "BRCA1",
                        "transcript_id": "ENST1",
                        "mane_select": "NM_007294.4",
                        "consequence_terms": ["stop_gained"],
                        "hgvsc": "ENST1.9:c.37G>T",
                        "hgvsp": "ENSP1.4:p.Glu13Ter",
                        "protein_start": 13,
                        "exon": "2/23",
                    },
                ],
            },
            {
                "id": "17-9-C-T",
                "transcript_consequences": [{"gene_symbol": "NBR2", "mane_select": "x"}],
            },
        ]

    found = annotate(["17-5-C-T", "17-9-C-T"], {"BRCA1"}, tmp_path / "v.json", request, wait=0)
    assert found["17-5-C-T"]["transcript"] == "ENST1"
    assert found["17-5-C-T"]["hgvsc"] == "c.37G>T" and found["17-5-C-T"]["hgvsp"] == "p.Glu13Ter"
    assert found["17-9-C-T"] is None
    # Minus strand: the transcript starts at the highest position.
    assert exons(["ENST1"], tmp_path / "e.json", request, wait=0) == {"ENST1": [50, 100]}
    annotate(["17-5-C-T"], {"BRCA1"}, tmp_path / "v.json", request, wait=0)
    assert len(calls) == 2  # the rerun is answered from the cache


def assessed(expected, gene="BRCA1", frequency=None, consequence=None):
    return {
        "id": f"{gene}:{expected}:{len(str(frequency))}",
        "gnomad_id": f"{gene}-{expected}-{frequency}",
        "expected": expected,
        "_frequency": frequency,
        "_vep": consequence or {**vep(), "gene": gene},
    }


def test_score_counts_agreement_and_reversals():
    variants = [
        assessed("Pathogenic", consequence={**vep("stop_gained", "p.Glu13Ter"), "gene": "BRCA1"}),
        assessed("Benign", frequency=freq(faf=0.01)),
        assessed("Likely_benign", frequency=freq(faf=0.01)),
        assessed("Pathogenic", frequency=freq(faf=0.01)),  # a reversal
        assessed("Uncertain_significance"),
    ]
    variants.append({**assessed("Benign"), "_vep": {**vep(), "gene": "TP53"}})  # not in the rules
    result = curate(
        variants,
        RULES,
        {v["gnomad_id"]: v["_frequency"] for v in variants},
        {v["gnomad_id"]: v["_vep"] for v in variants},
        {},
    )
    assert len(result) == 5
    s = score(result)
    assert s["reversals"] == 1 and s["agreement"] == pytest.approx(4 / 5)
    assert s["confusion"]["P/LP"] == {"P/LP": 1, "VUS": 0, "B/LB": 1}
    assert s["by_gene"]["BRCA1"]["variants"] == 5


def test_a_run_is_stored_with_its_sources(pg, dq_schema):
    variants = [
        assessed("Pathogenic", consequence={**vep("stop_gained", "p.Glu13Ter"), "gene": "BRCA1"})
    ]
    result = curate(
        variants,
        RULES,
        {variants[0]["gnomad_id"]: None},
        {variants[0]["gnomad_id"]: variants[0]["_vep"]},
        {},
    )
    run_sources = sources(RULES, "gnomad_r4", 116, "20261115")
    assert run_sources["cspec"]["MLH1"] == "GN115 v2.0"
    run_id = save_run(pg, "eval", run_sources, result, score(result))
    row = pg.execute(
        "SELECT a.classification, a.expected, r.sources->>'ensembl' FROM curation.assessment a"
        " JOIN curation.run r USING (run_id) WHERE run_id = %s",
        [run_id],
    ).fetchone()
    assert row == ("Pathogenic", "Pathogenic", "116")  # PVS1, PM5_Strong, PM2_Supporting


def test_erepo_codes_parse_with_their_strength():
    from ehr_rwe_eln.curation.erepo import parse_code

    assert parse_code("PM2_Supporting") == ("PM2", "supporting")
    assert parse_code("PVS1") == ("PVS1", "very_strong")
    assert parse_code(" BS3 ") == ("BS3", "strong")
    assert parse_code("PP4_Strong") == ("PP4", "strong")


def test_erepo_export_is_read_by_variation_id(tmp_path):
    from ehr_rwe_eln.curation.erepo import read_erepo

    header = [
        "#Variation", "ClinVar Variation Id", "HGNC Gene Symbol", "Assertion",
        "Applied Evidence Codes (Met)", "Applied Evidence Codes (Not Met)", "PubMed Articles",
        "Guideline", "Retracted",
    ]  # fmt: skip
    rows = [
        ["v1", "37404", "BRCA1", "Pathogenic", "PS3, PVS1", "BA1, PM2", "123, 456", "g", "false"],
        ["v2", "11", "BRCA1", "Benign", "BA1", "", "", "g", "true"],  # retracted
        ["v3", "12", "TP53", "Benign", "BA1", "", "", "g", "false"],  # not a panel gene
        ["v4", "-", "LDLR", "Benign", "BA1", "", "", "g", "false"],  # no ClinVar id
    ]
    path = tmp_path / "erepo.tsv"
    path.write_text("\n".join("\t".join(r) for r in [header, *rows]) + "\n")
    found = read_erepo(path, {"BRCA1", "LDLR"})
    assert list(found) == [37404]
    assert found[37404]["met"] == ["PS3", "PVS1"] and found[37404]["pmids"] == ["123", "456"]


def test_criteria_are_scored_against_the_panel_codes():
    from ehr_rwe_eln.curation.erepo import score_criteria

    def a(ours, met, not_met):
        criteria = [{"code": c, "strength": s} for c, s in ours]
        return {"met": criteria, "evidence": {"expert": {"met": met, "not_met": not_met}}}

    scored = score_criteria(
        [
            a([("PVS1", "very_strong"), ("PM2", "supporting")], ["PVS1", "PM2_Supporting"], []),
            a([("PVS1", "very_strong")], ["PVS1_Strong"], []),  # agreed, other strength
            a([("PM2", "supporting")], [], ["PM2"]),  # extra, the panel said not met
            a([("BS1", "strong")], [], []),  # extra, the panel did not list it
            a([], ["PS3"], []),  # missed
            {"met": [], "evidence": {}},  # not an ERepo variant: ignored
        ]
    )
    assert scored["PVS1"]["agreed"] == 2 and scored["PVS1"]["same_strength"] == 1
    assert scored["PM2"]["extra_marked_not_met"] == 1 and scored["PM2"]["precision"] == 0.5
    assert scored["BS1"]["extra_not_listed"] == 1 and scored["BS1"]["recall"] is None
    assert scored["PS3"]["missed"] == 1 and scored["PS3"]["recall"] == 0.0
