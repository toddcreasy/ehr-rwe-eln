"use client";

import { useCallback, useEffect, useState } from "react";
import Spinner from "../spinner";
import {
  CriteriaHelp,
  DecisionHelp,
  EvidenceHelp,
  ExomiserHelp,
  HeaderHelp,
  HistoryHelp,
  ListHelp,
  PageHelp,
  PhenotypeHelp,
  ProposalsHelp,
  SetsHelp,
  SourcesHelp,
} from "./help";

type VariantSet = { variant_set: string; run_id: number; created_at: string; variants: number; decided: number };

type Row = {
  variant_id: string;
  gene: string;
  hgvsc: string | null;
  hgvsp: string | null;
  points: number | null;
  classification: string;
  expected: string | null;
  proposals: number;
  decision: string | null;
  curator: string | null;
  decided_at: string | null;
};

type Criterion = { code: string; label: string; strength: string; reason: string; proposal_id?: number };
type NotAssessed = { code: string; reason: string; decided?: boolean };
type Proposal = {
  proposal_id: number;
  criterion: string;
  strength: string;
  pmid: string;
  quote: string;
  rationale: string;
  verified: boolean;
  rejected_why: string | null;
};
type Decision = {
  decision_id: number;
  curator: string;
  decided_at: string;
  accepted: number[];
  criteria: Criterion[];
  points: number | null;
  computed: string;
  classification: string;
  note: string | null;
};
type Detail = Row & {
  variant_set: string;
  run_id: number;
  run_at: string;
  sources: Record<string, unknown>;
  evidence: {
    vep?: { transcript?: string; refseq?: string; exon?: string | null; intron?: string | null; consequences?: string[] };
    gnomad?: { ac: number; an: number; af: number | null; faf95?: number | null; faf95_group?: string | null } | null;
  };
  met: Criterion[];
  not_assessed: NotAssessed[];
  proposals: Proposal[];
  decisions: Decision[];
  phenotype: { hpo_release: string; gene_group: string[]; subjects: number; percentiles: number[] } | null;
  exomiser: {
    data_release: string;
    gene: string;
    subjects: number;
    ranks: number[];
    genes: number[];
    auc: number | null;
  } | null;
};
type Score = { criteria: Criterion[]; points: number | null; classification: string };

const CLASSES = ["Pathogenic", "Likely pathogenic", "Uncertain significance", "Likely benign", "Benign"];
const FILTERS = {
  all: "All",
  proposals: "With proposals",
  undecided: "Undecided",
  differs: "Rules and panel in different tiers",
} as const;
type Filter = keyof typeof FILTERS;

const muted = "text-zinc-600 dark:text-zinc-400";
const box = "rounded-lg border-[1.5px] border-grid p-4";
const h3 = "font-medium text-zinc-900 dark:text-zinc-100";
const input = "rounded border border-zinc-300 bg-white px-2 py-1 text-sm dark:border-zinc-700 dark:bg-zinc-950";

const json = (res: Response) =>
  res.ok ? res.json() : res.json().then((b) => Promise.reject(new Error(b.detail ?? `${res.status}`)), () => Promise.reject(new Error(`${res.status}`)));
const name = (r: { gene: string; hgvsc: string | null; hgvsp: string | null; variant_id: string }) =>
  `${r.gene} ${r.hgvsc ?? r.variant_id}${r.hgvsp ? ` (${r.hgvsp})` : ""}`;
const points = (p: number | null) => (p === null ? "stand-alone" : `${p > 0 ? "+" : ""}${p} points`);
// ClinVar writes "Likely_benign", the Evidence Repository "Likely Benign", the rules "Likely benign".
const spelled = (c: string) => c.toLowerCase().replaceAll("_", " ");
// The three tiers the docs score agreement in (curation/curate.py TIERS).
const tier = (c: string) => {
  const k = spelled(c);
  return k.includes("pathogenic") ? "P/LP" : k.includes("benign") ? "B/LB" : k.includes("uncertain") ? "VUS" : k;
};
const when = (t: string) => new Date(t).toLocaleString("en-US", { dateStyle: "medium", timeStyle: "short" });

function readCurator() {
  try {
    return localStorage.getItem("curator") ?? "";
  } catch {
    return "";
  }
}

function Criteria({ items }: { items: Criterion[] }) {
  if (!items.length) return <p className={`text-sm ${muted}`}>None.</p>;
  return (
    <ul className="flex flex-col gap-1 text-sm">
      {items.map((c) => (
        <li key={c.label}>
          <span className="font-medium">{c.label}</span> <span className={muted}>{c.reason}</span>
          {c.proposal_id && <span className="text-xs text-zinc-500"> (accepted from literature)</span>}
        </li>
      ))}
    </ul>
  );
}

function Evidence({ v }: { v: Detail }) {
  const vep = v.evidence.vep;
  const g = v.evidence.gnomad;
  return (
    <section data-help className={`${box} flex flex-col gap-2 text-sm`}>
      <h3 className={`${h3} flex items-center gap-2`}>
        Evidence <EvidenceHelp gnomad={g} />
      </h3>
      <p>
        <span className={muted}>Consequence (Ensembl VEP, MANE Select): </span>
        {vep?.consequences?.join(", ").replaceAll("_", " ") ?? "none"}
        {vep?.exon && `, exon ${vep.exon}`}
        {vep?.intron && `, intron ${vep.intron}`}
        {vep?.refseq && <span className={muted}> on {vep.refseq}</span>}
      </p>
      <p>
        <span className={muted}>gnomAD v4: </span>
        {!g || g.ac === 0
          ? "absent"
          : `${g.ac.toLocaleString("en-US")} of ${g.an.toLocaleString("en-US")} alleles, AF ${g.af?.toExponential(2)}` +
            (g.faf95 ? `, FAF95 ${g.faf95.toExponential(2)} (${g.faf95_group})` : "")}
      </p>
    </section>
  );
}

function Proposals({
  v,
  accepted,
  toggle,
}: {
  v: Detail;
  accepted: Set<number>;
  toggle: (id: number) => void;
}) {
  const ruled = new Set(v.met.map((c) => c.code));
  if (!v.proposals.length)
    return <p className={`text-sm ${muted}`}>No literature proposals for this variant.</p>;
  return (
    <ul className="flex flex-col gap-3">
      {v.proposals.map((p) => {
        const blocked = !p.verified || ruled.has(p.criterion);
        return (
          <li key={p.proposal_id} className={`flex gap-3 text-sm ${p.verified ? "" : "opacity-60"}`}>
            <input
              type="checkbox"
              className="mt-1"
              checked={accepted.has(p.proposal_id)}
              disabled={blocked}
              onChange={() => toggle(p.proposal_id)}
              aria-label={`Accept ${p.criterion} from PMID ${p.pmid}`}
            />
            <div className="flex flex-col gap-1">
              <div>
                <span className="font-medium">
                  {p.criterion} {p.strength}
                </span>{" "}
                <a
                  className="underline"
                  href={`https://pubmed.ncbi.nlm.nih.gov/${p.pmid}/`}
                  target="_blank"
                  rel="noreferrer"
                >
                  PMID {p.pmid}
                </a>
                {!p.verified && <span className={muted}> rejected: {p.rejected_why}</span>}
                {p.verified && ruled.has(p.criterion) && <span className={muted}> already met by the rules</span>}
              </div>
              <blockquote className="border-l-2 border-zinc-300 pl-3 dark:border-zinc-700">{p.quote}</blockquote>
              <p className={muted}>{p.rationale}</p>
            </div>
          </li>
        );
      })}
    </ul>
  );
}

function DecisionForm({ v, onSaved }: { v: Detail; onSaved: () => void }) {
  const [accepted, setAccepted] = useState<Set<number>>(new Set());
  const [score, setScore] = useState<Score | null>(null);
  const [choice, setChoice] = useState("");
  const [note, setNote] = useState("");
  const [curator, setCurator] = useState(readCurator);
  const [message, setMessage] = useState("");
  const [enabled, setEnabled] = useState(true);

  useEffect(() => {
    fetch("/api/curation/decisions/enabled")
      .then(json)
      .then(setEnabled)
      .catch(() => {});
  }, []);

  useEffect(() => {
    fetch("/api/curation/score", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ run_id: v.run_id, variant_id: v.variant_id, accepted: [...accepted] }),
    })
      .then(json)
      .then((s: Score) => {
        setScore(s);
        setChoice(s.classification);
      })
      .catch((e) => setMessage(e.message));
  }, [v.run_id, v.variant_id, accepted]);

  function toggle(id: number) {
    setAccepted((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function save() {
    try {
      localStorage.setItem("curator", curator);
    } catch {}
    setMessage("");
    fetch("/api/curation/decisions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        run_id: v.run_id,
        variant_id: v.variant_id,
        accepted: [...accepted],
        curator,
        classification: choice,
        note: note || null,
      }),
    })
      .then(json)
      .then(() => {
        setNote("");
        onSaved();
      })
      .catch((e) => setMessage(`Not saved: ${e.message}`));
  }

  const differs = score !== null && choice !== score.classification;
  return (
    <>
      <section data-help className={`${box} flex flex-col gap-3`}>
        <h3 className={`${h3} flex items-center gap-2`}>
          Literature proposed by Claude{" "}
          <ProposalsHelp
            verified={v.proposals.filter((p) => p.verified).length}
            rejected={v.proposals.filter((p) => !p.verified).length}
          />
        </h3>
        <p className={`text-xs ${muted}`}>
          Each verified claim quotes a passage that was sent to the model from that paper. Proposals change nothing until
          you accept them here.
        </p>
        <Proposals v={v} accepted={accepted} toggle={toggle} />
      </section>

      <section data-help className={`${box} flex flex-col gap-3 text-sm`}>
        <h3 className={`${h3} flex items-center gap-2`}>
          Decision <DecisionHelp score={score} />
        </h3>
        {score && (
          <p>
            With the accepted evidence: <span className="font-medium">{score.classification}</span>{" "}
            <span className={muted}>({points(score.points)})</span>
          </p>
        )}
        <div className="flex flex-wrap items-center gap-3">
          <label className="flex items-center gap-2">
            <span className={muted}>Class</span>
            <select className={input} value={choice} onChange={(e) => setChoice(e.target.value)}>
              {CLASSES.map((c) => (
                <option key={c}>{c}</option>
              ))}
            </select>
          </label>
          <label className="flex items-center gap-2">
            <span className={muted}>Curator</span>
            <input className={input} value={curator} onChange={(e) => setCurator(e.target.value)} placeholder="your name" />
          </label>
        </div>
        <textarea
          className={`${input} min-h-16`}
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder={differs ? "Why this class and not the scored one (required)" : "Note (optional)"}
        />
        <button
          onClick={save}
          disabled={!enabled || !curator.trim() || (differs && !note.trim())}
          className="w-fit rounded bg-zinc-900 px-4 py-2 text-white disabled:opacity-40 dark:bg-zinc-100 dark:text-black"
        >
          Record decision
        </button>
        {!enabled && (
          <p className={muted}>
            Recording is off on the public demo, where anyone could write. The form still rescores; run the app locally
            to record decisions.
          </p>
        )}
        {message && <p>{message}</p>}
      </section>
    </>
  );
}

function History({ decisions }: { decisions: Decision[] }) {
  if (!decisions.length) return <p className={`text-sm ${muted}`}>No decisions yet.</p>;
  return (
    <ol className="flex flex-col gap-2 text-sm">
      {decisions.map((d) => (
        <li key={d.decision_id}>
          <span className="font-medium">{d.classification}</span>{" "}
          <span className={muted}>
            by {d.curator}, {when(d.decided_at)}; scored {d.computed} ({points(d.points)})
            {d.accepted.length > 0 && `, ${d.accepted.length} literature claim${d.accepted.length > 1 ? "s" : ""} accepted`}
          </span>
          {d.note && <p className={muted}>{d.note}</p>}
        </li>
      ))}
    </ol>
  );
}

function Phenotypes({ p }: { p: NonNullable<Detail["phenotype"]> }) {
  const high = p.percentiles.filter((x) => x >= 90).length;
  return (
    <section data-help className={`${box} flex flex-col gap-2 text-sm`}>
      <h3 className={`${h3} flex items-center gap-2`}>
        Carriers&apos; phenotypes (context, not evidence){" "}
        <PhenotypeHelp release={p.hpo_release} subjects={p.subjects} high={high} />
      </h3>
      {p.subjects === 0 ? (
        <p className={muted}>No one in the synthetic genomics study carries this variant.</p>
      ) : (
        <>
          <p>
            {p.subjects.toLocaleString("en-US")} {p.subjects === 1 ? "carrier" : "carriers"} in the synthetic genomics
            study; {high} in the top 10% of all study subjects for phenotype match with {p.gene_group.join(", ")}.
          </p>
          {p.subjects <= 40 && (
            <p className={muted}>Percentiles: {p.percentiles.map((x) => Math.round(x)).join(", ")}</p>
          )}
        </>
      )}
      <p className={`text-xs ${muted}`}>
        Not scored as PP4: PP4 is judged for one patient under each expert panel&apos;s rules, which this score does not
        follow, and the score finds the right gene group only about as well as knowing who has the condition. This
        service/product is using the Human Phenotype Ontology (release {p.hpo_release}). Find out more at{" "}
        <a className="underline" href="http://www.human-phenotype-ontology.org" target="_blank" rel="noreferrer">
          http://www.human-phenotype-ontology.org
        </a>
        .
      </p>
    </section>
  );
}

function median(xs: number[]) {
  const s = [...xs].sort((a, b) => a - b);
  const m = Math.floor(s.length / 2);
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
}

function Exomiser({ e }: { e: NonNullable<Detail["exomiser"]> }) {
  const first = e.ranks.filter((r) => r === 1).length;
  return (
    <section data-help className={`${box} flex flex-col gap-2 text-sm`}>
      <h3 className={`${h3} flex items-center gap-2`}>
        Carriers&apos; Exomiser rank (context, not evidence){" "}
        <ExomiserHelp release={e.data_release} gene={e.gene} auc={e.auc} />
      </h3>
      {e.subjects === 0 ? (
        <p className={muted}>No one in the synthetic genomics study carries this variant.</p>
      ) : (
        <p>
          Exomiser&apos;s phenotype score ranks {e.gene} first for {first} of {e.subjects.toLocaleString("en-US")}{" "}
          {e.subjects === 1 ? "carrier" : "carriers"}, median rank {median(e.ranks)} of about {median(e.genes)} panel
          genes each carrier has a variant in.
        </p>
      )}
      {e.auc !== null && (
        <p className={muted}>
          Across the study, the score picks out {e.gene}&apos;s pathogenic carriers with AUC {e.auc.toFixed(2)} (0.5 is
          chance).
        </p>
      )}
      <p className={`text-xs ${muted}`}>
        Only the phenotype score is shown: Exomiser&apos;s variant score includes ClinVar. Not scored as PP4: PP4 is
        judged for one patient under each expert panel&apos;s rules, and this rank follows neither. Exomiser 15.1.0, data release {e.data_release}.
      </p>
    </section>
  );
}

function VariantDetail({ v, onSaved }: { v: Detail; onSaved: () => void }) {
  return (
    <article className="flex flex-col gap-4">
      <header data-help>
        <h2 className="flex items-center gap-2 text-lg font-semibold text-zinc-900 dark:text-zinc-100">
          {name(v)} <HeaderHelp classification={v.classification} points={v.points} expected={v.expected} />
        </h2>
        <p className={`text-sm ${muted}`}>
          {v.variant_id} (GRCh38). Rules: <span className="font-medium">{v.classification}</span> ({points(v.points)})
          {v.expected && `; expert panel: ${v.expected}`}
        </p>
      </header>

      <Evidence v={v} />

      <div data-help className="relative grid gap-4 lg:grid-cols-2">
        <div className="absolute -top-2.5 -right-2.5 rounded-full bg-card">
          <CriteriaHelp
            met={v.met}
            notAssessed={v.not_assessed.length}
            points={v.points}
            classification={v.classification}
          />
        </div>
        <section className={`${box} flex flex-col gap-2`}>
          <h3 className={h3}>Criteria the rules met</h3>
          <Criteria items={v.met} />
        </section>
        <section className={`${box} flex flex-col gap-2`}>
          <h3 className={h3}>Left to the curator</h3>
          {v.not_assessed.length ? (
            <ul className="flex flex-col gap-1 text-sm">
              {v.not_assessed.map((c) => (
                <li key={c.code + c.reason}>
                  <span className="font-medium">{c.code}</span> <span className={muted}>{c.reason}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className={`text-sm ${muted}`}>Nothing.</p>
          )}
        </section>
      </div>

      {v.phenotype && <Phenotypes p={v.phenotype} />}
      {v.exomiser && <Exomiser e={v.exomiser} />}

      <DecisionForm key={`${v.run_id} ${v.variant_id}`} v={v} onSaved={onSaved} />

      <section data-help className={`${box} flex flex-col gap-2`}>
        <h3 className={`${h3} flex items-center gap-2`}>
          History <HistoryHelp count={v.decisions.length} />
        </h3>
        <History decisions={v.decisions} />
      </section>

      <section data-help className={`${box} flex flex-col gap-1 text-xs ${muted}`}>
        <h3 className={`${h3} flex items-center gap-2`}>
          Sources <SourcesHelp />
        </h3>
        <p>
          {v.variant_set} run {v.run_id}, {when(v.run_at)}
        </p>
        {Object.entries(v.sources).map(([k, val]) => (
          <p key={k}>
            {k}: {typeof val === "object" ? JSON.stringify(val).replaceAll(/[{}"]/g, "").replaceAll(",", ", ") : String(val)}
          </p>
        ))}
        <p>Includes data from the gnomAD v4 release. Expert panel specifications and tables from ClinGen (CC0), accessed 2026-11-19.</p>
      </section>
    </article>
  );
}

export default function Curation() {
  const [sets, setSets] = useState<VariantSet[] | null>(null);
  const [runId, setRunId] = useState<number | null>(null);
  const [rows, setRows] = useState<Row[] | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const [detail, setDetail] = useState<Detail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const loadSets = useCallback(() => {
    fetch("/api/curation/sets")
      .then(json)
      .then((list: VariantSet[]) => {
        setSets(list);
        setRunId((cur) => cur ?? list.find((s) => s.variant_set === "erepo")?.run_id ?? list[0]?.run_id ?? null);
      })
      .catch((e) => setError(`Could not load curation runs (${e.message}).`));
  }, []);

  const loadRows = useCallback((run: number) => {
    fetch(`/api/curation/runs/${run}/variants`)
      .then(json)
      .then(setRows)
      .catch((e) => setError(`Could not load variants (${e.message}).`));
  }, []);

  const loadDetail = useCallback((run: number, id: string) => {
    setLoading(true);
    fetch(`/api/curation/runs/${run}/variants/${encodeURIComponent(id)}`)
      .then(json)
      .then(setDetail)
      .catch((e) => setError(`Could not load ${id} (${e.message}).`))
      .finally(() => setLoading(false));
  }, []);

  useEffect(loadSets, [loadSets]);
  useEffect(() => {
    if (runId !== null) loadRows(runId);
  }, [runId, loadRows]);

  const shown = (rows ?? []).filter(
    (r) =>
      filter === "all" ||
      (filter === "proposals" && r.proposals > 0) ||
      (filter === "undecided" && !r.decision) ||
      (filter === "differs" && r.expected !== null && tier(r.expected) !== tier(r.classification)),
  );

  function saved() {
    if (!detail) return;
    loadDetail(detail.run_id, detail.variant_id);
    loadRows(detail.run_id);
    loadSets();
  }

  return (
    <main className="mx-auto flex w-full max-w-6xl flex-1 flex-col gap-6 px-6 py-12">
      <div data-help>
        <h1 className="flex items-center gap-2 text-2xl font-semibold">
          Variant curation <PageHelp />
        </h1>
        <p className={`text-sm ${muted}`}>
          ACMG/AMP criteria the rules decided from gnomAD and Ensembl VEP with each gene&apos;s ClinGen expert panel
          thresholds, literature evidence Claude proposed with quotes checked in code, and the curator&apos;s decision
          with who and when.
        </p>
      </div>

      <p className="rounded-lg border border-zinc-300 p-4 text-sm text-zinc-900 dark:border-zinc-700 dark:text-zinc-100">
        For research and demonstration. These classifications are not for clinical use. Variants are real ClinVar
        records; the people carrying them in this project are synthetic.
      </p>

      {error && <p className="text-sm text-zinc-900 dark:text-zinc-100">{error}</p>}
      {!error && (sets === null || loading) && <Spinner />}

      {sets && sets.length === 0 && (
        <p className={`text-sm ${muted}`}>
          No curation runs yet. Run <code>uv run python scripts/curate_variants.py --set panel</code>, then reload.
        </p>
      )}

      {sets && sets.length > 0 && (
        <div data-help className="flex flex-wrap items-center gap-2 text-sm">
          {sets.map((s) => (
            <button
              key={s.run_id}
              onClick={() => {
                setDetail(null);
                setRunId(s.run_id);
              }}
              className={`rounded border px-3 py-1 ${s.run_id === runId ? "border-zinc-900 dark:border-zinc-100" : "border-zinc-300 dark:border-zinc-700"}`}
            >
              {s.variant_set}: {s.variants.toLocaleString("en-US")} variants, {s.decided} decided
            </button>
          ))}
          <select className={`${input} ml-auto`} value={filter} onChange={(e) => setFilter(e.target.value as Filter)}>
            {Object.entries(FILTERS).map(([k, label]) => (
              <option key={k} value={k}>
                {label}
              </option>
            ))}
          </select>
          <SetsHelp sets={sets} />
        </div>
      )}

      {rows && runId !== null && (
        <div className="grid gap-6 lg:grid-cols-[20rem_1fr]">
          <div data-help className="max-h-[75vh] overflow-y-auto rounded-lg border-[1.5px] border-grid">
            <p className={`flex items-center justify-between gap-2 border-b border-zinc-200 px-3 py-2 text-xs dark:border-zinc-800 ${muted}`}>
              {shown.length.toLocaleString("en-US")} shown <ListHelp shown={shown.length} total={rows.length} />
            </p>
            <ul>
              {shown.map((r) => (
                <li key={r.variant_id}>
                  <button
                    onClick={() => loadDetail(runId, r.variant_id)}
                    className={`flex w-full flex-col items-start gap-0.5 border-b border-zinc-200 px-3 py-2 text-left text-sm dark:border-zinc-800 ${detail?.variant_id === r.variant_id ? "bg-zinc-100 dark:bg-zinc-900" : "hover:bg-zinc-50 dark:hover:bg-zinc-900"}`}
                  >
                    <span className="font-medium">{name(r)}</span>
                    <span className={muted}>
                      {r.classification}
                      {r.expected && spelled(r.expected) !== spelled(r.classification) && `; panel ${r.expected}`}
                    </span>
                    <span className="text-xs text-zinc-500">
                      {r.proposals > 0 && `${r.proposals} proposed; `}
                      {r.decision ? `decided ${r.decision} by ${r.curator}` : "undecided"}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
          <div className={`transition-opacity ${loading ? "opacity-50" : ""}`}>
            {detail ? (
              <VariantDetail v={detail} onSaved={saved} />
            ) : (
              <p className={`text-sm ${muted}`}>Pick a variant.</p>
            )}
          </div>
        </div>
      )}
    </main>
  );
}
