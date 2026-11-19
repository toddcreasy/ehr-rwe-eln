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
3. **Add up the points** ([Tavtigian et al. 2020](https://doi.org/10.1002/humu.24088)): supporting 1, moderate 2, strong 4, very strong 8, benign evidence negative. 10 or more is pathogenic, 6 to 9 likely pathogenic, 0 to 5 uncertain significance, -1 to -6 likely benign, -7 or less benign. BA1 is benign on its own.
4. **Store the run** (`curate.py`) in the `curation` schema: every assessment with its evidence, the criteria met and not assessed (each with its reason), the points, and the class; and on the run, every source and version (gnomAD dataset, Ensembl release, ClinVar release, each panel's CSpec version, a hash of `rules.yaml`, the git commit).

## Run it

```bash
uv run python scripts/curate_variants.py --set panel   # the clinical panel's 48 variants
uv run python scripts/curate_variants.py --set eval    # ClinVar expert-panel variants, scored
```

`uv run python scripts/import_enigma_pvs1.py` refreshes ENIGMA's table when the panel releases a new version. Both curation runs read positions and alleles only. gnomAD, VEP, and exon answers are cached under `data/reference/` per release, so reruns make no requests. The first eval run asks gnomAD about several hundred variants at gnomAD's limit of 10 requests a minute, about 10 minutes.

## Results

2026-11-19; ClinVar 2026-11-15, gnomAD v4, Ensembl 116.

**The clinical panel.** 47 of the 48 planted variants land in the class their ClinVar record would put them in: all 18 pathogenic (8 pathogenic, 10 likely pathogenic), all 18 benign, and 11 of 12 uncertain. The other, LDLR p.Arg814Gln, uncertain in ClinVar (expert panel), comes out likely benign: its gnomAD v4 FAF95 is 0.36% in the African ancestry group, above the panel's BS1 threshold of 0.2%. The panel's classification may predate gnomAD v4; it is a real disagreement, for a curator to settle.

**Against ClinVar expert panels.** 578 variants with three ClinVar stars in the six genes, up to 20 per gene and class, sampled with a fixed seed. The rules never read the classification.

| Expert panel (rows), rules (columns) | P/LP | VUS | B/LB |
|---|---|---|---|
| Pathogenic or likely pathogenic | 120 | 120 | 0 |
| Uncertain significance | 2 | 110 | 4 |
| Benign or likely benign | 0 | 81 | 141 |

Agreement is 64.2% overall, from 48% (LDLR) to 74% (MSH2), with no reversals. The number to read first is how often a decision is right when the rules make one: 120 of 122 pathogenic or likely pathogenic calls (98%) and 141 of 145 benign or likely benign calls (97%). Most of the rest is evidence data alone cannot reach:

- Pathogenic variants called uncertain (120): 81 missense, which need functional, case, or segregation evidence (the literature step); 21 splice-region variants outside the canonical ±1, ±2 sites; 17 truncations or splice sites the rules leave to the curator (MSH2 7, APC 6, LDLR 3, MLH1 1); 1 in-frame deletion. One BRCA2 variant is pathogenic to ENIGMA though its own Table 4 rules PVS1 out for it, so its classification rests on other evidence.
- Benign variants called uncertain (81): 49 synonymous and 23 missense. Synonymous variants are usually benign by BP7, which needs a splicing prediction; gnomAD's SpliceAI scores are licensed for non-commercial use only and are not used here.

**Where the rules and the panels differ.** Two variants the panels call uncertain come out pathogenic, both by the panels' own rules: BRCA2 p.Glu3309Ter, the last codon before ENIGMA's cut-off at 3310, gets PVS1 and PM5_PTC from Table 4; MLH1 p.Tyr750Ter falls inside InSiGHT's PVS1 cut-off at codon 753. The panels' classifications must rest on evidence beyond these rules.

**What the panel tables changed.** Before them, PVS1 followed only the NMD rule. The pathogenic calls agreed with the panels 114 of 124 times (92%), with ten over-calls and one reversal. Over-calls are the costlier error. ENIGMA's table removed all seven in BRCA1 and BRCA2: exon 9 truncations rescued by a natural isoform, splice sites it rates supporting or not applicable, and a deletion it does not list, now left to the curator. APC's codon boundaries removed the two at codons 12 and 24. The table added one, p.Glu3309Ter, which the NMD rule had left to the curator. And its last-exon rule turned the reversal, a BRCA2 frameshift in exon 27, from likely benign to likely pathogenic, as ENIGMA has it.

## Limits

- Only the criteria data alone decides. Missense variants, which need functional studies, case data, or segregation, come out uncertain until the literature step (C2).
- PS1 and PM5 (the same or a nearby amino acid change as a known pathogenic variant) are not applied yet: each panel sets its own strengths for them.
- PVS1 follows each panel only as far as data allows. For LDLR, MLH1, and MSH2 splice sites it does not check whether a stop falls in the last 50 nucleotides of the penultimate exon (which also escapes NMD), or a panel's list of critical domains. APC splice sites, initiation codon variants, and exon-level deletions and duplications are left to the curator. ENIGMA's RNA-based codes ("PVS1 (RNA)") are applied at the table's strength without re-reading the RNA data.
- Thresholds are read on gnomAD v4 joined. ENIGMA's are defined on gnomAD v2.1 and v3.1 non-cancer subsets, and PM2 for BRCA1 and BRCA2 also requires read depth of at least 25, not checked. Founder variants, which InSiGHT excludes from BA1 and BS1, are not excepted.
- This tool includes data from the gnomAD v4 release. For research and demonstration; not for clinical use.
