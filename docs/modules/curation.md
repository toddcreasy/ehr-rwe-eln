# Variant curation

Package: `ehr_rwe_eln.curation`. Back to the [README](../../README.md). Terms are defined in the [glossary](../GLOSSARY.md).

Classifies variants the way a clinical lab starts to: it applies the [ACMG/AMP](https://doi.org/10.1038/gim.2015.30) criteria that data alone can decide, with each gene's thresholds from its [ClinGen](https://clinicalgenome.org) expert panel, adds them up on the Bayesian points scale, and says what it could not decide and why. It curates the [clinical panel](genomics.md#clinical-panel) planted in the synthetic study, and is scored against ClinVar's expert-panel classifications, which it never reads.

It also matches each study subject's conditions against the panel genes with the [Human Phenotype Ontology](#phenotype-matching) (HPO), and checks whether that finds the planted carriers.

## Who decides what

| | Decides | Stored in | Can change a class? |
|---|---|---|---|
| The rules (`rules.py`) | The criteria data alone can settle: frequency (BA1, BS1, PM2), null variants (PVS1, PM5_PTC), ENIGMA's calibrated assays (PS3, BS3). Each with its reason, and what it could not decide | `curation.assessment` | Yes: the points and class come from these |
| Claude (`literature.py`) | Nothing. It proposes PS3, BS3, PS4, or PP1 from passages that name the variant; code rejects any claim whose PMID was not sent or whose quote is not in the passage | `curation.proposal` | No |
| HPO phenotype (`phenotype.py`) | Nothing. Where the variant's carriers fall on a phenotype score for the gene's group | `curation.phenotype` | No: context, not PP4 |
| The curator (`/curation/`) | The class. Accepts the verified proposals they agree with, sees the rescored points, records a class with their name and the time; a class other than the score needs a note | `curation.decision`, added to and never changed | Yes, and only a decision is final |

The rules' points and class stand until a curator decides. Nothing Claude writes reaches a class without a person accepting it.

## What it does

1. **Gather evidence** for each variant from its position and alleles alone:
   - [gnomAD](https://gnomad.broadinstitute.org) v4, exomes and genomes joined: allele count, overall frequency, the highest frequency in a non-bottlenecked ancestry group (grpmax), and the filtering allele frequency (FAF95) in the group where it is highest. Expert panels set their thresholds on the FAF.
   - [Ensembl VEP](https://www.ensembl.org/info/docs/tools/vep/index.html) on the MANE Select transcript: the consequence, the c. and p. names, and the exon or intron. Unlike gnomAD, VEP annotates variants nobody has seen, which is most pathogenic ones.
   - The exon lengths of each MANE transcript from Ensembl, for the splice rule.
2. **Apply each gene's expert-panel rules** (`rules.yaml`, `rules.py`). Thresholds are transcribed from the [CSpec registry](https://cspec.genome.network), with the panel, document, and version on each gene:

   | Gene | Panel (CSpec) | BA1 | BS1 | PM2 | PVS1 |
   |---|---|---|---|---|---|
   | BRCA1, BRCA2 | ENIGMA (GN092, GN097 v1.2) | FAF > 0.1% | Strong: FAF > 0.01%; Supporting: > 0.002% | Supporting: absent | ENIGMA Table 4: by exon, with PM5_PTC; splice sites by exact change |
   | MLH1 | InSiGHT (GN115 v2.0) | FAF ≥ 0.1% | Strong: 0.01% to 0.1% | Supporting: AF < 0.002% | Stop at codon ≤ 753; Moderate 754 to 756 |
   | MSH2 | InSiGHT (GN137 v2.0) | FAF ≥ 0.1% | Strong: 0.01% to 0.1% | Supporting: AF < 0.002% | Stop at codon ≤ 891; Moderate 892 to 934 |
   | APC | InSiGHT (GN089 v2.1) | FAF ≥ 0.1% | Strong: FAF ≥ 0.001% | Supporting: by AF and allele count | Truncations from codon 49 to 2645, any exon; splice sites to the curator |
   | LDLR | Familial Hypercholesterolemia (GN013 v1.2) | FAF ≥ 0.5% | Strong: FAF ≥ 0.2% | **Moderate**: grpmax AF ≤ 0.02% | NMD rule |

   PVS1 follows each panel's own rules where they can be read from data:

   - **BRCA1 and BRCA2** use ENIGMA's Specifications Table 4 ([v1.2](https://cspec.genome.network/cspec/ui/svi/doc/GN092)), transcribed to `enigma_pvs1.yaml` by `scripts/import_enigma_pvs1.py`. For a variant that introduces a premature stop, the exon decides: most exons give PVS1 plus an exon-specific PM5_PTC weight (other proven pathogenic stops in the same exon); BRCA1 exons 8 and 9 give nothing, because a natural isoform skipping them keeps the protein working; the last exons are split by the stop's codon (BRCA1 before 1855, BRCA2 before 3310). Each canonical splice-site change has its own code, from very strong to not applicable. A one-base deletion at a canonical site takes the table's strength only when every substitution listed at that position has the same one.
   - **APC** follows [Spier et al. 2024](https://doi.org/10.1016/j.gim.2023.100992): its last exon is most of the gene and truncations there cause disease without NMD, so PVS1 applies to truncations starting between codons 49 and 2645, the 5'-most and 3'-most the panel could classify likely pathogenic, in any exon. Splice sites are graded in the panel's supplement and go to the curator.
   - **MLH1 and MSH2** use the panel's codon cut-offs for the premature stop.
   - **LDLR**, and splice sites in MLH1 and MSH2, use the NMD rule: a nonsense or frameshift variant outside the last exon is PVS1, since nonsense-mediated decay destroys its mRNA; one in the last exon is left to the curator. A canonical splice-site variant (±1, ±2) is PVS1 when skipping the exon it serves shifts the reading frame (its length is not a multiple of three); when skipping keeps the frame, whether the lost region matters is left to the curator.

   Where a panel's rule says PVS1 does not apply, the assessment records that as decided, so a curator can tell "ruled out by the panel" from "the rules could not tell".

   **Functional evidence (PS3, BS3).** For BRCA1 and BRCA2, ENIGMA's Specifications Table 9 gives the code its calibrated functional assays support for 4,731 variants: PS3 (damaging, 931), BS3 (no damaging effect, 3,363), or none (inconclusive, 437). `scripts/import_enigma_functional.py` transcribes it to `enigma_functional.tsv`, and the rules apply it by the variant's c. name. Functional evidence for the other genes comes from the literature (the next step).
3. **Add up the points** ([Tavtigian et al. 2020](https://doi.org/10.1002/humu.24088)): supporting 1, moderate 2, strong 4, very strong 8, benign evidence negative. 10 or more is pathogenic, 6 to 9 likely pathogenic, 0 to 5 uncertain significance, -1 to -6 likely benign, -7 or less benign. BA1 is benign on its own.
4. **Store the run** (`curate.py`) in the `curation` schema: every assessment with its evidence, the criteria met and not assessed (each with its reason), the points, and the class; and on the run, every source and version (gnomAD dataset, Ensembl release, ClinVar release, each panel's CSpec version, a hash of `rules.yaml`, the git commit).

5. **Propose literature evidence** (`literature.py`). For PS3 and BS3 (functional studies), PS4 (case-control or proband counts), and PP1 (segregation), Claude reads what papers say about the variant and proposes criteria, each claim with a PMID and a quoted sentence. Retrieval: [LitVar2](https://www.ncbi.nlm.nih.gov/research/litvar2/), NCBI's index of variant mentions, gives the PMIDs; [PubTator3](https://www.ncbi.nlm.nih.gov/research/pubtator3/) gives each paper's text (full text for open-access PMC articles, the abstract otherwise); only passages that name the variant are sent, under any of its names, including older numbering (LDLR residues without the signal peptide; BRCA1 and BRCA2 BIC nucleotides). Claude (Opus 4.6 on Amazon Bedrock) replies in a typed schema. Every claim is then verified in code: its PMID must be one that was sent and its quote must appear in a passage sent from that paper; a claim that fails is stored as rejected, with the reason. Verified claims go to `curation.proposal`, apart from the rules' assessments.
6. **Decide** (`/curation/` page, `src/ehr_rwe_eln/api/curation.py`). For each variant the page shows the evidence (gnomAD, VEP), the criteria the rules met and what they left to the curator, each with its reason, Claude's proposals with their quotes and PubMed links, and the run's sources and versions. The curator ticks the verified proposals they accept, and the page rescores: the rules' criteria plus the accepted ones, through the same points scale. A proposal cannot add a criterion the rules already met (ENIGMA's PS3 table and a paper's PS3 would otherwise count twice), and a criterion accepted from two papers counts once, at the stronger strength. The curator then records a class with their name. A class other than the scored one needs a note saying why. Decisions go to `curation.decision`, which is only ever added to: a new decision on a variant adds a row, so the history of who decided what, and when, is kept.

## Run it

```bash
uv run python scripts/curate_variants.py --set panel   # the clinical panel's 48 variants
uv run python scripts/curate_variants.py --set eval    # ClinVar expert-panel variants, scored
uv run python scripts/curate_variants.py --set erepo   # Evidence Repository curations, by criterion
uv run python scripts/curate_literature.py --dry-run   # retrieval and input tokens only, free
uv run python scripts/curate_literature.py             # Claude proposes literature evidence, about $0.25 for 10
uv run pytest evals/test_curation_literature.py -s     # the literature eval, about $0.15
uv run fastapi dev                                     # then http://127.0.0.1:8000/curation/
uv run python scripts/match_phenotypes.py              # HPO phenotype scores and their eval, 15 s; reads OMOP from the lake
```

`uv run python scripts/import_enigma_pvs1.py` and `scripts/import_enigma_functional.py` refresh ENIGMA's tables when the panel releases a new version. The `erepo` run downloads ClinGen's Evidence Repository export (33 MB, CC0) to `data/reference/clingen/` the first time. Both curation runs read positions and alleles only. gnomAD, VEP, and exon answers are cached under `data/reference/` per release, so reruns make no requests. A first run asks gnomAD about several hundred variants at its limit of 10 requests a minute, about 10 minutes; when gnomAD answers that it is overloaded, the client waits and retries, and never records a busy answer as "absent".

## Results

2026-11-19; ClinVar 2026-11-15, gnomAD v4, Ensembl 116.

**The clinical panel.** 47 of the 48 planted variants land in the class their ClinVar record would put them in: all 18 pathogenic (8 pathogenic, 10 likely pathogenic), all 18 benign, and 11 of 12 uncertain. The other, LDLR p.Arg814Gln, uncertain in ClinVar (expert panel), comes out likely benign: its gnomAD v4 FAF95 is 0.36% in the African ancestry group, above the panel's BS1 threshold of 0.2%. The panel's classification may predate gnomAD v4; it is a real disagreement, for a curator to settle.

**Against ClinVar expert panels.** 578 variants with three ClinVar stars in the six genes, up to 20 per gene and class, sampled with a fixed seed. The rules never read the classification.

| Expert panel (rows), rules (columns) | P/LP | VUS | B/LB |
|---|---|---|---|
| Pathogenic or likely pathogenic | 120 | 120 | 0 |
| Uncertain significance | 2 | 108 | 6 |
| Benign or likely benign | 0 | 78 | 144 |

Agreement is 64.4% overall, from 48% (LDLR) to 74% (MSH2), with no reversals. The number to read first is how often a decision is right when the rules make one: 120 of 122 pathogenic or likely pathogenic calls (98%) and 144 of 150 benign or likely benign calls (96%). ENIGMA's functional table adds PS3 to 43 of these variants and BS3 to 8. Most of the rest is evidence data alone cannot reach:

- Pathogenic variants called uncertain (120): 81 missense, which need functional, case, or segregation evidence (the literature step); 21 splice-region variants outside the canonical ±1, ±2 sites; 17 truncations or splice sites the rules leave to the curator (MSH2 7, APC 6, LDLR 3, MLH1 1); 1 in-frame deletion. One BRCA2 variant is pathogenic to ENIGMA though its own Table 4 rules PVS1 out for it, so its classification rests on other evidence.
- Benign variants called uncertain (78): 46 synonymous and 23 missense. Synonymous variants are usually benign by BP7, which needs a splicing prediction; gnomAD's SpliceAI scores are licensed for non-commercial use only and are not used here.

**Criterion by criterion, against the Evidence Repository.** ClinGen's Evidence Repository lists, for each expert panel curation, every criterion the panel applied ("Met") and considered and rejected ("Not Met"). All 883 short-variant curations in the six genes (LDLR 557, BRCA1 102, APC 101, BRCA2 95, MLH1 16, MSH2 12), scored against the criteria the rules apply:

| Criterion | Agreed | Rules only (panel said not met) | Panel only | Precision | Recall | Same strength |
|---|---|---|---|---|---|---|
| BA1 | 32 | 3 (1) | 1 | 91% | 97% | 32 of 32 |
| BS1 | 27 | 8 (6) | 4 | 77% | 87% | 25 of 27 |
| PM2 | 683 | 18 (18) | 40 | 97% | 94% | 680 of 683 |
| PVS1 | 56 | 2 (2) | 55 | 97% | 50% | 54 of 56 |
| PS3 | 90 | 4 (4) | 139 | 96% | 39% | 90 of 90 |
| BS3 | 13 | 6 (5) | 36 | 68% | 27% | 13 of 13 |
| PM5 | 3 | 1 (0) | 71 | 75% | 4% | 3 of 3 |

When a rule fires it is nearly always the criterion the panel used, at the panel's strength (PM2, PVS1, PS3 at 96% to 97%). Recall is low where the evidence lives outside these rules: PS3 for LDLR and the colorectal genes comes from published functional studies; of the 55 PVS1 misses, 35 are missense or splice-region variants the panels gave PVS1 from RNA assays showing aberrant splicing, 14 are null variants the rules leave to the curator, and 6 are LDLR start-loss variants the rules do not handle; and PM5 the panels mostly apply to missense changes at a residue with a known pathogenic change, which is not implemented. BS3 is the weak spot: of its 6 extras, 5 are variants the panel marked not met though ENIGMA's own Table 9 gives BS3, which suggests curations made before Table 9 v1.2. By class the run has no reversals; pathogenic calls are right 50 of 53 times and benign calls 67 of 73, and agreement is 56.9%, lower than the ClinVar sample because most of these curations are LDLR missense variants classified on literature evidence.

**Where the rules and the panels differ.** Two variants the panels call uncertain come out pathogenic, both by the panels' own rules: BRCA2 p.Glu3309Ter, the last codon before ENIGMA's cut-off at 3310, gets PVS1 and PM5_PTC from Table 4; MLH1 p.Tyr750Ter falls inside InSiGHT's PVS1 cut-off at codon 753. The panels' classifications must rest on evidence beyond these rules.

**What the panel tables changed.** Before them, PVS1 followed only the NMD rule. The pathogenic calls agreed with the panels 114 of 124 times (92%), with ten over-calls and one reversal. Over-calls are the costlier error. ENIGMA's table removed all seven in BRCA1 and BRCA2: exon 9 truncations rescued by a natural isoform, splice sites it rates supporting or not applicable, and a deletion it does not list, now left to the curator. APC's codon boundaries removed the two at codons 12 and 24. The table added one, p.Glu3309Ter, which the NMD rule had left to the curator. And its last-exon rule turned the reversal, a BRCA2 frameshift in exon 27, from likely benign to likely pathogenic, as ENIGMA has it.

**Literature proposals.** Ten Evidence Repository variants the panels scored with PS3, BS3, PS4, or PP1 and that have passages to read, in a fixed order, 2026-11-19, $0.25:

| | |
|---|---|
| Claims | 13, all verified: every PMID was sent, every quote is in its passage |
| Criteria proposed that the panel also applied | 7 (PS3 3, BS3 2, PS4 1, PP1 1) |
| Proposed, the panel did not apply | 3 (2 the panel marked not met) |
| Applied by the panel, not proposed | 7 |

Precision 70%, recall 50%; where both applied PS3 the strength matched every time. One LDLR variant drew both PS3 Moderate and BS3 Supporting from different papers, the kind of conflict the curator resolves. The eval in `evals/` (6 cases) gave 8 claims, all verified, precision 83%. Ten variants is a pilot, not a measurement.

The ceiling is retrieval, not reading. Of 20 such variants, 7 are not in LitVar2 at all, and of the 24 papers the panels cited, none has a passage naming the variant in text PubTator3 provides: the panels' evidence sits in supplementary tables (multiplexed assays such as [Findlay et al. 2018](https://doi.org/10.1038/s41586-018-0461-z), which ENIGMA's Table 9 already captures), or in papers that do not name the variant in reachable text. Adding older numbering found no more. So the proposals come from other papers about the variant, and their agreement with the panels is at the level of criteria, not citations.

## Phenotype matching

`phenotype.py`, `scripts/match_phenotypes.py`. This service/product is using the Human Phenotype Ontology (release 2026-09-01). Find out more at http://www.human-phenotype-ontology.org. [Köhler et al. 2014](https://doi.org/10.1093/nar/gkt1026).

1. **Conditions to HPO terms.** HPO no longer ships SNOMED cross-references, and the OMOP vocabularies loaded here do not carry HPO, so the mapping is ours, in three steps: a hand-written table for 17 conditions that matter for the panel or are common (`hpo_conditions.yaml`, each entry checked against the release's term name on load); an HPO term whose name or exact synonym equals the condition's name; otherwise the term of the nearest OMOP ancestor mapped either way. Of the 513 condition concepts among the 5,000 study subjects, 352 map (17 by table, 76 by name, 259 by ancestor), covering 74% of their condition records. A subject has a median of 9 terms.
2. **Score each gene.** Each gene's terms come from HPO's `genes_to_phenotype.txt`. A subject's score for a gene is the Resnik best match average from the subject's side, as [Phenomizer](https://doi.org/10.1016/j.ajhg.2009.09.003) does it ([glossary](../GLOSSARY.md#information-content-and-resnik-similarity)). Raw scores do not compare across genes: a gene with many annotations matches almost anyone somewhere, so before standardizing, BRCA2 (217 terms) or APC (162) came first for 4,592 of the 5,000 subjects. Each gene's score is standardized over the study (mean 0, standard deviation 1). Scores go to `data/genomics/phenotype_scores.tsv` by subject ID; the OMOP person ID stays in the registry.
3. **Check against the panel's answer key.** The [clinical panel](genomics.md#clinical-panel) chose pathogenic carriers by condition: about 10% of people with breast cancer, colon cancer, or hyperlipidemia (5% for hyperlipidemia), about 0.3% of everyone else, with the gene picked at random within the condition's group. So a phenotype can point to a group (BRCA1 and BRCA2; MLH1, MSH2, and APC; LDLR) but never to one gene within it, and a carrier and a non-carrier with the same condition have the same records. The eval asks whether the score ranks each group's carriers above everyone else (AUC, area under the ROC curve: the chance a random carrier scores above a random non-carrier), with a 95% bootstrap interval, next to the AUC of simply knowing who has the condition. That second number is the reference: about half the carriers were chosen without the condition, so no phenotype can find them.

2026-11-19, HPO 2026-09-01, 5,000 subjects:

| Group | Carriers (with the condition) | Phenotype score AUC (95% interval) | AUC of knowing the condition | Top-scoring gene in the group, carriers with the condition |
|---|---|---|---|---|
| Breast cancer: BRCA1, BRCA2 | 21 (7) | 0.70 (0.60 to 0.79) | 0.66 | 4 of 7 |
| Colon cancer: MLH1, MSH2, APC | 29 (14) | 0.66 (0.53 to 0.77) | 0.73 | 7 of 14 |
| Hyperlipidemia: LDLR | 74 (50) | 0.68 (0.62 to 0.74) | 0.74 | 37 of 50 |

Every interval is above 0.5, and each score comes close to what knowing the condition gives; breast cancer's slightly passes it, within the interval. That is what the panel's design allows, and no more. By gene, MSH2 reaches 0.89 and APC and MLH1 are near chance, as expected when the gene within a group was picked at random: those are noise around the group result, with 8 to 13 carriers each, not differences between genes. **Context for the curator, not evidence.** For each panel variant, the script reads its carriers from `panel.vcf.gz` (the genotypes, not the answer key) and stores in `curation.phenotype` where each carrier's score for the variant's gene group falls among the 5,000 subjects, as a percentile, with no subject IDs. The `/curation/` page shows it next to the evidence. It is not scored as PP4 (phenotype specific to the gene): PP4 is judged for one patient under each expert panel's rules, which this score does not follow, while an assessment here is about a variant with many carriers, and the score finds the right gene group only about as well as knowing who has the condition (decided 2026-11-19).

Scoring by a subject's single best-matching term instead of the average (a sensitivity check, in `phenotype_eval.json`) gives group AUCs of 0.74, 0.75, and 0.68; the average stays the method because it was chosen before the eval and is the standard.

## Limits

- The rules decide only what data alone can. Missense variants, which need functional studies, case data, or segregation, come out uncertain; literature proposals can point a curator to that evidence but do not change the class.
- Literature retrieval reads abstracts and open-access full text, not supplementary tables, so variant-level results from multiplexed assays are out of reach (ENIGMA's Table 9 covers them for BRCA1 and BRCA2).
- PS1 and PM5 (the same or a nearby amino acid change as a known pathogenic variant) are not applied yet: each panel sets its own strengths for them.
- PVS1 follows each panel only as far as data allows. For LDLR, MLH1, and MSH2 splice sites it does not check whether a stop falls in the last 50 nucleotides of the penultimate exon (which also escapes NMD), or a panel's list of critical domains. APC splice sites, initiation codon variants, and exon-level deletions and duplications are left to the curator. ENIGMA's RNA-based codes ("PVS1 (RNA)") are applied at the table's strength without re-reading the RNA data.
- PVS1 from RNA evidence for variants outside the canonical sites (the panels' "PVS1 (RNA)"), and initiation codon (start-loss) variants, are not applied: they need lab data the rules do not have.
- Thresholds are read on gnomAD v4 joined. ENIGMA's are defined on gnomAD v2.1 and v3.1 non-cancer subsets, and PM2 for BRCA1 and BRCA2 also requires read depth of at least 25, not checked. Founder variants, which InSiGHT excludes from BA1 and BS1, are not excepted.
- Phenotype matching is checked only against carriers planted by condition, so it can show that a score finds the right group of genes, not that it tells genes apart. Synthea records diseases, rarely the findings (polyp counts, age at diagnosis, family history) that separate Lynch syndrome from FAP or BRCA1 from BRCA2. The condition mapping is hand-checked for 17 concepts only; the rest rely on name matches and OMOP ancestors.
- The curator's name is what they type: the app has no sign-in, so a decision records who said they made it, not a verified identity.
- This tool includes data from the gnomAD v4 release. For research and demonstration; not for clinical use.
