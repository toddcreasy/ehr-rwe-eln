# Variant curation

Package: `ehr_rwe_eln.curation`. Back to the [README](../../README.md). Terms are defined in the [glossary](../GLOSSARY.md).

Classifies variants the way a clinical lab starts to: it applies the [ACMG/AMP](https://doi.org/10.1038/gim.2015.30) criteria that data alone can decide, with each gene's thresholds from its [ClinGen](https://clinicalgenome.org) expert panel, adds them up on the Bayesian points scale, and says what it could not decide and why. It curates the [clinical panel](genomics.md#clinical-panel) planted in the synthetic study, and is scored against ClinVar's expert-panel classifications, which it never reads.

This is the rules step. Literature evidence (C2) and a curator's review and sign-off (C3) come next; until then nothing here is a final classification.

## What it does

1. **Gather evidence** for each variant from its position and alleles alone:
   - [gnomAD](https://gnomad.broadinstitute.org) v4, exomes and genomes joined: allele count, overall frequency, the highest frequency in a non-bottlenecked ancestry group (grpmax), and the filtering allele frequency (FAF95) in the group where it is highest. Expert panels set their thresholds on the FAF.
   - [Ensembl VEP](https://www.ensembl.org/info/docs/tools/vep/index.html) on the MANE Select transcript: the consequence, the c. and p. names, and the exon or intron. Unlike gnomAD, VEP annotates variants nobody has seen, which is most pathogenic ones.
   - The exon lengths of each MANE transcript from Ensembl, for the splice rule.
2. **Apply each gene's expert-panel rules** (`rules.yaml`, `rules.py`). Thresholds are transcribed from the [CSpec registry](https://cspec.genome.network), with the panel, document, and version on each gene:

   | Gene | Panel (CSpec) | BA1 | BS1 | PM2 | PVS1 |
   |---|---|---|---|---|---|
   | BRCA1, BRCA2 | ENIGMA (GN092, GN097 v1.2) | FAF > 0.1% | Strong: FAF > 0.01%; Supporting: > 0.002% | Supporting: absent | NMD rule |
   | MLH1 | InSiGHT (GN115 v2.0) | FAF ≥ 0.1% | Strong: 0.01% to 0.1% | Supporting: AF < 0.002% | Stop at codon ≤ 753; Moderate 754 to 756 |
   | MSH2 | InSiGHT (GN137 v2.0) | FAF ≥ 0.1% | Strong: 0.01% to 0.1% | Supporting: AF < 0.002% | Stop at codon ≤ 891; Moderate 892 to 934 |
   | APC | InSiGHT (GN089 v2.1) | FAF ≥ 0.1% | Strong: FAF ≥ 0.001% | Supporting: by AF and allele count | NMD rule |
   | LDLR | Familial Hypercholesterolemia (GN013 v1.2) | FAF ≥ 0.5% | Strong: FAF ≥ 0.2% | **Moderate**: grpmax AF ≤ 0.02% | NMD rule |

   The NMD rule: a nonsense or frameshift variant outside the last exon is PVS1, since nonsense-mediated decay destroys its mRNA; one in the last exon is left to the curator. A canonical splice-site variant (±1, ±2) is PVS1 when skipping the exon it serves shifts the reading frame (the exon's length is not a multiple of three); when skipping keeps the frame, whether the lost region matters is left to the curator.
3. **Add up the points** ([Tavtigian et al. 2020](https://doi.org/10.1002/humu.24088)): supporting 1, moderate 2, strong 4, very strong 8, benign evidence negative. 10 or more is pathogenic, 6 to 9 likely pathogenic, 0 to 5 uncertain significance, -1 to -6 likely benign, -7 or less benign. BA1 is benign on its own.
4. **Store the run** (`curate.py`) in the `curation` schema: every assessment with its evidence, the criteria met and not assessed (each with its reason), the points, and the class; and on the run, every source and version (gnomAD dataset, Ensembl release, ClinVar release, each panel's CSpec version, a hash of `rules.yaml`, the git commit).

## Run it

```bash
uv run python scripts/curate_variants.py --set panel   # the clinical panel's 48 variants
uv run python scripts/curate_variants.py --set eval    # ClinVar expert-panel variants, scored
```

Both read positions and alleles only. gnomAD, VEP, and exon answers are cached under `data/reference/` per release, so reruns make no requests. The first eval run asks gnomAD about several hundred variants at gnomAD's limit of 10 requests a minute, about 10 minutes.

## Results

2026-11-19; ClinVar 2026-11-15, gnomAD v4, Ensembl 116.

**The clinical panel.** Of the 48 planted variants, 46 land in the class their ClinVar record would put them in: all 18 benign, 17 of 18 pathogenic (3 LDLR pathogenic, the other 14 likely pathogenic), all 12 uncertain but one. The two others:

- APC p.Gln1935SerfsTer35, pathogenic, comes out uncertain: it truncates in APC's last exon, which these rules leave to the curator.
- LDLR p.Arg814Gln, uncertain in ClinVar (expert panel), comes out likely benign: its gnomAD v4 FAF95 is 0.36% in the African ancestry group, above the panel's BS1 threshold of 0.2%. The panel's classification may predate gnomAD v4; it is a real disagreement, for a curator to settle.

**Against ClinVar expert panels.** 578 variants with three ClinVar stars in the six genes, up to 20 per gene and class, sampled with a fixed seed. The rules never read the classification.

| Expert panel (rows), rules (columns) | P/LP | VUS | B/LB |
|---|---|---|---|
| Pathogenic or likely pathogenic | 114 | 125 | 1 |
| Uncertain significance | 10 | 102 | 4 |
| Benign or likely benign | 0 | 81 | 141 |

Agreement is 61.8% overall, from 48% (LDLR) to 74% (MSH2). The number to read first is how often a decision is right when the rules make one: 114 of 124 pathogenic or likely pathogenic calls (92%) and 141 of 146 benign or likely benign calls (97%). Most of the rest is evidence data alone cannot reach:

- Pathogenic variants called uncertain (125): 81 missense, which need functional, case, or segregation evidence (the literature step); 23 truncations left to the curator (last exon); 21 splice-region variants outside the canonical ±1, ±2 sites; 1 in-frame deletion.
- Benign variants called uncertain (81): 49 synonymous and 23 missense. Synonymous variants are usually benign by BP7, which needs a splicing prediction; gnomAD's SpliceAI scores are licensed for non-commercial use only and are not used here.

**Where the rules are wrong.** One reversal: BRCA2 p.Cys3233TrpfsTer15, likely pathogenic to ENIGMA, comes out likely benign. It is in the last exon, so PVS1 is left alone, and its gnomAD v4 FAF95 (0.019%, Latino/Admixed American) is above ENIGMA's BS1 threshold of 0.01%. ENIGMA sets that threshold on gnomAD v2.1 and v3.1 non-cancer subsets, not v4; on v4 this variant crosses it.

Ten variants the panels call uncertain come out likely pathogenic, all on PVS1: BRCA1 frameshifts at codons 208 and 209 and splice sites c.301+1; BRCA2 splice sites c.425+1 and c.681+1 and c.672_681+23del; APC stops at codons 12 and 24, at the start of the gene; and MLH1 p.Tyr750Ter, inside the panel's own codon cut-off. ENIGMA's PVS1 flowchart and APC's modified decision tree reduce or withhold PVS1 in specific regions, in tables these rules do not encode. Over-calling is the costlier error, so encoding those tables comes before these classifications go to a curator.

## Limits

- Only the criteria data alone decides. Missense variants, which need functional studies, case data, or segregation, come out uncertain until the literature step (C2).
- PS1 and PM5 (the same or a nearby amino acid change as a known pathogenic variant) are not applied yet: each panel sets its own strengths for them.
- PVS1 follows each panel only as far as data allows. It does not check whether a stop falls in the last 50 nucleotides of the penultimate exon (which also escapes NMD), or a panel's list of critical domains. APC's panel uses a modified decision tree in which truncations in the last exon, most of the gene, can be pathogenic; this leaves those to the curator.
- Thresholds are read on gnomAD v4 joined. ENIGMA's are defined on gnomAD v2.1 and v3.1 non-cancer subsets, and PM2 for BRCA1 and BRCA2 also requires read depth of at least 25, not checked. Founder variants, which InSiGHT excludes from BA1 and BS1, are not excepted.
- This tool includes data from the gnomAD v4 release. For research and demonstration; not for clinical use.
