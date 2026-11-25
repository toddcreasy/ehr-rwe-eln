import { Help, Term } from "../help";

// Help notes for the synthetic data page. Facts come from docs/modules/synthetic_data.md,
// docs/synthetic_data_methodology.md, and src/ehr_rwe_eln/synth/; the numbers come from the
// releases and monitor run on screen, so the notes stay true as releases are added.

// Each spec's name in words, as plain text for the help panel's title, and as the heading on the
// page, where an acronym can be a hover term. A spec not listed shows its file name.
const SPECS: Record<string, { title: string; heading: React.ReactNode }> = {
  person_summary: { title: "Person summary", heading: "Person summary" },
  trial_lisinopril_amlodipine_ckd: {
    title: "Trial table: lisinopril against amlodipine",
    heading: (
      <>
        Trial table: lisinopril against amlodipine, <Term t="CKD" /> stage 3 or worse
      </>
    ),
  },
};
const specTitle = (spec: string) => SPECS[spec]?.title ?? spec.replaceAll("_", " ");
export const specHeading = (spec: string) => SPECS[spec]?.heading ?? spec.replaceAll("_", " ");

type Release = {
  release_id: number;
  created_at: string;
  method: string;
  epsilon: number;
  source_rows: number;
  holdout_rows: number | null;
  withdrawn_at: string | null;
  column_tvd_mean: number | null;
  pair_tvd_mean: number | null;
  pair_tvd_floor: number | null;
  utility_auc: number | null;
  utility_auc_real: number | null;
  membership_auc: number | null;
  trial_covers_real: number | null;
  trial_spurious: number | null;
};

type MonitorRun = { finished_at: string; releases_checked: number; flags: unknown[] };
type Monitor = { latest: MonitorRun & { skipped: boolean }; last_evaluated: MonitorRun | null } | null;

const fmt = (n: number) => n.toLocaleString("en-US");
const num = (n: number) => n.toFixed(3);
const pct = (n: number) => `${(n * 100).toFixed(0)}%`;
const day = (iso: string) => new Date(iso).toLocaleString("en-US", { dateStyle: "medium", timeStyle: "short" });

// Each synthesizer's short name, and the glossary term that defines it when it has one.
const NAMES: Record<string, { short: string; term?: "VAE" | "MST" | "AIM" }> = {
  bayes_net: { short: "Bayesian network" },
  independent: { short: "Independent columns" },
  vae: { short: "VAE", term: "VAE" },
  mst: { short: "MST", term: "MST" },
  aim: { short: "AIM", term: "AIM" },
};
const name = (m: string) => {
  const t = NAMES[m]?.term;
  return t ? <Term t={t} /> : (NAMES[m]?.short ?? m);
};

const ABOUT: Record<string, React.ReactNode> = {
  bayes_net:
    "each column gets a noisy histogram (a count of people per value) together with the columns it depends on, as declared in the spec; new rows are sampled from those counts.",
  independent:
    "a baseline that keeps each column on its own and loses every relationship between them. A release that scores like this one is useless.",
  vae: (
    <>
      a small neural network that learns to compress each row and rebuild it, trained with <Term t="DP-SGD" />, which
      adds noise at every training step.
    </>
  ),
  mst: (
    <>
      the method that won the 2018 <Term t="NIST" /> synthetic data contest. It measures every column, picks a tree of
      column pairs, measures those, and samples from a model fitted to them.
    </>
  ),
  aim: (
    <>
      the successor to <Term t="MST" />, from the same research group. It is told which column combinations the analyses will read
      and spends its budget in rounds, each measuring the one the current model fits worst.
    </>
  ),
};

const short = (m: string) => NAMES[m]?.short ?? m;
const label = (r: Release) => `release ${r.release_id} (${short(r.method)}, epsilon ${r.epsilon})`;

function lowest(releases: Release[], key: keyof Release) {
  const with_ = releases.filter((r) => r[key] !== null);
  return with_.length ? with_.reduce((a, b) => ((a[key] as number) <= (b[key] as number) ? a : b)) : null;
}

// A small heading inside a note, for the longer ones with sections.
const Head = ({ children }: { children: React.ReactNode }) => (
  <h3 className="mt-1 text-xs font-semibold tracking-wide text-foreground uppercase">{children}</h3>
);

export function PageHelp({ releases }: { releases: Release[] | null }) {
  const epsilons = releases ? [...new Set(releases.map((r) => r.epsilon))].sort((a, b) => a - b) : [];
  return (
    <Help page title="Synthetic data releases">
      <Head>Why run it</Head>
      <p>
        Health records with real people in them are shared under controlled access: a researcher applies, and a
        committee checks the use against what the participants agreed to. This page treats the project&apos;s{" "}
        <Term t="OMOP" /> database as if it were such a source.
      </p>
      <p>
        A synthetic release is a made-up table with the same columns and, as far as possible, the same patterns. Each
        one is generated under <Term t="DP">differential privacy</Term>, a mathematical guarantee that what is
        released barely changes whether or not any one person&apos;s data was used. Teams can then build and test
        analysis code against it without seeing anyone in the source. The checks on each release are written for a
        reviewer such as a <Term t="DAC">data access committee</Term>, who decides whether a dataset may be shared.
      </p>

      <Head>Where the data comes from</Head>
      <p>
        <Term t="Synthea" />, an open-source simulator, generates 23,421 people who never existed. The project
        converts their records to the OMOP <Term t="CDM">Common Data Model</Term> v5.4. No real patient data is used anywhere.
      </p>
      <p>
        A spec file names the source table, its columns, and the fixed range of every column. Ranges are written
        before the data is read, since a range taken from the data would leak on its own (the top edge would be the
        oldest person&apos;s age). Ages come out in ten-year bins, the last one &ldquo;90 or older.&rdquo; There are
        two specs:
      </p>
      <p>
        <strong>Person summary</strong>: one row per person, 21 columns. Age, sex, race, ethnicity, whether each of
        eight conditions and four drugs was ever recorded, the latest of four measurements (blood pressure, body mass index, kidney function, and average blood sugar), and death.
        30% of people are held out of every release to test it against.
      </p>
      <p>
        <strong>Trial table</strong>: the analysis table of the trial emulation page&apos;s trial of lisinopril
        against amlodipine, with chronic kidney disease stage 3 or worse as the outcome. 1,890 people and 26 outcome
        events, too few to hold any out.
      </p>
      <p>
        Five synthesizers make releases: a Bayesian network (each column measured with the columns it depends on), a{" "}
        <Term t="VAE" /> (a small neural network), <Term t="MST" />, the method that won the 2018 <Term t="NIST" />{" "}
        synthetic data contest, <Term t="AIM" />, MST&apos;s successor from the same group, and an
        independent-columns baseline that keeps no relationships at all.
      </p>
      <p>
        Each release has a <strong>privacy budget</strong>, epsilon: a bound on how much any one person can change
        what is released. Smaller is more private and noisier.
        {epsilons.length > 0 && ` The releases here use epsilon ${epsilons.join(", ")}.`}
      </p>
      <p>
        Each release is stored in the app&apos;s database with its provenance: the spec as run, each step&apos;s
        privacy spend, the source, the seed, and the code version. A data card for each one is rendered from that
        record and its reports.
      </p>

      <Head>What each release is checked for</Head>
      <p>
        <strong>Fidelity</strong>: does each column, and each pair of columns, look like the real data?{" "}
        <strong>Utility</strong>: does a model trained on the release predict death in real held-out people as well
        as one trained on real data? <strong>Privacy risk</strong>: can simple attacks tell the people it learned
        from apart from people it never saw? <strong>Trial parity</strong>: does the trial&apos;s own analysis, run
        on the release, give the real answer?
      </p>
      <p>
        These reports read the real source, so they are not covered by differential privacy. They are for internal
        review and never leave with a release.
      </p>

      <Head>How to read it</Head>
      <p>
        The line above the tables says when privacy was last checked and whether any release has drifted. Each table
        is one spec; click a row to read that release&apos;s data card below. Each &ldquo;?&rdquo; explains the part
        next to it.
      </p>
      <p>
        These releases are fit for building and testing pipelines, not for reporting estimates. On the small trial,
        they often show effects the real data does not.
      </p>
      <p>Synthetic data, for research and demonstration only.</p>
    </Help>
  );
}

export function MonitorHelp({ monitor }: { monitor: Monitor }) {
  const run = monitor?.last_evaluated;
  return (
    <Help title="Scheduled privacy check">
      <p>
        Once a day a scheduled job reruns the privacy attacks on every release that has held-out people. A{" "}
        <strong>membership inference</strong> attack tries to tell whether a given person was in the data a release
        learned from.
      </p>
      <p>
        The attacks are seeded, so on unchanged data and code they give the same answer. Each run fingerprints the
        source tables and the synthesizer code and reruns the attacks only if one changed: a rebuild, new lab results
        written to the <Term t="OMOP" /> tables, or new code. Otherwise it records a skipped
        run, which is what &ldquo;sources and code unchanged&rdquo; means.
      </p>
      <p>
        A release is flagged when its membership <Term t="AUC" /> (0.5 is a coin flip) or its share of
        synthetic rows nearest a training person moves more than halfway from chance toward what a plain copy of the
        training data scores. For the person summary that is 0.575 and 56.5%, per the methodology. A flag is a
        reason to investigate and maybe withdraw the release, not proof of a leak.
      </p>
      <p>
        {monitor === null
          ? "No check has run yet."
          : run
            ? `The last full check, ${day(run.finished_at)}, covered ${fmt(run.releases_checked)} releases and flagged ${fmt(run.flags.length)}.`
            : `The last run, ${day(monitor.latest.finished_at)}, was skipped and no full check is on record.`}{" "}
        Trial parity is not rerun on the schedule: it measures how a method behaves, not drift.
      </p>
    </Help>
  );
}

export function ReleaseTableHelp({ spec, releases }: { spec: string; releases: Release[] }) {
  const methods = [...new Set(releases.map((r) => r.method))];
  const epsilons = [...new Set(releases.map((r) => r.epsilon))].sort((a, b) => a - b);
  const withdrawn = releases.filter((r) => r.withdrawn_at !== null);
  const first = releases[0];
  const floor = releases.find((r) => r.pair_tvd_floor !== null)?.pair_tvd_floor ?? null;
  const bestPair = lowest(releases, "pair_tvd_mean");
  const underFloor = floor === null ? [] : releases.filter((r) => r.pair_tvd_mean !== null && r.pair_tvd_mean < floor);
  const holdout = releases.some((r) => r.membership_auc !== null);
  const real = releases.find((r) => r.utility_auc_real !== null)?.utility_auc_real ?? null;
  const utility = releases.filter((r) => r.utility_auc !== null);
  const bestUtility = utility.length ? utility.reduce((a, b) => ((a.utility_auc as number) >= (b.utility_auc as number) ? a : b)) : null;
  const membership = releases.map((r) => r.membership_auc).filter((v): v is number => v !== null);
  const trial = releases.filter((r) => r.trial_spurious !== null);
  const spurious = trial.filter((r) => (r.trial_spurious as number) > 0);
  const worst = spurious.length ? spurious.reduce((a, b) => ((a.trial_spurious as number) >= (b.trial_spurious as number) ? a : b)) : null;
  const allCover = trial.filter((r) => r.trial_covers_real === 1 && r.trial_spurious === 0);

  return (
    <Help title={`Releases: ${specTitle(spec)}`}>
      <Head>What a row is</Head>
      <p>
        One synthetic release of this table: {fmt(releases.length)} so far. Click a row to read its data card below.
        {first &&
          ` Each learned from ${fmt(first.source_rows)} people` +
            (first.holdout_rows ? `; ${fmt(first.holdout_rows)} more were held out to test it.` : ".")}{" "}
        <strong>Rows</strong> is a noisy count, not the true one.
      </p>
      <p>
        <strong>Epsilon</strong> is the privacy budget: how much any one person can change what is released. Smaller
        is more private and noisier. Here: {epsilons.join(", ")}.
      </p>
      <p>
        <strong>Method</strong> is the synthesizer.{" "}
        {methods.map((m) => (
          <span key={m}>
            {name(m)}: {ABOUT[m] ?? ""}{" "}
          </span>
        ))}
      </p>
      {withdrawn.length > 0 ? (
        <p>
          <strong>Withdrawn</strong> ({withdrawn.map((r) => r.release_id).join(", ")}): a flaw was found after
          release. It keeps its record and reports for review, can no longer be exported, and its card tells anyone
          holding a copy to delete it.
        </p>
      ) : (
        <p>
          A release found to be flawed later is marked <strong>withdrawn</strong> here and can no longer be exported.
          None in this table is.
        </p>
      )}

      <Head>Fidelity</Head>
      <p>
        <strong>Column <Term t="TVD" /></strong> is how far each column&apos;s distribution in the
        release is from the real one, averaged over columns: 0 is identical, 1 is no overlap.{" "}
        <strong>Pair TVD</strong> is the same for every pair of columns, which shows whether relationships survived.
      </p>
      {floor !== null ? (
        <p>
          The <strong>floor</strong> in parentheses, {num(floor)}, is the pair TVD between two real samples (held-out
          people against training people): how far apart real data is from itself.
          {bestPair && ` The closest on pairs is ${label(bestPair)} at ${num(bestPair.pair_tvd_mean as number)}.`}
          {underFloor.length > 0 &&
            ` ${underFloor.length === 1 ? "Release" : "Releases"} ${underFloor.map((r) => r.release_id).join(", ")} ${underFloor.length === 1 ? "comes" : "come"} in under the floor. That can happen: a release is compared with the training people it was fitted to, while the floor compares two different samples.`}
        </p>
      ) : (
        <p>
          This table keeps no held-out people, so there is no floor to read the TVD against.
          {bestPair && ` The lowest pair TVD is ${label(bestPair)} at ${num(bestPair.pair_tvd_mean as number)}.`}
        </p>
      )}

      {holdout && (
        <>
          <Head>Utility and privacy</Head>
          <p>
            <strong>Utility <Term t="AUC" /></strong>: a model predicting death, trained on the release and
            scored on held-out real people. 0.5 is guessing, 1 is perfect.
            {real !== null && ` In parentheses, the same model trained on real data: ${num(real)}.`}
            {bestUtility && ` The best release is ${label(bestUtility)} at ${num(bestUtility.utility_auc as number)}.`}
          </p>
          <p>
            <strong>Membership AUC</strong>: how well an attacker tells training people from held-out people by how
            close their record sits to the release. 0.5 is a coin flip.
            {membership.length > 0 &&
              ` Here every release is between ${num(Math.min(...membership))} and ${num(Math.max(...membership))}.`}{" "}
            In the methodology&apos;s results, a plain copy of the training data scores 0.650, which is what leakage
            looks like. A failed attack bounds the risk from below; differential privacy is the guarantee.
          </p>
        </>
      )}

      {trial.length > 0 && (
        <>
          <Head>Trial parity</Head>
          <p>
            The trial emulation page&apos;s own analysis, a propensity-weighted Cox model, run on 20 more draws of
            each method and epsilon. Its answer is a <Term t="HR">hazard ratio</Term> (HR): how much faster the outcome comes on
            lisinopril than on amlodipine, where 1 means no difference. In the run of 2026-11-22 the real data gave
            1.00, with a 95% <Term t="CI">confidence interval</Term> of 0.43 to 2.32.
          </p>
          <p>
            <strong>Trial covers real</strong>: the share of draws whose interval contains the real HR.{" "}
            <strong>Spurious effect</strong> (bold when above zero): the share whose interval excludes 1, an effect
            the real data does not show.
            {worst
              ? ` ${spurious.length} of ${trial.length} releases show one in some draws, up to ${pct(worst.trial_spurious as number)} for ${label(worst)}.`
              : " No release here shows one."}
            {allCover.length > 0 &&
              ` Every draw covers the real HR with no spurious effect for ${allCover.map(label).join(", ")}.`}
          </p>
          {releases.some((r) => r.release_id === 23 && r.method === "aim") && (
            <p>
              Release 23 is kept as a warning: by itself it gives an HR of 0.14, a strong protective effect that is
              not there.
            </p>
          )}
        </>
      )}

      <Head>How to read it</Head>
      <p>
        Lower TVD means closer to the real data; utility near the real model&apos;s AUC means the release keeps the
        signal; membership near 0.5 means the attack learned nothing. Even a release that scores well here is fit for
        building and testing pipelines, not for reporting estimates.
      </p>
    </Help>
  );
}

export function CardHelp({ release }: { release: Release | undefined }) {
  return (
    <Help title="The data card">
      <p>
        A data card is the label that travels with a release: an export writes it next to the rows. It is rendered
        only from the stored release record and its reports.
        {release && (
          <>
            {" "}
            This one is for release {release.release_id}, made with {name(release.method)} at epsilon {release.epsilon} on{" "}
            {new Date(release.created_at).toLocaleDateString("en-US", { dateStyle: "medium" })}.
          </>
        )}
      </p>
      <p>
        <strong>At a glance</strong> gives the method, the privacy budget (epsilon, plus delta for some methods, a
        small chance that the epsilon bound fails), the noisy row count, how many people it learned from and how many
        were held out, and the seed.
      </p>
      <p>
        <strong>Intended use</strong>: building, testing, and demonstrating analyses and pipelines, not estimates that
        will be reported, and never clinical decisions. It also names any group whose share of the release is off by
        more than 20% and by more than chance explains, with an instruction not to study that group in this release.
      </p>
      <p>
        The rest covers the source&apos;s data use limitations, how the release was made, where its privacy budget
        went, and the fidelity, utility, subgroup, trial parity, and privacy risk results, then its limitations.
      </p>
      <p>
        The seed lets a release be remade exactly. That is acceptable only because the source is synthetic: anyone
        who knows the seed could regenerate the noise and subtract it.
        {release?.withdrawn_at && " This release is withdrawn, so the card opens with the reason and asks every holder to delete their copy."}
      </p>
    </Help>
  );
}
