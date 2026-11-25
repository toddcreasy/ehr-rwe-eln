import { Help } from "./help";

// The help note for the home page. Facts come from CLAUDE.md and docs/ARCHITECTURE.md; the
// patient count is the one the page shows above it.

const Head = ({ children }: { children: React.ReactNode }) => (
  <h3 className="mt-1 text-xs font-semibold tracking-wide text-foreground uppercase">{children}</h3>
);

export default function HomeHelp({ persons }: { persons: string }) {
  return (
    <Help title="About RWE Workbench" className="ml-2">
      <Head>What it is</Head>
      <p>
        RWE (real world evidence) is what can be learned about diseases and treatments from routine health records
        rather than from clinical trials. RWE Workbench runs the main steps of that work end to end, on one
        population of synthetic patients, so every record behind every number can be shown.
      </p>

      <Head>Where the data comes from</Head>
      <p>
        Synthea, an open-source patient simulator, generated {persons} patients, each with a lifetime of visits,
        diagnoses, drugs, and lab tests. An ETL (extract, transform, load) step converts them to the OMOP
        (Observational Medical Outcomes Partnership) Common Data Model (CDM), the standard format of OHDSI
        (Observational Health Data Sciences and Informatics). The tables are stored as Apache Iceberg files in
        Amazon S3 (Simple Storage Service) and queried through Amazon Redshift. Every section reads that one copy.
        No one in it is a real person.
      </p>

      <Head>The five sections</Head>
      <p>In the order the data moves through them:</p>
      <ol className="list-decimal space-y-1 pl-5">
        <li>
          <strong>Check</strong> (Data quality): whether the tables are fit to use, before anything relies on them.
        </li>
        <li>
          <strong>Emulate</strong> (Trial emulation): what a randomized trial of two drugs would have found, worked
          out from records alone, with checks for the bias that records carry.
        </li>
        <li>
          <strong>Extract</strong> (Lab notebook): Claude, a large language model, reads free-text ELN (electronic lab
          notebook) entries and turns them into structured samples and results, linked to patients.
        </li>
        <li>
          <strong>Curate</strong> (Variant curation): real genetic variants from ClinVar, NCBI&apos;s (National
          Center for Biotechnology Information) public archive, classified by the rules expert panels use; a curator
          records the final class.
        </li>
        <li>
          <strong>Release</strong> (Synthetic data): differentially private copies of the data, made to be shared,
          with how faithful, useful, and private each one is.
        </li>
      </ol>

      <Head>How to use this page</Head>
      <p>
        Click a tile, or use the arrow keys, to see what that section asks and its latest numbers, then open it.
        The numbers come live from each section&apos;s latest run. Every page has &ldquo;?&rdquo; buttons like this
        one; the switch at the top right turns them off.
      </p>
      <p>For research and demonstration only. Nothing here is medical advice.</p>
    </Help>
  );
}
