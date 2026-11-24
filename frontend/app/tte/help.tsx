import { Help } from "../help";

// Help notes for the trial emulation page. Facts come from docs/modules/trial_emulation.md,
// docs/GLOSSARY.md, and src/ehr_rwe_eln/tte/; the numbers come from the run on screen, so the
// notes stay true when another run is picked.

const fmt = (n: number) => n.toLocaleString("en-US");
const pct = (n: number) => `${(n * 100).toFixed(1)}%`;
const signed = (n: number) => `${n >= 0 ? "+" : ""}${(n * 100).toFixed(1)}%`;
const two = (n: number) => n.toFixed(2);
const label = (s: string) => s.replaceAll("_", " ");

type Arm = { name: string; persons: number; events: number; median_follow_up_days: number };
type Interval = { low: number | null; high: number | null };
type Risk = { day: number; risk_treatment: number; risk_comparator: number; risk_difference: number };

// A small heading inside a note, for the longer ones with sections.
const Head = ({ children }: { children: React.ReactNode }) => (
  <h3 className="mt-1 text-xs font-semibold tracking-wide text-foreground uppercase">{children}</h3>
);

export function PageHelp() {
  return (
    <Help title="Target trial emulation">
      <Head>Why run it</Head>
      <p>
        Real world evidence (RWE) is what you learn from health data collected outside a clinical trial, such as
        electronic health records. A common RWE question is causal: does starting drug A instead of drug B change the
        risk of some outcome? A trial would answer it, but trials are slow and costly, and the records already exist.
      </p>
      <p>
        Comparing the records naively gives wrong answers. Doctors pick drugs for reasons tied to the outcome
        (confounding), and careless designs count follow-up time before anyone could have started treatment.
        Target trial emulation, formalized by Miguel Hern&aacute;n and James Robins (2016), guards against both: you
        write down the randomized trial you would have run, then apply that protocol to the records as closely as
        the data allow.
      </p>

      <Head>Where the data comes from</Head>
      <p>
        <strong>Synthea</strong> 3.3.0, an open-source simulator, generates the medical histories of 23,421 people
        who never existed. No real patient data is used. This project converts them into the{" "}
        <strong>OMOP</strong> (Observational Medical Outcomes Partnership) Common Data Model (CDM) v5.4, the shared
        table layout of the OHDSI (Observational Health Data Sciences and Informatics) research network.
      </p>
      <p>
        Each trial is a <strong>protocol</strong> file in YAML (YAML Ain&apos;t Markup Language) under{" "}
        <code>src/ehr_rwe_eln/tte/protocols/</code>: who is eligible, the two drugs, the outcome, how long to
        follow people, and the covariates to adjust for. There are four: lisinopril against amlodipine and metformin
        against insulin, each with chronic kidney disease stage 3 or worse and with myocardial infarction (heart
        attack) as the outcome.
      </p>
      <p>
        <code>scripts/run_tte.py</code> reads the OMOP tables from the project&apos;s data lake, Apache Iceberg tables
        in Amazon S3 (Simple Storage Service) queried through Amazon Redshift. It closes the billed Redshift session
        before fitting any models. It stores each run in the <code>tte</code> schema of the app&apos;s PostgreSQL database, and this page
        reads it from there. A run on 2026-11-23 took 31 minutes.
      </p>

      <Head>What it does</Head>
      <p>
        <strong>Builds the trial.</strong> Time zero, the day follow-up starts, is each person&apos;s first use of
        either drug, and their arm is whichever they started. Eligibility rules apply in order on that day.
      </p>
      <p>
        <strong>Weights the arms.</strong> A logistic regression (a standard model for yes or no outcomes) gives each person a propensity score, their
        estimated chance of getting the treatment drug given their covariates. Weighting by it makes the arms look
        alike on those covariates, as randomization would.
      </p>
      <p>
        <strong>Estimates the effect.</strong> Weighted risks by day, and one hazard ratio from a weighted Cox model
        (a standard survival model), each with 95% intervals.
      </p>
      <p>
        <strong>Checks for bias.</strong> Balance after weighting, overlap between the arms, and negative control
        outcomes the drugs should not affect. When the arms do not overlap, the page says &ldquo;not estimable&rdquo;
        instead of printing a number.
      </p>
      <p>
        OHDSI&apos;s own R packages run on the same protocols as a check (CohortMethod 6.0.3 on the two lisinopril
        protocols, TrialEmulation 0.0.5 for a per-protocol estimate on the kidney protocol). Their results are not on
        this page.
      </p>

      <Head>How to read it</Head>
      <p>
        Each card is one protocol. Read it top to bottom, the way a trial report goes: who got in, how well weighting
        balanced the arms, the estimates, then the negative controls. Trust an estimate only when the checks above
        it hold up. Pick an older run in the menu at the top right to compare. Each &ldquo;?&rdquo; explains the
        part next to it.
      </p>
      <p>
        Synthea assigns treatments by fixed rules, so these numbers test the method, not the drugs. Synthetic data,
        for research and demonstration only.
      </p>
    </Help>
  );
}

export function AttritionHelp({ attrition }: { attrition: { rule: string; persons: number }[] }) {
  const first = attrition[0];
  const last = attrition[attrition.length - 1];
  const drops = attrition.slice(1).map((a, i) => ({ rule: a.rule, lost: attrition[i].persons - a.persons }));
  const biggest = drops.reduce<{ rule: string; lost: number } | null>((m, d) => (!m || d.lost > m.lost ? d : m), null);
  return (
    <Help title="Attrition">
      <p>
        How many people are left after each eligibility rule, applied in order. It is the first table of any trial
        report, and it shows who the result is about.
      </p>
      {first && last && (
        <p>
          Here {fmt(first.persons)} people started either drug, and {fmt(last.persons)} passed every rule.
          {biggest && biggest.lost > 0 && (
            <>
              {" "}
              The largest cut, {fmt(biggest.lost)} people, came at &ldquo;{biggest.rule}&rdquo;.
            </>
          )}
        </p>
      )}
      <p>
        <strong>Time zero</strong> is each person&apos;s first day on either drug. Every rule is checked on that day,
        so eligibility, the choice of arm, and the start of follow-up line up. No follow-up time is counted before
        treatment starts.
      </p>
      <p>
        The last rule drops anyone who already had the outcome, since they cannot have it for the first time during
        follow-up.
      </p>
    </Help>
  );
}

export function ArmsHelp({ arms }: { arms: Arm[] }) {
  return (
    <Help title="Arms">
      <p>
        The two strategies being compared, as people started them. The analysis is intention to treat: people stay
        in the arm they started in, whatever they take later.
      </p>
      {arms.map((a) => (
        <p key={a.name}>
          <strong>{a.name}</strong>: {fmt(a.persons)} people, {fmt(a.events)} with the outcome, followed for a median
          of {fmt(Math.round(a.median_follow_up_days))} days.
        </p>
      ))}
      <p>
        <strong>Events</strong> are first occurrences of the outcome after time zero. Follow-up ends at the
        outcome, death, the end of the person&apos;s records, or the protocol&apos;s maximum, whichever comes first.
      </p>
      <p>
        Here {fmt(arms.reduce((n, a) => n + a.events, 0))} events in all carry the estimate. Few events mean wide
        intervals further down.
      </p>
    </Help>
  );
}

export function NotEstimableHelp({ reason }: { reason: string }) {
  return (
    <Help title="Not estimable">
      <p>The module refused to estimate this effect. The reason it gave: &ldquo;{reason}&rdquo;.</p>
      <p>
        A fair comparison needs <strong>positivity</strong>: every eligible person could have received either drug.
        When the covariates (age, sex, prior conditions, recent measurements) nearly decide which drug a person gets,
        some kinds of people only ever appear in one arm. The data hold no comparison for them, and no weighting can
        create one. &ldquo;No convergence&rdquo; is the milder form: the propensity model kept pushing some
        people&apos;s chance of their own arm toward 100% and never settled on an answer.
      </p>
      <p>
        Synthea treats diabetes by fixed rules, so for the metformin protocols the covariates almost decide who gets
        insulin. Reporting &ldquo;not estimable&rdquo; instead of a number is the bias check doing its job.
      </p>
    </Help>
  );
}

export function DiagnosticsHelp({
  outside,
  weightMin,
  weightMax,
  effective,
  arms,
  unbalanced,
}: {
  outside: number;
  weightMin: number;
  weightMax: number;
  effective: [number, number];
  arms: Arm[];
  unbalanced: number;
}) {
  return (
    <Help title="Weighting diagnostics">
      <p>
        A logistic regression, a standard model for yes or no outcomes, gives each person a <strong>propensity score</strong>: their estimated chance of
        getting {arms[0]?.name ?? "the treatment"} rather than {arms[1]?.name ?? "the comparator"}, given their
        covariates. Each person is then weighted so the two arms look alike. These tiles say whether that worked.
      </p>
      <p>
        <strong>Propensity outside 0.05 to 0.95</strong>: {(outside * 100).toFixed(0)}% of people. A score near 0 or 1
        means the person had almost no chance of the other drug, so there is no one comparable in the other arm.
        Near 0% is what you want.
      </p>
      <p>
        <strong>Weights</strong>: {two(weightMin)} to {two(weightMax)}. Stabilized weights average near 1. They are
        truncated at the 1st and 99th percentiles so a few extreme people cannot dominate the result.
      </p>
      <p>
        <strong>Effective sample size</strong>: {fmt(Math.round(effective[0]))} vs {fmt(Math.round(effective[1]))}
        {arms.length === 2 && (
          <>
            , against {fmt(arms[0].persons)} and {fmt(arms[1].persons)} actual people
          </>
        )}
        . It is how many unweighted people the weighted arm is worth (Kish&apos;s formula). A big drop means a few
        heavy weights carry the estimate.
      </p>
      <p>
        <strong>Unbalanced after weighting</strong>: {fmt(unbalanced)} covariates with a standardized mean difference
        of 0.1 or more. Zero is what you want; the table below shows each one.
      </p>
    </Help>
  );
}

export function BalanceHelp({ balance }: { balance: { covariate: string; smd_before: number; smd_after: number }[] }) {
  const worst = balance.reduce<(typeof balance)[number] | null>(
    (m, b) => (!m || Math.abs(b.smd_before) > Math.abs(m.smd_before) ? b : m),
    null,
  );
  const unbalanced = balance.filter((b) => Math.abs(b.smd_after) >= 0.1).length;
  return (
    <Help title="Covariate balance">
      <p>
        One row per covariate in the propensity model: age, sex, prior conditions, and the latest measurements
        (such as blood pressure or kidney function) before time zero. A missing measurement gets its own 0/1
        &ldquo;missing&rdquo; row, since being unmeasured can itself carry information.
      </p>
      <p>
        The <strong>standardized mean difference</strong> (SMD) is the gap between the arms&apos; averages, divided by
        the covariate&apos;s spread. Below 0.1 in absolute value is the usual threshold for balanced. Positive means
        higher in the treatment arm.
      </p>
      {worst && (
        <p>
          Before weighting, the biggest gap is {label(worst.covariate)} at {worst.smd_before.toFixed(3)}; after, it is{" "}
          {worst.smd_after.toFixed(3)}. {unbalanced === 0
            ? `All ${fmt(balance.length)} covariates are under 0.1 after weighting.`
            : `${fmt(unbalanced)} of ${fmt(balance.length)} are still at 0.1 or more, shown in bold.`}
        </p>
      )}
      <p>
        Balance only covers what was measured. A cause of both drug choice and outcome that is not in this list stays
        unadjusted; the negative controls at the bottom look for signs of that. Covariates too rare to fit (fewer than
        5 people with one of their values) are dropped and listed under the table.
      </p>
    </Help>
  );
}

export function RisksHelp({
  treatment,
  comparator,
  weighted,
  bootstrap,
}: {
  treatment: string;
  comparator: string;
  weighted: Risk[];
  bootstrap: Record<string, Interval>;
}) {
  const last = weighted[weighted.length - 1];
  const interval = last ? bootstrap[`risk_difference_${last.day}`] : undefined;
  const includesZero = interval && interval.low !== null && interval.high !== null && interval.low <= 0 && interval.high >= 0;
  return (
    <Help title="Risk of the outcome">
      <p>
        The share of each arm that had the outcome by each day after time zero, estimated with the Kaplan-Meier
        method. It handles people followed for different lengths of time, counting each person only while they are
        still being followed.
      </p>
      <p>
        <strong>Crude</strong> is the raw comparison. <strong>Weighted</strong> uses the propensity weights, an
        estimate of what would have happened had both arms had the same mix of covariates.
      </p>
      {last && (
        <p>
          By day {fmt(last.day)}, the weighted risk is {pct(last.risk_treatment)} on {treatment} and{" "}
          {pct(last.risk_comparator)} on {comparator}, a difference of {signed(last.risk_difference)}
          {interval && interval.low !== null && interval.high !== null && (
            <>
              {" "}
              (95% interval {signed(interval.low)} to {signed(interval.high)})
            </>
          )}
          . {includesZero && "The interval includes zero, so the data cannot tell the arms apart at that day."}
        </p>
      )}
      <p>
        The <strong>difference</strong> is {treatment} minus {comparator}: positive means more outcomes on{" "}
        {treatment}. Its 95% confidence interval (CI) comes from the bootstrap: the whole analysis rerun on resamples
        of the people, keeping the middle 95% of results.
      </p>
    </Help>
  );
}

export function HazardHelp({
  treatment,
  comparator,
  hr,
  robust,
  boot,
  crude,
  used,
  notEstimable,
}: {
  treatment: string;
  comparator: string;
  hr: number | null;
  robust: [number, number] | null;
  boot: Interval | null;
  crude: number | null;
  used: number;
  notEstimable: number;
}) {
  const includesOne = robust !== null && robust[0] <= 1 && robust[1] >= 1;
  return (
    <Help title="Hazard ratio">
      <p>
        The <strong>hazard ratio</strong> (HR) summarizes the gap between the arms in one number: the rate of the
        outcome on {treatment} divided by the rate on {comparator}, from a weighted Cox model. Below 1 means a lower
        rate on {treatment}; 1 means no difference. The model assumes the ratio stays the same over time.
      </p>
      {hr === null ? (
        <p>No hazard ratio here: one arm had no events, so the ratio would be 0 or infinite.</p>
      ) : (
        <p>
          The weighted HR is {two(hr)}
          {robust && (
            <>
              , with a robust 95% confidence interval (CI) of {two(robust[0])} to {two(robust[1])}.{" "}
              {includesOne
                ? "The interval includes 1, so these data are consistent with no difference between the drugs."
                : "The interval excludes 1. Check the negative controls before reading anything into it."}
            </>
          )}
          {!robust && "."}
        </p>
      )}
      <p>
        Two intervals, two methods. The <strong>robust</strong> (sandwich) interval adjusts the error with a formula.
        The <strong>bootstrap</strong> reruns everything from the propensity score on, over {fmt(used)} usable
        resamples of the people
        {boot && boot.low !== null && boot.high !== null && <> (giving {two(boot.low)} to {two(boot.high)})</>}, so it
        also carries the propensity model&apos;s own uncertainty. {fmt(notEstimable)} resamples were not estimable,
        for example because a resample lost every person with some covariate pattern.
      </p>
      {crude !== null && (
        <p>
          The <strong>crude</strong> HR, {two(crude)}, is the same model without weights. The distance between crude
          and weighted shows how much the covariates were skewing the raw comparison.
        </p>
      )}
    </Help>
  );
}

export function ControlsHelp({
  controls,
}: {
  controls: { name: string; not_estimable: string | null; excludes_null: boolean }[];
}) {
  const excluding = controls.filter((c) => c.excludes_null);
  const skipped = controls.filter((c) => c.not_estimable).length;
  return (
    <Help title="Negative controls">
      <p>
        Outcomes neither drug plausibly causes, such as {label(controls[0]?.name ?? "viral_sinusitis")}, run through
        the same eligibility, weighting, and Cox model. Each gets its own eligibility (no prior case of that
        outcome), so the person counts differ from the main analysis.
      </p>
      <p>
        Their hazard ratios (HR) should sit near 1. An interval that excludes 1 points to confounding the weights
        did not remove, or to chance, which grows with the number of controls.
      </p>
      <p>
        Here {fmt(excluding.length)} of {fmt(controls.length)} intervals exclude 1
        {excluding.length > 0 && <> ({excluding.map((c) => label(c.name)).join(", ")}, in bold)</>}
        {skipped > 0 && <>, and {fmt(skipped)} could not be estimated</>}.
      </p>
      <p>
        These use the robust 95% confidence interval (CI) only, with no bootstrap. Each protocol file lists its
        controls, with comments on the conditions left out because of a known or published link to either drug.
      </p>
    </Help>
  );
}
