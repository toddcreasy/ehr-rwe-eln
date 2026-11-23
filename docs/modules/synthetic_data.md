# Privacy-preserving synthetic data

Package: `ehr_rwe_eln.synth`. Back to the [README](../../README.md). Terms are defined in the [glossary](../GLOSSARY.md).

Treats the [OMOP](https://ohdsi.github.io/CommonDataModel/cdm54.html) build as if it were a controlled-access source, such as a [dbGaP](https://www.ncbi.nlm.nih.gov/gap/) study, and releases synthetic copies of it under differential privacy (DP), so they can be shared and built against without exposing the people in it. Each release comes with fidelity, utility, and privacy risk reports, and a data card.

The full method, threat model, and results for reviewers are in [synthetic_data_methodology.md](../synthetic_data_methodology.md). This page is the overview.

## What it does

A release spec in YAML (`specs/`) names the source table's columns, each column's domain, and the releases to make. Domains are fixed in the spec, never read from the data: a range taken from the data would leak on its own, since the top edge would be the oldest person's age.

Five synthesizers:

- **Bayesian network** (`bayes_net.py`), on [diffprivlib](https://github.com/IBM/differential-privacy-library). Each column gets a noisy histogram with its declared parents, the privacy budget (epsilon) is split across the histograms, and a budget accountant refuses to overspend. Rows are sampled from the noisy counts.
- **Variational autoencoder** (VAE, `vae.py`), a small neural network trained with DP-SGD (differentially private stochastic gradient descent) through [Opacus](https://opacus.ai), on the same encoding.
- **MST** (`mst.py`), the winning method of the 2018 NIST contest, on its authors' `mbi` library. It measures every column's histogram, chooses a tree of column pairs with privacy noise, measures those, and samples from a graphical model fitted to them. Same encoding as the Bayesian network.
- **AIM** (`aim.py`), MST's successor from the same group, also on `mbi`. It is given a workload, the marginals the trial and cohort analyses read, and spends its budget in rounds, each measuring the marginal the current model fits worst.
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

Releases are made and evaluated on AWS: `scripts/run_synth.py` runs either script at the current commit as a Fargate task, which reads OMOP from the lake through Redshift and writes releases and reports to Aurora (see [Synthetic releases on AWS](../../infra/terraform/README.md#synthetic-releases-on-aws)). Run locally, the same scripts read the lake (or the staging Postgres with `OMOP_SOURCE=staging`, see [Who reads the lake](cohort.md#who-reads-the-lake)) and write to the Compose Postgres; keep that to the tests and small specs, since MST, AIM, and the trial redraws take minutes to hours of several cores.

```bash
export SPEC=src/ehr_rwe_eln/synth/specs/trial_lisinopril_amlodipine_ckd.yaml
uv run python scripts/run_synth.py synthesize.py
uv run python scripts/run_synth.py synthesize.py --spec $SPEC --method mst
uv run python scripts/run_synth.py evaluate_synth.py
uv run python scripts/synth_cards.py

# Hand a release to someone, and withdraw one later
uv run python scripts/export_release.py --release 3 --recipient "Pipeline team" --contact team@example.org --purpose "testing the cohort pipeline"
uv run python scripts/withdraw_release.py --release 3 --reason "what is wrong with it"
uv run python scripts/confirm_deletion.py --export 7 --evidence "Dana's reply, 2026-11-20"
```

Exports go to `data/synth/exports/` with the release's data card, and each is recorded with its recipient. A withdrawal marks the release, stops further exports, rewrites its card, and drafts a notice per recipient in `data/synth/withdrawals/` for you to send. Record each recipient's reply that they deleted it with `scripts/confirm_deletion.py`; with no arguments it lists who has not replied. Each evaluation run lists any release whose privacy checks have drifted toward leakage, and the Compose `monitor` service runs that check every 24 hours when a source or the synth code has changed; the `/synth/` page shows the last check.

Synthesis takes under a minute and evaluation about a minute. Data cards go to `data/synth/cards/`. The page at http://127.0.0.1:8000/synth/ compares the releases and shows each card.

## Results in brief

From the [methodology](../synthetic_data_methodology.md#5-results):

- The Bayesian network at epsilon 4 matches single columns at the noise floor, and every age, sex, and race group within 0.014 of its own floor. Relationships still fall short of the floor (pair TVD 0.023 against 0.012). Its measurements depend on age as well as their condition; at epsilon 0.25 that structure costs more in noise than it adds, so the spec makes no release there.
- MST at epsilon 4 is closer still: single columns at 0.001, pairs at 0.021, and the best death prediction of any release (AUC 0.754). It learns pairs the spec left out, but not age by race, so older Black people stay at twice their share, as in the Bayesian network.
- AIM is best of all at epsilon 4: pairs below the noise floor (0.006 against 0.012) and death prediction within 0.014 AUC of the real data (0.790 against 0.804). Even at epsilon 1 it beats MST at epsilon 4.
- By subgroup, age is where releases fall short: the VAE has 19 to 28% too few people aged 70 and over and distorts them most. Each data card names any group a release misrepresents.
- Every release is at chance on every privacy attack; the plain copy of the training data is not, which shows the attacks detect leakage when it exists.
- On the 26-event trial, DP releases often give confident wrong answers: 45% of the Bayesian network's draws at epsilon 1 and 15% at epsilon 4 show an effect the real data does not. MST at epsilon 4 has none, and covers the real hazard ratio in all 20 draws. AIM, best on the person summary, is worse here: 10% of its draws are spurious at both epsilons, and its stored epsilon 1 release (23) gives a hazard ratio of 0.14 where the real one is 1.00. These releases are fit for building and testing pipelines, not for reporting estimates.

## For reviewers

- [Methodology](../synthetic_data_methodology.md): threat model, mechanisms, evaluation, results, recommended use, limits.
- [NIST AI RMF mapping](../nist_ai_rmf.md): the work against the NIST AI Risk Management Framework, with its gaps.
- [NIH and HHS requirements](../nih_hhs_requirements.md): what a real controlled-access source would require (the Genomic Data Sharing Policy, NIST SP 800-171, HIPAA de-identification) and how far the repository goes.
