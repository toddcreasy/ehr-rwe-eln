# NIST AI RMF mapping

How this repository's practices line up with the NIST AI Risk Management Framework (AI RMF 1.0, 2023), and where they fall short. Category names are quoted from NIST's AI RMF Core at airc.nist.gov; NIST notes that a revision of the framework is in progress, so this maps to 1.0.

The framework has four functions. **Govern** sets the policies and culture for managing AI risk. **Map** establishes context and identifies risks. **Measure** analyzes and tracks them. **Manage** acts on them. Each function has numbered categories (GOVERN 1, MAP 3, and so on), used below.

Scope: the parts of this repository that are AI systems. The tables below cover the first two in depth; the other two are in the rows where they differ.

- **Synthetic data releases** (`src/ehr_rwe_eln/synth/`): differentially private synthesizers (a Bayesian network, a variational autoencoder, MST, and AIM) that produce synthetic copies of the [OMOP](https://ohdsi.github.io/CommonDataModel/cdm54.html) data for testing other systems. Method and results: [synthetic_data_methodology.md](synthetic_data_methodology.md).
- **ELN extraction** (`src/ehr_rwe_eln/eln/`): Claude (`MODEL`, Opus 4.6 on Amazon Bedrock) extracting samples and results from lab notebook text into typed records.
- **The agent** (`POST /api/agent`, `src/ehr_rwe_eln/agents/`): Claude answering questions on the public demo with four read-only tools over precomputed OMOP counts (counts under 11 suppressed) and the newest results.
- **Literature proposals** (`src/ehr_rwe_eln/curation/literature.py`, `literature_graph.py`): Claude proposing ACMG criteria from papers, each claim's PMID and quote verified in code; proposals change no class until a curator accepts them.

This is a single-maintainer project on synthetic data. Some categories are about organizations (roles, workforce, outside stakeholders); for those, the mapping says what exists and what an organization would add.

## Govern

| Category | In place | Gap |
|---|---|---|
| GOVERN 1: policies, processes, procedures, and practices | Written data rules (`CLAUDE.md`): synthetic or openly licensed data only, no patient-level data or vocabularies committed, no clinical claims, every LLM extraction validated against a typed model and scored. Synthesis rules enforced in code: domains fixed in the spec, seeds only for synthetic sources, budgets enforced by an accountant. | No written policy for choosing epsilon on a real source. |
| GOVERN 2: accountability structures | Every change goes through a pull request that the maintainer approves; branch protection requires the `lint-test`, `secrets`, and `terraform` checks. | One person holds every role. An organization would separate who builds, who reviews releases, and who approves sharing. |
| GOVERN 3: workforce diversity, equity, inclusion, and accessibility | Not applicable to a one-person project. | An organization would document who took part in mapping and measuring risk. |
| GOVERN 4: a culture that considers and communicates AI risk | Negative findings are reported as plainly as positive ones: the VAE's weak fidelity, spurious trial effects in up to 45% of draws, the eval that caught two prompt gaps. The frontend shows a synthetic-data, no-clinical-use disclaimer (`frontend/app/disclaimer.tsx`). | None specific. |
| GOVERN 5: engagement with relevant AI actors | The methodology document and data cards are written for a Data Access Committee. | No outside reviewer has seen them. Engagement would mean a real DAC review and red-team exercise. |
| GOVERN 6: third-party software and data | Dependencies locked in `uv.lock`. [scikit-learn](https://scikit-learn.org) held below 1.9 because [diffprivlib](https://github.com/IBM/differential-privacy-library) uses its private names. VAE releases without a seed are refused, because the secure-noise package [Opacus](https://opacus.ai) needs (`torchcsprng`) cannot be installed. [OHDSI](https://www.ohdsi.org) vocabularies used under their licenses, never committed. Model IDs fixed in settings and checked by evals before a change. | No automated dependency vulnerability scanning. |

## Map

| Category | In place | Gap |
|---|---|---|
| MAP 1: context established and understood | Purpose, users, and setting are written down: synthetic test and development data so teams can build and red-team systems without the source; a public demo on AWS with no real data (methodology sections 1 and 2). | None for this setting. |
| MAP 2: categorization of the AI system | Synthesizers categorized by method (statistical, generative, baseline) in each release record and card. ELN extraction categorized as structured extraction with Claude Opus 4.6; the agent as tool use over read-only, precomputed counts; literature proposals as extraction with verified citations, advisory only. | None. |
| MAP 3: capabilities, goals, benefits, and costs compared with benchmarks | Every synthetic release is read against benchmarks from real data: a real-against-real noise floor, a model trained on real data (TRTR AUC 0.804), and the real trial hazard ratio (0.97). ELN extraction has a 0.95 precision and recall bar. | None. |
| MAP 4: risks and benefits mapped for all components, including third-party | Component risks found and recorded: diffprivlib's zero-truncated noise inflates sparse counts (70 events against 26); Opacus's default accountant warned of divergent integration, so the RDP accountant is used; the LLM missed replicate and dilution rules until the hard eval caught them; prompt injections that asked it to add a fabricated sample worked on 6 of 11 entries until the prompt said entry text is data, never instructions. | None found unrecorded. |
| MAP 5: impacts on individuals, groups, communities, organizations, and society | Threat model for individuals: membership, attribute, and identity disclosure (methodology section 2). Impact of misuse: synthetic trial tables produce effects that are not there, so cards forbid reporting estimates from them. | Impact on groups measured by race, ethnicity, sex, age, and their pairs; three-way intersections not measured (see MEASURE 2, fair). |

## Measure

| Category | In place | Gap |
|---|---|---|
| MEASURE 1: appropriate methods and metrics identified and applied | Fidelity (total variation distance per column and pair, KS, correlation gap), utility (train on synthetic, test on real), trial parity over 20 draws, three privacy attacks, quasi-identifier uniqueness; ELN precision and recall per trap. Each metric defined in its module and in the methodology. | None. |
| MEASURE 2: evaluated for trustworthy characteristics | See the table below. | Fairness across three-way intersections; the VAE's distortion of older people. |
| MEASURE 3: tracking identified risks over time | Every release and every report records the code version it came from; data cards are regenerated from them. The data quality module keeps every run. | `synth.report` keeps only the latest report per release and kind; history is in git, not the database. Scheduled privacy checks keep a row per run (`synth.monitor_run`), but not the reports they replace. |
| MEASURE 4: feedback about the efficacy of measurement | The measurements are themselves checked: the noise floor and the copy of the training data show what the metrics read at their limits; the independent-columns baseline must score as useless and does (AUC 0.465); tests confirm a shuffled relationship is caught and a copy leaks. A weak copy result led to adding the uniqueness metric, which explained it. | None. |

Trustworthy characteristics (MEASURE 2):

| Characteristic | Evidence | Gap |
|---|---|---|
| Valid and reliable | Fidelity, utility, and trial parity per release; parity judged over repeated draws because one draw is unreliable on 26 events. ELN extraction scored at precision and recall 1.000 on default and hard sets, with the hard set's two misses fixed and confirmed on unseen seeds. | Synthesis checked on one source and one trial. |
| Safe | No clinical claims in code, docs, or UI; cards state intended use and, for trial tables, the measured rate of spurious effects. | None. |
| Secure and resilient | ELN extraction resists prompt injection: adversarial entries asking it to add a fabricated sample, change a value, or return nothing score precision and recall 1.000, including on a seed the defense was not written against. Differential privacy with enforced budgets; secure noise required off synthetic sources. Claude reached with IAM credentials, so there is no API key; database passwords managed in Secrets Manager. The public agent is bounded: a Bedrock Guardrail on every call, a daily token limit, 10 calls an hour per address, and alarms on token use, errors, and Guardrail interventions; curator decisions are off in the demo. | No sign-in, by design for a public demo on synthetic data, bounded by the limits instead; a deployment on real data would need it. |
| Accountable and transparent | Provenance per release (spec as run, spend per mechanism, source, counts, seed, code version); data cards; methodology; PR history. | None. |
| Explainable and interpretable | The Bayesian network's structure is declared and printed on each card; each privacy report has a plain-language summary. | The VAE is not interpretable beyond its metrics. |
| Privacy-enhanced | DP at epsilon 1 to 4 on the person summary; all three attacks at chance on every release. | No location in the source, so linkage risk is understated. |
| Fair, with harmful bias managed | Fidelity and utility within each race, ethnicity, sex, and age group, and within each cell of age by race, age by sex, and race by sex, each read against its own noise floor (methodology section 5). The Bayesian network at epsilon 4 keeps every reported cell within 0.028 of its floor, but draws race independently of age, so older Black people appear at twice their real share. The VAE, conditional on age, now has every age band within 11% of its real share, but people 80 and over are still far from real in their other columns. Each data card names any group whose share is off by more than 20% and says not to study it in that release. | Three-way intersections are not measured; cells under 11 people are listed without numbers. The VAE's older people are reported, not fixed: the methodology says to use the Bayesian network for them. |

## Manage

| Category | In place | Gap |
|---|---|---|
| MANAGE 1: risks prioritized and responded to | Findings become tracked items: give the trial outcome a confounder as a parent, load location for linkage testing, tune the VAE on a public stand-in. | Prioritization is informal (a TODO list), not a risk register. |
| MANAGE 2: strategies to maximize benefits and minimize negative impacts | Intended-use limits on every card; warnings where trial parity found spurious effects; a holdout kept out of every release; budgets enforced in code; unsafe configurations refused (unseeded VAE). | None. |
| MANAGE 3: third-party risks and benefits | Version constraints and lockfile; the accountant switched after a numerical warning; model changes gated by evals. | No scanning or alerting on new dependency advisories. |
| MANAGE 4: risk treatments, response and recovery, and communication | Data cards and the methodology communicate risk to reviewers. Every export is recorded with its recipient and purpose; a withdrawal marks the release, stops further exports, rewrites its card, and drafts a notice for each recipient (methodology section 6); each recipient's confirmed deletion is recorded, and those who have not confirmed are listed. Each evaluation run, and a scheduled check every day (a Fargate task at 11:00 UTC) when a source or the code changed, lists releases whose privacy checks drift past halfway to a copy of the training data. | Notices are drafted, not sent, and recipients who have not confirmed deletion are listed but not chased. Scheduled checks flag drift on the `/synth/` page and in the logs; no alarm or email goes out on a flag. |

## Gaps, in order of importance

1. The VAE's older people (the right number, but not realistic past 80); age and race unlinked in the Bayesian network's structure (linking them was tested and hurt the smallest races at epsilon 1); three-way intersections (MEASURE 2).
2. Location in the source, so the linkage attack reflects real risk (MEASURE 2, privacy-enhanced).
3. Report history in the database, not only the latest report (MEASURE 3).
4. Alerts that reach someone off the machine, for privacy drift and for recipients who have not confirmed deletion (MANAGE 4).
5. Outside review by a DAC or red team (GOVERN 5), and separated roles (GOVERN 2), for any use beyond this project.
6. A written policy for choosing epsilon on real data (GOVERN 1) and dependency advisory scanning (GOVERN 6, MANAGE 3).
