import { Help, Term } from "../help";
import type { Status } from "./status";

// Help notes for the data quality page. Facts come from docs/modules/data_quality.md; the counts
// come from the run on screen, so the notes stay true when another run is picked.

const fmt = (n: number) => n.toLocaleString("en-US");

type Totals = Record<Status, number>;

// A small heading inside a note, for the longer ones with sections.
const Head = ({ children }: { children: React.ReactNode }) => (
  <h3 className="mt-1 text-xs font-semibold tracking-wide text-foreground uppercase">{children}</h3>
);

export function PageHelp() {
  return (
    <Help page title="Data quality">
      <Head>Why run it</Head>
      <p>
        <Term t="RWE">Real world evidence</Term> is what you learn from health data collected outside a clinical trial, such as
        electronic health records. Regulators, the <Term t="FDA" /> among them, accept it for some decisions, but only when the
        analysis is built carefully, and that starts with the data. An analysis run on broken dates or wrongly coded
        diagnoses gives a confident, wrong answer.
      </p>
      <p>
        So the checks run on the finished database before any analysis uses it. Whatever fails here is a limit
        to keep in mind on every other page.
      </p>

      <Head>Where the data comes from</Head>
      <p>
        <strong>Synthea</strong> 3.3.0, an open-source simulator, generates the medical histories of 23,421 people
        who never existed, with a fixed seed so the same people come out every time. No real patient data is used.
      </p>
      <p>
        This project&apos;s <Term t="ETL" /> converts those records into the <Term t="OMOP" />{" "}
        <Term t="CDM">Common Data Model</Term> v5.4, mapping each code to a standard <Term t="concept" /> from the{" "}
        <Term t="Athena" /> vocabularies of <Term t="OHDSI" />, the open research network that maintains OMOP. OMOP is the network&apos;s shared table
        layout, so analysis code written for it runs on any data in that form. The lab notebook section adds
        specimens and lab results to the same tables.
      </p>
      <p>
        The OMOP tables live as <Term t="Iceberg">Apache Iceberg</Term> tables in Amazon <Term t="S3" /> and are queried
        through Amazon <Term t="Redshift">Redshift</Term>.
        OHDSI&apos;s own <Term t="DQD">DataQualityDashboard</Term> (DQD) 2.9.1, in R, runs against them, and its
        results are loaded into the app&apos;s database and shown here.
      </p>

      <Head>What it checks</Head>
      <p>
        Each run executes 2,384 checks at three levels: whole tables (does <code>measurement</code> have rows?),
        single fields (is a birth year before 1850?), and specific concepts (is a female-only condition recorded on
        a male?).
      </p>

      <Head>How to read it</Head>
      <p>
        Start with the tiles for the overall picture, use the bar chart to see which kind of check fails, then read
        the failures themselves in the table at the bottom. Pick an older run in the menu at the top right to
        compare. Each &ldquo;?&rdquo; on the page explains the part next to it.
      </p>
      <p>Synthetic data, for research and demonstration only.</p>
    </Help>
  );
}

// strict and dqd: the two pass rates exactly as the tiles show them.
export function TilesHelp({ totals, strict, dqd }: { totals: Totals; strict: number | null; dqd: number }) {
  const all = totals.pass + totals.na + totals.fail + totals.error;
  const applicable = all - totals.na;
  return (
    <Help title="The summary tiles">
      <p>
        <strong>Checks</strong>: {fmt(all)} in this run. Each one either passes, fails, errors, or has nothing to
        test.
      </p>
      <p>
        <strong>Failed</strong>: {fmt(totals.fail)}. A check fails when the share of rows breaking its rule is over
        its threshold, which the table lists for each check. At 0%, one bad row fails it.
      </p>
      <p>
        <strong>Errors</strong>: {fmt(totals.error)}. The check&apos;s query itself failed, so the result is unknown.
        Zero is what you want.
      </p>
      <p>
        <strong>Not applicable</strong>: {fmt(totals.na)}. There was nothing to test: an empty table, or a check
        about a lab that never appears in this data. Synthea leaves several <Term t="OMOP" /> tables empty, which is why this
        number is large. It says nothing bad about the data.
      </p>
      <p>
        <strong>Pass rate</strong> ({strict === null ? "n/a" : `${strict}%`}) counts only the {fmt(applicable)} checks that
        had something to test. <strong>DQD pass rate</strong> ({dqd}%) is
        the figure the checking tool, <Term t="DQD" />, reports itself, which counts not-applicable checks as passed. The first is stricter; the second is shown so this run can be compared with other DQD reports.
      </p>
    </Help>
  );
}

export function ChartHelp({ counts }: { counts: Record<string, Totals> }) {
  const line = (c: string) => {
    const t = counts[c];
    const n = t.pass + t.na + t.fail + t.error;
    return `${fmt(n)} checks, ${fmt(t.fail)} failed`;
  };
  return (
    <Help title="Checks by Kahn category">
      <p>
        <Term t="DQD" /> sorts every check into one of three categories from the <Term t="Kahn">Kahn framework</Term> (Kahn et al.,
        2016), the standard way to group data quality checks on health records:
      </p>
      <p>
        <strong>Conformance</strong> ({line("Conformance")}): values follow the rules of the <Term t="CDM">data model</Term> the tables use. Right data types,
        keys that point at real rows, codes that exist in the vocabulary.
      </p>
      <p>
        <strong>Completeness</strong> ({line("Completeness")}): the values that should be there are there, such as
        a standard concept for every diagnosis.
      </p>
      <p>
        <strong>Plausibility</strong> ({line("Plausibility")}): values make sense. Birth years in range, no visit
        ending before it starts, no prostate cancer in a woman.
      </p>
      <p>
        <strong>Reading the bars.</strong> Each bar is 100% of that category&apos;s checks, split by status: green
        passed, grey had nothing to test, red failed, orange errored. Hover a segment for its count, or use Show
        table for the exact numbers. A long grey stretch means many checks had nothing to look at, not that
        anything is wrong. The red slivers are what matter, and the table below lists them.
      </p>
    </Help>
  );
}

export function TableHelp({ failed }: { failed: number }) {
  return (
    <Help title="The checks table">
      <p>
        One row per check. It opens on the {fmt(failed)} failed checks (and any errors); the first menu shows
        passed or not-applicable checks too. Filter by category or <Term t="OMOP" /> table, or search for a field or <Term t="concept" /> ID.
      </p>
      <p>
        <strong>Check</strong>: the check&apos;s name in <Term t="DQD" />, then the table and field it tests, and a concept ID when the
        check is about one concept. The grey line under it says in words what was tested, or why it was not
        applicable.
      </p>
      <p>
        <strong>Violated rows</strong>: rows that broke the rule, out of the rows checked. <strong>Violated</strong>{" "}
        is the same as a percentage, and <strong>Threshold</strong> is the most DQD allows before failing the check.
        Rows are sorted with the largest share first.
      </p>
      <p>
        <strong>What the failures mean.</strong> In the 2026-11-20 run, all 14 failures come from Synthea&apos;s data.
        Eleven are how its codes map to OMOP: procedure and device codes with no standard
        concept, observations with no unit, dates before DQD&apos;s plausible lower bound, and 28 of 209,849 drug
        strength rows whose ingredient is not classed as one. Three are diagnoses Synthea gave the wrong sex:
        prostate cancer in 12 women, ovarian cancer in 4 men, and uterine fibroids in 1 man.
      </p>
      <p>
        The Violated column shows how big each problem is next to the rows checked. Keep these limits in mind when
        reading the other pages.
      </p>
    </Help>
  );
}
