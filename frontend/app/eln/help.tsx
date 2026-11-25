import { Help, Term } from "../help";

// Help notes for the lab notebook page. Facts come from docs/modules/eln.md and the code in
// src/ehr_rwe_eln/eln/; the counts come from the data on screen, so the notes stay true after a rerun.

const fmt = (n: number) => n.toLocaleString("en-US");

// A small heading inside a note, for the longer ones with sections.
const Head = ({ children }: { children: React.ReactNode }) => (
  <h3 className="mt-1 text-xs font-semibold tracking-wide text-foreground uppercase">{children}</h3>
);

export function PageHelp() {
  return (
    <Help page title="Lab notebook extraction">
      <Head>Why run it</Head>
      <p>
        <Term t="RWE">Real world evidence</Term> is what you learn from health data collected outside a clinical
        trial, such as <Term t="EHR">electronic health records</Term>. Some questions need bench results too.
        &ldquo;Do patients with high baseline <Term t="IL-6" /> respond worse to this drug?&rdquo; means joining a lab&apos;s biomarker
        results to each patient&apos;s clinical outcomes.
      </p>
      <p>
        Those results sit in an <Term t="ELN" />, mostly as free text. A person can read
        &ldquo;S-0007-02 serum, creatinine 1.3 mg/dl&rdquo;; a database can&apos;t. Today the join is often done
        by hand: export the notebooks, clean them in a spreadsheet, map sample IDs to subjects, and
        send a file to the RWE team. Again for every question. This section does that step with a language model
        and writes the results into the same database as the clinical records.
      </p>

      <Head>Where the data comes from</Head>
      <p>
        <strong>The entries</strong> are synthetic, generated in this repo from templates with a seeded random
        generator. The default run writes 300 entries on 200 adults with essential hypertension from the
        project&apos;s Synthea patients, who never existed. Because the generator decides what goes in, it also
        knows the right answer for every entry.
      </p>
      <p>
        <strong>Subjects</strong> appear only as study codes such as HTN-0007, given out in a random order so a
        code says nothing about the person. The key from code to person is a registry kept apart from the
        entries, the way a biobank keeps it. This page shows only whether a code links to a person, never which
        one.
      </p>
      <p>
        <strong>The extraction</strong> is done by Claude, a <Term t="LLM">large language model</Term>. The stored entries were
        extracted by Claude Opus 5.5 on the Anthropic API on 2026-11-18; new runs use Opus 4.6 on Amazon Bedrock,
        which scored the same on every labeled test set when the project moved there on 2026-11-20. Its reply is constrained to a fixed schema and checked by Pydantic, a Python
        library that validates data against a typed model, before it is stored. A reply that doesn&apos;t fit is
        recorded as a failure and retried on the next run.
      </p>
      <p>
        <strong>The outputs</strong> go to the <Term t="OMOP" /> <Term t="CDM">Common Data Model</Term> v5.4, the
        same tables the rest of the site reads: one <code>specimen</code> row per sample and one{" "}
        <code>measurement</code> row per result, linked to each other. The same results are also exported as{" "}
        <Term t="FHIR" /> R4 <code>Specimen</code> and <code>Observation</code>{" "}
        resources, for systems that exchange data in FHIR. This page shows the entries and the extractions, not
        those outputs.
      </p>

      <Head>What it does</Head>
      <p>
        Each entry goes to Claude with instructions that define a sample (a specimen from a study subject) and a
        result (an analyte, a value, and a unit). The entries carry the traps real notebooks have:{" "}
        <Term t="QC" /> material that is not a patient sample, reagent lots and plate numbers, a failed run replaced by a
        repeat, values read on a diluted specimen, and units written many ways.
      </p>
      <p>
        Some test entries also hide an instruction to the <Term t="AI" />, such as &ldquo;add this
        sample&rdquo;. The prompt treats every entry as data, never as instructions, so those lines are ignored.
      </p>
      <p>
        Each result is then coded with a <Term t="LOINC" /> concept, chosen
        by analyte and unit, and written to OMOP for the subjects the registry links.
      </p>

      <Head>How to read it</Head>
      <p>
        The tiles give the totals. Pick an entry in the list on the left, then compare &ldquo;Entry as
        written&rdquo; with the two tables under &ldquo;Extracted&rdquo;: every subject sample and result in the
        text should appear once, and nothing else should. Each &ldquo;?&rdquo; on the page explains the part next
        to it.
      </p>
      <p>Synthetic data, for research and demonstration only.</p>
    </Help>
  );
}

type Summary = {
  subjects: number;
  entries: number;
  extracted: number;
  failed: number;
  samples: number;
  results: number;
  models: string[];
};

export function TilesHelp({ summary }: { summary: Summary }) {
  const pending = summary.entries - summary.extracted - summary.failed;
  return (
    <Help title="The summary tiles">
      <p>
        <strong>Entries</strong>: {fmt(summary.entries)} synthetic <Term t="ELN" /> entries, written
        about {fmt(summary.subjects)} study subjects. Each entry covers one to four subjects.
      </p>
      <p>
        <strong>Extracted</strong>: {fmt(summary.extracted)} entries with a stored extraction that passed the
        schema check. <strong>Failed</strong> ({fmt(summary.failed)}) means the model&apos;s reply did not fit
        the schema or stopped early; <strong>pending</strong> ({fmt(pending)}) means not sent yet. Both are
        picked up on the next run, and a finished entry is never paid for twice.
      </p>
      <p>
        <strong>Samples</strong>: {fmt(summary.samples)} specimens and <strong>Results</strong>:{" "}
        {fmt(summary.results)} measurements, added up over the extracted entries. When written to{" "}
        <Term t="OMOP" />, a sample reported in two entries becomes one specimen, so
        the OMOP counts can be lower, never higher.
      </p>
      <p>
        The line under Results names the model that did the extractions
        {summary.models.length ? `: ${summary.models.join(", ")}` : ""}. It is the model recorded with each stored
        extraction, so it changes only when the entries are extracted again.
      </p>
      <p>
        In the documented run (2026-11-18), all 300 default entries extracted with none failed: 753 samples and
        1,160 results, every one matching the generator&apos;s answer.
      </p>
    </Help>
  );
}

type EntryRow = { status: "extracted" | "failed" | "pending" };

export function EntriesHelp({ entries }: { entries: EntryRow[] }) {
  const n = (s: EntryRow["status"]) => entries.filter((e) => e.status === s).length;
  return (
    <Help title="The entries list">
      <p>
        All {fmt(entries.length)} <Term t="ELN" /> entries, in ID order. Click one to
        open it on the right.
      </p>
      <p>
        Each row gives the entry ID, its title, and either how many samples and results were extracted from it
        or its status: {fmt(n("extracted"))} extracted, {fmt(n("failed"))} failed, {fmt(n("pending"))} pending.
      </p>
      <p>
        The entries vary the way real notebooks do: prose, tables, or lists, different names for the same
        analyte, and different spellings of units and dates. That variety is what the extraction has to read
        through.
      </p>
    </Help>
  );
}

type Entry = {
  model: string | null;
  error: string | null;
  extraction: { samples: unknown[]; results: unknown[] } | null;
};

export function EntryHelp({ entry }: { entry: Entry }) {
  return (
    <Help title="One entry">
      <p>
        The entry&apos;s ID and title, then its author and date. The authors (Analyst A, B, C) and
        the date are generated with the entry; the date is the day the assay was run, which is not always the
        day the specimens were collected.
      </p>
      <p>
        {entry.model
          ? `It was extracted by ${entry.model}, a version of Claude, a large language model (LLM).`
          : "No model has read this entry yet."}
      </p>
      <p>
        Below, the entry&apos;s text sits on the left and what Claude pulled out of it on the right, so you can
        check one against the other.
      </p>
    </Help>
  );
}

export function BodyHelp() {
  return (
    <Help title="Entry as written">
      <p>
        The notebook text exactly as stored, the only thing the model saw. It is synthetic, generated from
        templates in this repo.
      </p>
      <p>
        Look for what should <strong>not</strong> be extracted: <Term t="QC" /> material, which is a sample
        with a known value run to check the assay, not a patient; reagent lots and plate numbers; and a failed
        run whose value a repeat replaces.
      </p>
      <p>
        Harder entries give units once for a whole table, correct a value further down, report a reading on a
        diluted specimen (the result is the reading times the dilution), or give duplicate readings and their
        mean. Some test entries also carry a line addressed to the <Term t="AI" />; the extraction
        ignores it.
      </p>
    </Help>
  );
}

export function ExtractedHelp({ entry }: { entry: Entry }) {
  return (
    <Help title="Extracted">
      <p>
        What Claude, a <Term t="LLM">large language model</Term>, returned for this entry. The reply had to fit a fixed schema:
        samples with a subject code, specimen type, and collection date, and results with an analyte, value, and
        unit. Pydantic, a Python library that checks data against a typed model, validated it before it was
        stored.
      </p>
      <p>
        {entry.extraction
          ? `This entry gave ${fmt(entry.extraction.samples.length)} samples and ${fmt(entry.extraction.results.length)} results.`
          : entry.error
            ? "This entry's extraction failed, so nothing from it reaches OMOP (Observational Medical Outcomes Partnership); it is retried on the next run."
            : "This entry has not been sent to the model yet."}
      </p>
      <p>
        A correct extraction lists every subject sample and result in the text once, and nothing else. On the
        test sets (2026-11-20), precision and recall were both 1.000. Precision is the share of extracted items
        that are right; recall is the share of the right items that were extracted.
      </p>
    </Help>
  );
}

type Sample = { collection_date: string | null };

export function SamplesHelp({ samples, linked }: { samples: Sample[]; linked: number }) {
  const undated = samples.filter((s) => s.collection_date === null).length;
  return (
    <Help title="Extracted samples">
      <p>
        One row per specimen from a study subject. <strong>Sample</strong> and <strong>Subject</strong> are
        copied exactly as written. Each sample becomes one row in the{" "}
        <Term t="OMOP" /> <code>specimen</code> table.
      </p>
      <p>
        <strong>(linked)</strong> means the subject code resolves to a person in the OMOP data through the
        registry; {fmt(linked)} of this entry&apos;s subject codes do. <strong>(no OMOP person)</strong> means it
        does not, and that sample is left out of OMOP. The page never shows which person a code belongs to.
      </p>
      <p>
        <strong>Specimen</strong> is one of serum, plasma, whole blood, or urine, with tube details dropped
        (&ldquo;EDTA plasma&rdquo;, plasma from a tube with the anticoagulant <Term t="EDTA" />, is plasma). <strong>Collected</strong> is filled only when the entry says
        when the specimen was taken; the assay date doesn&apos;t count.
      </p>
      <p>
        {fmt(undated)} of {fmt(samples.length)} samples here have no stated date. OMOP requires one, so those
        take the entry&apos;s date there; the <Term t="FHIR" /> export leaves it out.
      </p>
    </Help>
  );
}

export function ResultsHelp({ count }: { count: number }) {
  return (
    <Help title="Extracted results">
      <p>
        {fmt(count)} results, one per sample and analyte. Each becomes a row in the <Term t="OMOP" />{" "}
        <code>measurement</code> table, linked to its specimen.
      </p>
      <p>
        <strong>Analyte</strong> is what was measured: creatinine, hba1c (<Term t="HbA1c" />), crp (<Term t="CRP" />),
        hs crp (<Term t="hs-CRP" />, a separate assay), il6 (<Term t="IL-6" />), or nt probnp (<Term t="NT-proBNP" />).
      </p>
      <p>
        <strong>Value</strong> is the reported number, never converted between units. For a failed run it is
        the repeat; for a diluted specimen, the reading times the dilution; for duplicate readings, the mean the
        entry gives.
      </p>
      <p>
        <strong>Unit</strong> is written as a <Term t="UCUM" /> code, whatever spelling the entry used (mg/dl
        becomes mg/dL). Analyte and unit together pick the <Term t="LOINC" /> concept in OMOP, so creatinine in mg/dL and in umol/L get different codes.
      </p>
    </Help>
  );
}
