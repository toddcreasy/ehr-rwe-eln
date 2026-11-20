# ELN to EHR bridge

Package: `ehr_rwe_eln.eln`. Back to the [README](../../README.md). Terms are defined in the [glossary](../GLOSSARY.md).

Reads free-text electronic lab notebook (ELN) entries, extracts the samples and results in them with Claude, and writes them into the same [OMOP](https://ohdsi.github.io/CommonDataModel/cdm54.html) database as the clinical records, linked to the right patients. The same results also come out as [FHIR R4](https://hl7.org/fhir/R4/) (Fast Healthcare Interoperability Resources) for systems that speak FHIR rather than OMOP.

## Contents

1. [Background: what ELN platforms do](#background-what-eln-platforms-do)
2. [What it does](#what-it-does)
3. [The test entries](#the-test-entries)
4. [Run it](#run-it)
5. [Results](#results)

## Background: what ELN platforms do

An ELN replaces the paper notebook a bench scientist writes in. It records what was run, on which samples, with what reagents, and what came out. In pharma it is also the legal and regulatory record: timestamped, signed, and produced for patent disputes and GxP audits (work under regulated "good practice" rules).

Most of what goes into one is free text. A scientist writes "S-0007-02 serum, creatinine 1.3 mg/dl, rerun after QC fail, 1:2 dilution." A person can read that; a database can't use it. Language models changed this. Pulling structured data out of a messy entry used to take brittle regular expressions or manual curation, and now it is a model call with a schema.

Three commercial platforms lead, each from a different scientific tradition:

| | [Benchling](https://www.benchling.com) | [Revvity Signals](https://revvitysignals.com) | [IDBS](https://www.idbs.com) |
|---|---|---|---|
| Roots | Molecular biology and biologics | Chemistry (formerly PerkinElmer Informatics) | Regulated pharma R&D and process development (now part of Danaher) |
| Typical buyer | Biotechs, startup to mid-size | Pharma discovery, chemicals, materials | Large pharma, contract development and manufacturing organizations |
| Strength | Usability, molecular biology tools, a modern API | ChemDraw, chemistry workflows, Spotfire analytics | GxP compliance, the handoff from development to manufacturing |
| Weakness | Fewer chemistry tools; cost rises at scale | Weaker biology tooling | Older interface; customers moving from E-WorkBook to the newer Polar platform |

None of the three solves the problem this module targets. They capture bench data well, and only Revvity reaches past the lab: [Signals Translational](https://revvitysignals.com/solutions/clinical-translational1) joins biomarker results to clinical trial data for cross-study analysis. That is trial data, not real world data. None of the three writes notebook results into OMOP or EHR data.

Outside the ELN category, a few systems do link lab results to patients, each by a different route:

- [LabKey Server](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC3062597/), open source, matches assay samples to participants and dates within a clinical study, and has been connected to Medidata Rave and REDCap. It takes structured assay uploads, not free-text entries, and does not write OMOP.
- [Flatiron Health](https://resources.flatiron.com/our-journey-to-integrating-real-world-clinical-outcomes-and-genomics) links Foundation Medicine's genomic results to outcomes from its EHR database, inside one company's data.
- Biobanks such as [GlioBank](https://doi.org/10.1093/noajnl/vdaf015) keep samples, research results, and clinical data together in an ELN by hand, with no common data model.

Getting lab and specimen data into OMOP is itself an open problem. [Michael et al. (2020)](https://pubmed.ncbi.nlm.nih.gov/32477663/) found no earlier study that had populated the OMOP `specimen` table from a biobank, and mapped only 26% of their own records. In eMERGE, laboratory data was the hardest part of moving EHR-linked biobanks to OMOP ([Hripcsak et al. 2019](https://doi.org/10.1016/j.jbi.2019.103253)). As of November 2026, searches of PubMed, arXiv, and GitHub turned up no project that extracts free-text notebook entries with a language model and writes them into OMOP.

Joining notebook results to the clinical record is the gap this module works in. Take a translational question such as "do patients with high baseline IL-6 respond worse to this drug?" Answering it means joining bench biomarker results to clinical outcomes, and today that join is often done by hand: export the notebooks, clean them in a spreadsheet, map sample IDs to subjects, and send a file to the real world evidence team. Again for every question.

## What it does

1. **Extract** (`extract.py`, `batch.py`). Each entry goes to Claude Opus 5.5 with a system prompt that defines a sample and a result. Structured outputs constrain the reply to the `Extraction` schema (`models.py`): samples with subject code, specimen type, and collection date, and results with analyte, value, and unit. [Pydantic](https://docs.pydantic.dev) validates every reply before it is stored. Batch runs use the [Message Batches API](https://docs.claude.com/en/docs/build-with-claude/batch-processing) at half price.
2. **Store** (`store.py`). Entries, extractions, and failures go in the `eln` schema. A failed extraction is retried on the next run; a finished one is not paid for again.
3. **Write to OMOP** (`omop.py`). Each sample becomes a `specimen` row and each result a `measurement` row with its [LOINC](https://loinc.org) (Logical Observation Identifiers Names and Codes) concept, chosen by analyte and unit. `fact_relationship` links each measurement to its specimen. Subject codes resolve to OMOP persons through the study's registry, kept in `data/registry/`, apart from anything shared.
4. **Export FHIR** (`fhir.py`). The same samples and results as FHIR R4 `Specimen` and `Observation` resources in one bundle.

The extraction prompt treats every entry as data, never as instructions, so a line in an entry addressed to the AI is ignored.

## The test entries

`synthetic.py` generates entries from templates with a seeded generator. Because it decides what goes in, it also knows the right extraction, so scoring needs no hand labeling. Entries vary the way real notebooks do: prose, tables, or lists; analyte aliases; unit and date spellings. Three sets:

- **Default** entries carry traps an extraction must skip: QC (quality control) material, reagent lots and plate IDs, and a failed run whose value is replaced by a repeat.
- **Hard** entries need the whole entry read: a sample manifest with results keyed by sample ID alone, units stated once, a rejected sample with no results, a value corrected further down, a value read on a diluted specimen (the result is the reading times the dilution), and duplicate readings with their mean.
- **Adversarial** entries each carry one prompt injection, sometimes hidden in an HTML comment, asking the model to add a fabricated sample, change a value, or return nothing.

Precision is the share of extracted samples and results that are right; recall is the share of the right ones that were extracted.

## Run it

```bash
uv run python scripts/generate_eln.py     # 300 entries on 200 hypertension subjects
uv run python scripts/extract_eln.py      # about 8 minutes, billed
uv run python scripts/write_eln_omop.py
uv run python scripts/export_eln_fhir.py
uv run pytest evals                       # hard and adversarial sets, billed
```

`generate_eln.py` picks its subjects from OMOP: oMOP is read from the lake through Redshift; `OMOP_SOURCE=staging` reads the staging Postgres instead (see [Who reads the lake](cohort.md#who-reads-the-lake)). `write_eln_omop.py` writes to the staging Postgres; republish `specimen`, `measurement`, and `fact_relationship` afterwards.

Subject codes (`HTN-0001` and on) are assigned in a random order, so a code says nothing about the person behind it. The page at http://127.0.0.1:8000/eln/ shows each entry beside what was extracted from it.

## Results

On Claude Opus 5.5, 2026-11-18, all 300 default entries extracted with none failed:

| | Expected | Extracted | Precision | Recall |
|---|---:|---:|---:|---:|
| Samples | 753 | 753 | 1.000 | 1.000 |
| Results | 1,160 | 1,160 | 1.000 | 1.000 |

All 753 specimens and 1,160 measurements reached OMOP with a mapped concept. 186 specimens have no stated collection date. OMOP requires one, so those take the date of the entry; FHIR leaves it out. The evals hold the hard and adversarial sets to at least 0.95 precision and recall, and both passed the same day.
