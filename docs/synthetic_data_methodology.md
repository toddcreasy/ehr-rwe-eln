# Synthetic data releases: methodology

How this repository makes differentially private synthetic copies of an [OMOP](https://ohdsi.github.io/CommonDataModel/cdm54.html) database, how it checks them, and what the checks found. Written for a reviewer such as a Data Access Committee (DAC): someone who decides whether a dataset may be shared and needs to know what it protects, what it costs in accuracy, and what it should not be used for.

The source here is [Synthea](https://github.com/synthetichealth/synthea) output, not real patients. It stands in for a controlled-access source so the whole process can be run and inspected in the open. The methods carry over to real data; the numbers describe this source only. Code: `src/ehr_rwe_eln/synth/`. Every figure below comes from the reports stored in the `synth.report` table of the 23,421-patient build and from the per-release data cards (`scripts/synth_cards.py`).

## 1. What is released

Two kinds of table, each defined by a YAML spec in `src/ehr_rwe_eln/synth/specs/`.

- **Person summary** (`person_summary.yaml`): one row per person, 21 columns. Age at the end of observation, sex, race, ethnicity; whether each of eight conditions and four drugs was ever recorded; the latest of four measurements (systolic blood pressure, BMI, eGFR, HbA1c); and death. 23,421 people.
- **Trial table** (`trial_lisinopril_amlodipine_ckd.yaml`): the analysis table of the trial emulation module's target trial of lisinopril against amlodipine, with chronic kidney disease stage 3 or worse as the outcome. One row per eligible person: treatment arm, age, sex, six condition and four measurement covariates, follow-up days, and outcome. 1,890 people, 26 outcome events.

Neither table carries a direct identifier. `person_id` is used to build and split the source and never reaches a synthesizer. Dates are not released; ages and follow-up lengths are.

## 2. What it protects against

The unit of privacy is one person: one row of the source. The question differential privacy answers is how much the release could differ if any one person's row were added or removed.

The attacker has the full synthetic release and the spec, and may hold auxiliary data about a real person: their full record, or only their quasi-identifiers (age, sex, race, ethnicity: fields that are not identifying alone but can be in combination). The attacker wants to learn:

- **Membership**: whether a given person was in the source. Being in a disease cohort can itself be sensitive.
- **Attributes**: a person's conditions, drugs, measurements, or death, from what they already know.
- **Identity**: which synthetic row, if any, is a near-copy of a real person.

Synthetic rows are not real people, so a match between a synthetic row and a real one is not by itself a disclosure. The risk is that the synthesizer copied or memorized real rows, or that the release lets someone infer something about a specific person that they could not infer from population-level patterns.

## 3. How privacy is enforced

**Differential privacy (DP).** A mechanism is epsilon-differentially private if, for any two sources that differ by one person, the probability of any output changes by at most a factor of e^epsilon. Smaller epsilon means more noise and stronger protection. Spending privacy more than once adds up: running mechanisms with epsilon 1 and epsilon 2 on the same people costs epsilon 3 (sequential composition). Anything computed only from a DP output costs nothing more (post-processing).

**Fixed domains.** Every category list and every numeric range and bin is written in the spec before the data is read. A range taken from the data would leak on its own: the top bin edge would be the oldest person's age. Values outside a range are clamped into its end bins. Age's last bin is open: it means 90 or older and decodes to 90, never to an age inside it, as HIPAA [Safe Harbor](https://www.hhs.gov/hipaa/for-professionals/special-topics/de-identification/index.html) requires.

**Declared structure.** For the Bayesian network, each column's parents (the columns its distribution is measured against) are declared in the spec from domain knowledge, so choosing the structure costs no privacy. Example: lisinopril depends on hypertension; diabetes on age and obesity; in the trial table, treatment on diabetes and early kidney disease, following public prescribing guidance.

**Bayesian network synthesizer** (`synth/bayes_net.py`). One histogram per column over the column and its parents. Each count gets noise from the truncated geometric mechanism (integer noise, the discrete form of the Laplace mechanism) through IBM's [diffprivlib](https://github.com/IBM/differential-privacy-library). Adding or removing one person changes one cell of each histogram by 1, so the sensitivity is 1. Every histogram counts every person, so the release's epsilon is split evenly across the histograms (21 for the person summary, 15 for the trial table), and diffprivlib's budget accountant refuses any spend beyond it. Each share is reduced by one part in a trillion so that floating-point rounding can only underspend. New rows are sampled from the noisy counts alone. The row count is the noisy total of the first histogram, not the true count.

**Variational autoencoder (VAE)** (`synth/vae.py`). A neural network that compresses each row to 16 numbers and rebuilds it, trained with DP-SGD through Meta's [Opacus](https://opacus.ai). Each training step clips every person's gradient to length 1 and adds Gaussian noise; Opacus chooses the noise for the target epsilon over the planned steps. The guarantee is (epsilon, delta)-DP: delta is a small probability that the guarantee does not hold, set to 1e-5, well under one over the number of people. Privacy is tracked with the Rényi DP (RDP) accountant, whose epsilon is a guaranteed upper bound; Opacus's default accountant warned that its numerical integration was divergent on this data. One percent of epsilon buys a noisy row count. Training settings are fixed in the spec, not tuned on the source: every training run on private data spends privacy, tuning runs included.

**Randomness.** The specs here are seeded so that each release can be remade exactly. That is acceptable only because the source is synthetic: anyone who knows the seed can regenerate the noise and subtract it. A spec over real data must set `seed: null`, which makes diffprivlib draw from a cryptographically secure generator. The VAE would need Opacus's secure mode, which depends on the `torchcsprng` package; its last release (2021) supports only torch 1.8 and Python up to 3.9, so it cannot be installed on this stack. The spec therefore refuses VAE releases without a seed: on real data, only the Bayesian network can be used here.

**What is not covered by DP.** The evaluation reports in sections 4 and 5 are computed on the source and are not differentially private. They are for reviewers and stay internal. The holdout split is by a hash of `person_id`, which is not sensitive.

## 4. How releases are checked

**Holdout.** For the person summary, 30% of people are held out of every release (chosen by a hash of the spec name and `person_id`, so the same person always lands on the same side). They are the real test set for utility and the non-members for the privacy attacks. The trial table keeps no holdout: its parity check compares against the data the synthesizer learned from, and holding out 30% would remove about 8 of its 26 events.

**Fidelity** (`synth/fidelity.py`), on the spec's encoding:

- Total variation distance (TVD) per column and per pair of columns (all 210 pairs). 0 means identical distributions, 1 means no overlap. Pairs show whether relationships survived, including ones the synthesizer was not told about.
- Kolmogorov-Smirnov statistic for numeric columns.
- Correlation gap: mean absolute difference between the two Pearson correlation matrices.
- Read against a **noise floor**: the same measures between two real samples (holdout against training). No release can be expected to beat it.

**Utility.** Train on synthetic, test on real (TSTR): a logistic regression predicting death, trained on the release and scored on held-out real people by AUC (the chance that a random person who died ranks above one who did not; 0.5 is guessing). Compared with the same model trained on real data (TRTR).

**Downstream parity** (`synth/parity.py`). The trial's own propensity-weighted Cox analysis from the trial emulation module, unchanged, run on the real trial table and on synthetic ones. One synthetic draw varies like a fresh small sample, so each method and epsilon is redrawn 20 more times with different seeds. Reported: share estimable, share whose 95% interval covers the real hazard ratio, and share showing a spurious effect (an interval excluding 1 when the real interval includes it).

**Privacy attacks** (`synth/privacy.py`). Each compares members (training people) with non-members (held-out people), because what an attacker learns equally about both is population knowledge, which is the purpose of a release.

- Distance to closest record: for 2,000 synthetic rows, is the nearest real record a member or a non-member? 50% means no sign of copying.
- Membership inference: an attacker scores how close a real record sits to the release and guesses that close means member. AUC over 2,000 members and 2,000 non-members; 0.5 is a coin flip.
- Attribute inference: from age group, sex, race, and ethnicity, guess each sensitive flag as the most common value among matching synthetic rows. The leak is how much more accurate this is for members.
- Quasi-identifier uniqueness of the source: the share of people who are the only one with their combination.
- All read against the same attacks on a **plain copy of the training data**, which shows what real leakage looks like.

A failed attack shows only that this attack failed. These checks bound risk from below; differential privacy is the guarantee.

## 5. Results

### Person summary (16,385 training people, 7,036 held out)

| Release | Column TVD mean | Pair TVD mean | Worst pair (TVD) | Correlation gap | TSTR AUC |
|---|---|---|---|---|---|
| Noise floor (real against real) | 0.006 | 0.012 | 0.050 | 0.015 | 0.804 (TRTR) |
| Independent columns, epsilon 1 | 0.005 | 0.071 | age x BMI (0.333) | 0.232 | 0.497 |
| Bayesian network, epsilon 0.25 | 0.015 | 0.049 | age x BMI (0.258) | 0.099 | 0.689 |
| Bayesian network, epsilon 1 | 0.006 | 0.035 | age x BMI (0.247) | 0.084 | 0.698 |
| Bayesian network, epsilon 4 | 0.004 | 0.032 | age x BMI (0.244) | 0.079 | 0.686 |
| VAE, epsilon 1 | 0.038 | 0.073 | age x BMI (0.386) | 0.210 | 0.730 |
| VAE, epsilon 4 | 0.046 | 0.077 | age x BMI (0.270) | 0.128 | 0.724 |

- The Bayesian network matches single columns at the noise floor from epsilon 1 up. Relationships fall short of the floor at every epsilon.
- The worst pair in every release is age x BMI. The spec makes BMI depend only on obesity, and the source includes children, whose BMI depends strongly on age. A declared structure keeps only what it declares.
- The VAE matches single columns worse (DP noise on 63,100 network weights trained from 16,385 people) but predicts death better, because in the Bayesian network death depends on age alone.
- The independent-columns baseline keeps every column and loses every relationship, and predicts death no better than guessing: the checks can tell a useless release from a useful one.

| Release | Nearer a member | Exact match, member / non-member | Membership AUC | Attribute gap, mean / max |
|---|---|---|---|---|
| Copy of the training data | 62.9% | 68.7% / 44.4% | 0.650 | +0.5% / +1.6% |
| Independent columns, epsilon 1 | 50.0% | 2.0% / 2.1% | 0.512 | +0.2% / +1.2% |
| Bayesian network, epsilon 0.25 | 50.8% | 17.4% / 17.5% | 0.504 | +0.1% / +1.1% |
| Bayesian network, epsilon 1 | 51.0% | 19.2% / 18.9% | 0.507 | +0.1% / +1.4% |
| Bayesian network, epsilon 4 | 50.1% | 20.8% / 21.3% | 0.500 | +0.2% / +1.3% |
| VAE, epsilon 1 | 50.9% | 9.4% / 8.8% | 0.509 | +0.2% / +1.2% |
| VAE, epsilon 4 | 50.4% | 19.6% / 19.5% | 0.506 | +0.2% / +1.3% |

- Every release is at chance on every attack; the copy shows the attacks detect leakage when it exists.
- The copy's own numbers are modest because the encoding is coarse: 44% of held-out people have an exact twin among training people on all 21 binned columns. In the source, 2.4% of people are unique on exact age, sex, race, and ethnicity, and 0.2% with age in ten-year groups (the last one 90 or older). With these quasi-identifiers, a linkage attack has almost no one to single out.

### Trial table (1,890 people, 26 events)

The real analysis gives a weighted hazard ratio of 0.97 (95% CI 0.42 to 2.26) for lisinopril against amlodipine, and a crude (unweighted) hazard ratio of 1.22.

| Release | Events | Release HR (95% CI) | Estimable | Covers real HR | Spurious effect | Median HR, 20 draws |
|---|---|---|---|---|---|---|
| Bayesian network, epsilon 1 | 118 | 5.47 (2.85 to 10.52) | 100% | 50% | 55% | 0.75 |
| Bayesian network, epsilon 4 | 46 | 12.22 (2.96 to 50.40) | 95% | 75% | 20% | 0.86 |
| Bayesian network, epsilon 16 | 35 | 4.38 (1.55 to 12.37) | 100% | 95% | 5% | 1.21 |
| Bayesian network, epsilon 1000 (no real privacy) | 26 | 0.63 (0.29 to 1.37) | 100% | 95% | 0% | 1.59 |
| VAE, epsilon 4 | 27 | 1.62 (0.69 to 3.81) | 100% | 100% | 0% | 1.08 |

- With 26 events, DP synthetic tables give confident wrong answers often: more than half of the draws at epsilon 1, and 20% at epsilon 4, show an effect the real data does not.
- Noise is clipped at zero, which can only raise sparse counts: the epsilon 1 release has 118 events against 26 real ones.
- The VAE does best: every draw covers the real hazard ratio and none shows a spurious effect.
- A single release is not enough to judge a method on a cohort this small. The stored epsilon 4 release gives a hazard ratio of 12.22, though 75% of draws at that setting cover the real one.
- Without real privacy (epsilon 1000), the Bayesian network's median drifts above 1. The spec makes the outcome depend only on arm and follow-up, so propensity weighting has nothing to adjust and the synthetic estimate follows the crude association. This is a structure limit, not a privacy one.

## 6. Recommended use

- Releases like these are fit for building, testing, and demonstrating analyses and pipelines without access to the source: schemas, code paths, and failure modes behave as they would on the real data.
- They are not fit for reporting estimates. On small cohorts with rare outcomes, they produce effects that are not there, at rates measured above.
- Each release's data card states its intended use and, for trial tables, the measured rate of spurious effects at its setting.
- For a real source, choose epsilon before looking at results, leave seeds unset, and treat the evaluation reports as internal.

## 7. Limitations

- Synthea output is cleaner and more regular than real records. Fidelity and attack results on real data will differ.
- The source has no location (the cohort pipeline's ETL does not load addresses), the strongest quasi-identifier for linkage. The attribute inference attack is weaker than a real one would be.
- The attacks are simple. Stronger ones (for example, density-based membership inference that uses reference data) might do better.
- The Bayesian network keeps only declared relationships, with at most two parents per column.
- The VAE's training settings were not tuned. Tuning on a separate public stand-in would likely improve it.
- On real data only the Bayesian network can run here: the VAE needs a seed, because secure noise for it is not installable (section 3).
- Fidelity is not yet measured by subgroup. DP noise is the same size for every count, so small groups (99 people of 23,421 are recorded as Native American) are distorted most.
- One spec per table kind and one trial protocol; results on other cohorts will differ.

## 8. Reproducing and provenance

```bash
uv run python scripts/synthesize.py
uv run python scripts/synthesize.py --spec src/ehr_rwe_eln/synth/specs/trial_lisinopril_amlodipine_ckd.yaml
uv run python scripts/evaluate_synth.py
uv run python scripts/synth_cards.py
```

Each release in `synth.release` records the spec as run, every mechanism's privacy spend, the source database, the training and holdout counts, the seed, and the git version of the code. Each report in `synth.report` records its own code version. The data cards in `data/synth/cards/` are rendered from those two tables only.
