// Terms a help note can mark with <Term>: hovering or focusing one shows its definition. Short
// forms of the entries in docs/GLOSSARY.md; keep the two saying the same thing.

export type Entry = { name?: string; def: string };

export const GLOSSARY = {
  "ACMG/AMP": {
    name: "American College of Medical Genetics and Genomics and Association for Molecular Pathology",
    def: "The 2015 rules for classifying a variant. Each criterion is one piece of evidence, pathogenic or benign, at a set strength.",
  },
  AF: {
    name: "Allele frequency",
    def: "How common a variant is: the share of all copies of that spot in the genome, two per person, that carry it.",
  },
  AI: { name: "Artificial intelligence", def: "Here, Claude, the large language model that reads each notebook entry." },
  AIM: {
    name: "Adaptive and iterative mechanism",
    def: "MST's successor from the same research group. Told which column combinations the analyses will read, it spends its privacy budget in rounds, each measuring the one the current model fits worst.",
  },
  Athena: {
    def: "OHDSI's vocabulary website, where the standard concepts and their mappings are downloaded, each vocabulary under its own license.",
  },
  AUC: {
    name: "Area under the curve",
    def: "How well a score separates two groups. 0.5 is a coin flip; 1 is perfect.",
  },
  CC0: { name: "Creative Commons Zero", def: "Creative Commons' public domain dedication." },
  CDM: {
    name: "Common Data Model",
    def: "A shared database layout: data from any source put into it can be analyzed by the same code, unchanged.",
  },
  CI: {
    name: "Confidence interval",
    def: "A range around an estimate, here at 95%, that says how sure the estimate is.",
  },
  ClinGen: {
    name: "Clinical Genome Resource",
    def: "Its expert panels adapt the ACMG/AMP criteria to their genes and publish the result in the CSpec registry.",
  },
  concept: {
    def: "In OMOP, one clinical idea with a numeric ID. Each idea has one standard concept, and the ETL maps every source code to it.",
  },
  CRP: { name: "C-reactive protein", def: "A blood marker of inflammation." },
  CSpec: {
    name: "Criteria Specification",
    def: "ClinGen's registry where each expert panel publishes how it adapts the ACMG/AMP criteria: thresholds, which criteria apply, and at what strength.",
  },
  DAC: {
    name: "Data access committee",
    def: "The committee that checks a researcher's planned use of controlled-access data against what the participants consented to.",
  },
  DNA: { name: "Deoxyribonucleic acid", def: "The molecule that carries the genome." },
  DP: {
    name: "Differential privacy",
    def: "A mathematical guarantee that what is released barely changes whether or not any one person's data was used. It works by adding calibrated random noise.",
  },
  DQD: {
    name: "DataQualityDashboard",
    def: "OHDSI's data quality tool for OMOP databases, written in R. It runs about 2,400 checks and scores each against a threshold.",
  },
  EDTA: {
    name: "Ethylenediaminetetraacetic acid",
    def: "An anticoagulant in blood collection tubes. EDTA plasma is plasma from such a tube.",
  },
  EHR: {
    name: "Electronic health record",
    def: "The digital chart a hospital or clinic keeps for each patient: diagnoses, prescriptions, lab results, procedures, and visits.",
  },
  ELN: {
    name: "Electronic lab notebook",
    def: "The digital replacement for a bench scientist's paper notebook: what was run, on which samples, and what came out. Most of it is free text.",
  },
  "EMBL-EBI": {
    name: "European Molecular Biology Laboratory's European Bioinformatics Institute",
    def: "The institute that runs Ensembl.",
  },
  ENIGMA: {
    name: "Evidence-based Network for the Interpretation of Germline Mutant Alleles",
    def: "The ClinGen expert panel for BRCA1 and BRCA2. Its tables of loss-of-function variants and lab assay results are read by the rules.",
  },
  ETL: {
    name: "Extract, transform, load",
    def: "Read data from a source, reshape it, and write it to a target. Here: Synthea's files into OMOP tables.",
  },
  FAF: {
    name: "Filtering allele frequency",
    def: "The low end of a 95% confidence interval on a variant's frequency, in the ancestry group where it is highest. Expert panels set their \"too common\" thresholds on it.",
  },
  FDA: { name: "Food and Drug Administration", def: "The US regulator of drugs and medical devices." },
  FHIR: {
    name: "Fast Healthcare Interoperability Resources",
    def: "A standard for exchanging health data between systems as small JSON resources. R4, release 4, is the one most systems use.",
  },
  gnomAD: {
    name: "Genome Aggregation Database",
    def: "Variant frequencies from hundreds of thousands of exomes and genomes. A variant too common in gnomAD to cause a rare disease is evidence that it is benign.",
  },
  GRCh38: {
    name: "Genome Reference Consortium human build 38",
    def: "The current human reference genome, the map that variant positions are given against.",
  },
  HbA1c: { name: "Hemoglobin A1c", def: "A blood test of average blood sugar over about three months." },
  HGVS: {
    name: "Human Genome Variation Society",
    def: "Its notation is the standard way to name a variant: a c. name for the change in the coding DNA, a p. name for the change to the protein.",
  },
  HPO: {
    name: "Human Phenotype Ontology",
    def: "About 20,000 terms for clinical findings, each linked to broader ones above it, and a file of which terms each gene's diseases show.",
  },
  HR: {
    name: "Hazard ratio",
    def: "The rate of the outcome in the treatment arm divided by the rate in the comparator arm, from a Cox model. Below 1 favors the treatment; 1 means no difference.",
  },
  "hs-CRP": {
    name: "High-sensitivity CRP",
    def: "A separate, more sensitive test for C-reactive protein, a marker of inflammation.",
  },
  Iceberg: {
    name: "Apache Iceberg",
    def: "An open table format: a table is data files plus metadata files that any query engine can read.",
  },
  "IL-6": { name: "Interleukin-6", def: "An inflammatory signal measured in blood." },
  Kahn: {
    name: "Kahn framework",
    def: "The standard grouping of data quality checks on health records (Kahn et al., 2016): conformance, completeness, and plausibility.",
  },
  LDLR: {
    name: "Low-density lipoprotein receptor",
    def: "The gene behind one form of hyperlipidemia, high blood fats.",
  },
  LLM: {
    name: "Large language model",
    def: "A model that reads and writes text. Claude, the one used here, is Anthropic's.",
  },
  LOINC: {
    name: "Logical Observation Identifiers Names and Codes",
    def: "Codes for lab tests, where one code fixes what was measured, in what specimen, and on what scale. OMOP's standard for measurements.",
  },
  MANE: {
    name: "Matched Annotation from NCBI and EMBL-EBI",
    def: "MANE Select is the one transcript per gene that NCBI and Ensembl agree on, which clinical reports use.",
  },
  MST: {
    name: "Maximum spanning tree",
    def: "A differentially private synthesizer, winner of NIST's 2018 synthetic data contest. It measures every column, picks a tree of column pairs, measures those, and samples from a model fitted to them.",
  },
  NCBI: {
    name: "National Center for Biotechnology Information",
    def: "Runs ClinVar, LitVar2, and PubTator3, among other public biology databases.",
  },
  NIST: {
    name: "National Institute of Standards and Technology",
    def: "Ran the 2018 differential privacy synthetic data contest that MST won.",
  },
  "NT-proBNP": { name: "N-terminal pro-B-type natriuretic peptide", def: "A blood marker of heart failure." },
  OHDSI: {
    name: "Observational Health Data Sciences and Informatics",
    def: 'Pronounced "Odyssey." The open research network that maintains OMOP, its vocabularies, and open-source tools to analyze them.',
  },
  OMOP: {
    name: "Observational Medical Outcomes Partnership",
    def: "The common data model OHDSI maintains: a table per kind of clinical event, each fact pointing to a standard concept.",
  },
  PMID: { name: "PubMed identifier", def: "The number that identifies a paper in PubMed." },
  PTC: {
    name: "Premature termination codon",
    def: "A stop signal that comes too early in the gene's code, cutting the protein short.",
  },
  QC: {
    name: "Quality control",
    def: "In a lab, QC samples are material with known values run alongside real specimens to check that an assay works. They are not patient samples.",
  },
  Redshift: {
    name: "Amazon Redshift",
    def: "AWS's data warehouse. Every query on the OMOP tables here goes through it.",
  },
  RWE: {
    name: "Real world evidence",
    def: "What is learned from health data collected outside a clinical trial, such as health records, insurance claims, or registries.",
  },
  S3: { name: "Amazon Simple Storage Service", def: "AWS's file storage. The OMOP tables are stored there." },
  "SHA-256": {
    name: "Secure Hash Algorithm 256",
    def: "A fingerprint of a file's contents. It changes if anything in the file does.",
  },
  SMD: {
    name: "Standardized mean difference",
    def: "The gap between the arms' averages for a covariate, divided by its spread. Below 0.1 in absolute value is the usual threshold for balanced.",
  },
  Synthea: {
    def: "An open-source simulator from MITRE that writes complete medical histories for people who never existed.",
  },
  TVD: {
    name: "Total variation distance",
    def: "How far apart two distributions are, from 0 (identical) to 1 (no overlap).",
  },
  UCUM: {
    name: "Unified Code for Units of Measure",
    def: "A grammar for writing units unambiguously, such as mg/dL or umol/L. OMOP and FHIR both use it.",
  },
  VAE: {
    name: "Variational autoencoder",
    def: "A neural network that compresses each record into a few numbers and learns to rebuild it. Decoding new numbers gives new records.",
  },
  VEP: {
    name: "Variant Effect Predictor",
    def: "Ensembl's tool for what a variant does to each transcript: its consequence, HGVS names, position, and exon.",
  },
  YAML: {
    name: "YAML Ain't Markup Language",
    def: "A plain-text format for structured settings. Each trial protocol is written in it.",
  },
} satisfies Record<string, Entry>;

export type TermKey = keyof typeof GLOSSARY;
