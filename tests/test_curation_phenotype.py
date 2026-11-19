import math

import pytest

from ehr_rwe_eln.curation.phenotype import (
    information_content,
    load_manual,
    map_conditions,
    percentiles,
    read_gene_terms,
    read_obo,
    similarity,
)

# A tiny ontology in OBO format: a root, two branches, a leaf under each, one obsolete term.
OBO = """\
format-version: 1.2
data-version: hp/releases/2026-01-01

[Term]
id: HP:0000001
name: All

[Term]
id: HP:0000010
name: Cancer
is_a: HP:0000001 ! All

[Term]
id: HP:0000011
name: Breast carcinoma
synonym: "Breast cancer" EXACT []
synonym: "Mammary tumour" RELATED []
alt_id: HP:0000099
is_a: HP:0000010 ! Cancer

[Term]
id: HP:0000012
name: Colon cancer
is_a: HP:0000010 ! Cancer

[Term]
id: HP:0000020
name: Hyperlipidemia
is_a: HP:0000001 ! All

[Term]
id: HP:0000030
name: Old term
is_obsolete: true

[Typedef]
id: part_of
name: part of
"""

GENES = """\
ncbi_gene_id\tgene_symbol\thpo_id\thpo_name\tfrequency\tdisease_id
1\tBRCA1\tHP:0000099\tBreast carcinoma\t-\tOMIM:1
1\tBRCA1\tHP:0000012\tColon cancer\t-\tOMIM:1
2\tLDLR\tHP:0000020\tHyperlipidemia\t-\tOMIM:2
3\tMLH1\tHP:0000012\tColon cancer\t-\tOMIM:3
3\tMLH1\tHP:0000030\tOld term\t-\tOMIM:3
"""


@pytest.fixture
def ont(tmp_path):
    (tmp_path / "hp.obo").write_text(OBO)
    return read_obo(tmp_path / "hp.obo")


@pytest.fixture
def genes(tmp_path, ont):
    (tmp_path / "g2p.txt").write_text(GENES)
    return read_gene_terms(tmp_path / "g2p.txt", ont)


def test_obo_terms_links_synonyms_and_retired_ids(ont):
    assert ont.release == "2026-01-01" and "part_of" not in ont.names
    assert ont.ancestors("HP:0000011") == {"HP:0000011", "HP:0000010", "HP:0000001"}
    assert ont.synonyms["HP:0000011"] == ["Breast cancer"]  # exact synonyms only
    assert ont.current("HP:0000099") == "HP:0000011" and ont.current("HP:0000030") is None


def test_gene_terms_resolve_retired_ids_and_drop_obsolete_ones(genes):
    assert genes == {
        "BRCA1": {"HP:0000011", "HP:0000012"},
        "LDLR": {"HP:0000020"},
        "MLH1": {"HP:0000012"},
    }


def test_information_content_is_rarity_among_genes(ont, genes):
    ic = information_content(ont, genes)
    assert ic["HP:0000001"] == 0  # every gene
    assert ic["HP:0000010"] == pytest.approx(math.log(3 / 2))  # BRCA1 and MLH1
    assert ic["HP:0000011"] == pytest.approx(math.log(3))  # BRCA1 only


def test_similarity_rewards_the_most_specific_shared_term(ont, genes):
    ic = information_content(ont, genes)
    breast = {"HP:0000011"}
    assert similarity(breast, genes["BRCA1"], ont, ic) == pytest.approx(math.log(3))
    # MLH1 has colon cancer, which shares only "Cancer" with breast carcinoma
    assert similarity(breast, genes["MLH1"], ont, ic) == pytest.approx(math.log(3 / 2))
    assert similarity(breast, genes["LDLR"], ont, ic) == 0
    both = {"HP:0000011", "HP:0000020"}
    assert similarity(both, genes["LDLR"], ont, ic) == pytest.approx(math.log(3) / 2)
    assert similarity(both, genes["LDLR"], ont, ic, "max") == pytest.approx(math.log(3))
    assert similarity(set(), genes["LDLR"], ont, ic) == 0


def test_percentiles_are_the_share_scoring_at_or_below(ont):
    score = [0.1, 0.5, 0.5, 0.9, 0.2]
    assert percentiles(score, [3, 1, 0]) == [100.0, 80.0, 20.0]


def test_conditions_map_by_table_then_name_then_nearest_ancestor(ont):
    concepts = {
        1: "Malignant neoplasm of breast",
        2: "Breast cancer",
        3: "Hyperlipidemia (disorder)",
        4: "Familial hyperlipidemia",
        5: "Gingivitis",
    }
    mapped = map_conditions(concepts, {4: [3, 2], 5: [99]}, ont, {1: "HP:0000011"})
    assert mapped[1] == {"hpo": "HP:0000011", "method": "table"}
    assert mapped[2] == {"hpo": "HP:0000011", "method": "name"}  # an exact synonym
    assert mapped[3] == {"hpo": "HP:0000020", "method": "name"}  # parenthesized tag ignored
    assert mapped[4] == {"hpo": "HP:0000020", "method": "ancestor", "via": 3}
    assert 5 not in mapped


def test_hand_table_must_name_the_term_it_points_to(tmp_path, ont):
    table = tmp_path / "t.yaml"
    table.write_text('concepts:\n  7: {name: x, hpo: "HP:0000099", hpo_name: Breast carcinoma}\n')
    assert load_manual(ont, table) == {7: "HP:0000011"}
    table.write_text('concepts:\n  7: {name: x, hpo: "HP:0000012", hpo_name: Breast carcinoma}\n')
    with pytest.raises(ValueError, match="is not 'Breast carcinoma'"):
        load_manual(ont, table)


def test_the_shipped_table_parses():
    import yaml

    from ehr_rwe_eln.curation.phenotype import CONDITIONS

    entries = yaml.safe_load(CONDITIONS.read_text())["concepts"]
    assert all(e["hpo"].startswith("HP:") and e["hpo_name"] for e in entries.values())
