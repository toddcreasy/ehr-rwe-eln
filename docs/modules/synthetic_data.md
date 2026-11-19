# Privacy-preserving synthetic data

Package: `ehr_rwe_eln.synth`. Back to the [README](../../README.md). Terms are defined in the [glossary](../GLOSSARY.md).

Treats the [OMOP](https://ohdsi.github.io/CommonDataModel/cdm54.html) build as if it were a controlled-access source, such as a [dbGaP](https://www.ncbi.nlm.nih.gov/gap/) study, and releases synthetic copies of it under differential privacy (DP), so they can be shared and built against without exposing the people in it. Each release comes with fidelity, utility, and privacy risk reports, and a data card.

The full method, threat model, and results for reviewers are in [synthetic_data_methodology.md](../synthetic_data_methodology.md). This page is the overview.

## What it does

A release spec in YAML (`specs/`) names the source table's columns, each column's domain, and the releases to make. Domains are fixed in the spec, never read from the data: a range taken from the data would leak on its own, since the top edge would be the oldest person's age.

Three synthesizers:

- **Bayesian network** (`bayes_net.py`), on [diffprivlib](https://github.com/IBM/differential-privacy-library). Each column gets a noisy histogram with its declared parents, the privacy budget (epsilon) is split across the histograms, and a budget accountant refuses to overspend. Rows are sampled from the noisy counts.
- **Variational autoencoder** (VAE, `vae.py`), a small neural network trained with DP-SGD (differentially private stochastic gradient descent) through [Opacus](https://opacus.ai), on the same encoding.
- **Independent columns**, a baseline that keeps each column and loses every relationship between them. A release that scores like this one is useless, which the reports have to be able to show.

Epsilon bounds how much any one person can change what is released. Smaller is more private and noisier.

Every release is stored in the `synth` schema with its provenance: the spec as run, each mechanism's privacy spend, the source, the seed, and the code version. 30% of people are held out of every release to evaluate against.

## Two specs

| Spec | Source | Judged by |
|---|---|---|
| `person_summary.yaml` | One row per person: demographics, eight conditions, four drugs, four measurements, death. 23,421 people | Fidelity and utility against the held-out people, and privacy attacks |
| `trial_lisinopril_amlodipine_ckd.yaml` | The trial emulation module's analysis table for lisinopril against amlodipine. 1,890 people, 26 events | Rerunning the trial on each release and comparing the hazard ratio with the real one |

Ages are released in ten-year bins, the last one "90 or older," as HIPAA [Safe Harbor](https://www.hhs.gov/hipaa/for-professionals/special-topics/de-identification/index.html) allows. Each spec must state the source's data use limitations, the consent terms a release from a real study inherits, and every data card prints them.

## Reports

- **Fidelity**: total variation distance (TVD) per column and per pair of columns, read against a noise floor (the same measure between two real samples). Also within each race, ethnicity, sex, and age group, against that group's own floor.
- **Utility**: a model trained on the release and tested on held-out real people (TSTR), against one trained on real data.
- **Trial parity**: the trial emulation module's own analysis on each release, over 20 more draws, counting how often the interval covers the real hazard ratio and how often it shows an effect the real data does not.
- **Privacy risk**: distance to closest record, a membership inference attack, and attribute inference, each comparing training people with held-out people, against the same attacks on a plain copy of the training data.

The reports read real data, so they are for internal review, not for release.

## Run it

```bash
export SPEC=src/ehr_rwe_eln/synth/specs/trial_lisinopril_amlodipine_ckd.yaml
uv run python scripts/synthesize.py
uv run python scripts/synthesize.py --spec $SPEC
uv run python scripts/evaluate_synth.py
uv run python scripts/synth_cards.py
```

Synthesis takes under a minute and evaluation about a minute. Data cards go to `data/synth/cards/`. The page at http://127.0.0.1:8000/synth/ compares the releases and shows each card.

## Results in brief

From the [methodology](../synthetic_data_methodology.md#5-results):

- The Bayesian network matches single columns at the noise floor from epsilon 1 up. Relationships between columns fall short of it at every epsilon.
- By subgroup, age is where releases fall short: the VAE has 19 to 28% too few people aged 70 and over and distorts them most. Each data card names any group a release misrepresents.
- Every release is at chance on every privacy attack; the plain copy of the training data is not, which shows the attacks detect leakage when it exists.
- On the 26-event trial, DP releases often give confident wrong answers: 55% of draws at epsilon 1 and 20% at epsilon 4 show an effect the real data does not. These releases are fit for building and testing pipelines, not for reporting estimates.

## For reviewers

- [Methodology](../synthetic_data_methodology.md): threat model, mechanisms, evaluation, results, recommended use, limits.
- [NIST AI RMF mapping](../nist_ai_rmf.md): the work against the NIST AI Risk Management Framework, with its gaps.
- [NIH and HHS requirements](../nih_hhs_requirements.md): what a real controlled-access source would require (the Genomic Data Sharing Policy, NIST SP 800-171, HIPAA de-identification) and how far the repository goes.
