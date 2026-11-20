"use client";

import { Fragment, useEffect, useState } from "react";
import Spinner from "../spinner";

type Release = {
  release_id: number;
  created_at: string;
  spec_name: string;
  method: string;
  epsilon: number;
  rows: number;
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

type MonitorRun = { run_id: number; finished_at: string; releases_checked: number; flags: { release_id: number; release: string; flag: string }[] };
type Monitor = { latest: MonitorRun & { skipped: boolean }; last_evaluated: MonitorRun | null } | null;

const day = (iso: string) => new Date(iso).toLocaleString("en-US", { dateStyle: "medium", timeStyle: "short" });

function MonitorStatus({ monitor }: { monitor: Monitor }) {
  if (monitor === null) {
    return (
      <p className={`text-sm ${muted}`}>
        Scheduled privacy checks have not run yet. The Compose <code>monitor</code> service runs them, or once with{" "}
        <code>uv run python -m ehr_rwe_eln.synth.monitor --once</code>.
      </p>
    );
  }
  const run = monitor.last_evaluated;
  const flags = run?.flags ?? [];
  return (
    <p className={`text-sm ${flags.length ? "font-medium text-red-800 dark:text-red-300" : muted}`}>
      Privacy last checked {day(monitor.latest.finished_at)}
      {monitor.latest.skipped && run ? `; sources and code unchanged since ${day(run.finished_at)}, when ${run.releases_checked} releases were checked` : run ? `, ${run.releases_checked} releases` : ""}.{" "}
      {flags.length
        ? `Review: ${flags.map((f) => `release ${f.release_id} (${f.release})`).join(", ")} drifted toward leakage.`
        : "No release has drifted toward leakage."}
    </p>
  );
}

const METHODS: Record<string, string> = {
  bayes_net: "Bayesian network",
  independent: "Independent columns",
  vae: "Variational autoencoder",
};

const fmt = (n: number) => n.toLocaleString("en-US");
const num = (n: number | null) => (n === null ? "" : n.toFixed(3));
const pct = (n: number | null) => (n === null ? "" : `${(n * 100).toFixed(0)}%`);

const muted = "text-zinc-600 dark:text-zinc-400";
const th = "py-1 pr-4 font-normal";
const td = "py-1 pr-4 text-right";
const row = "border-t border-zinc-200 dark:border-zinc-800";

// The data cards use only headings, paragraphs, tables, lists, **bold**, and `code`.
function Inline({ text }: { text: string }) {
  return (
    <>
      {text.split(/(\*\*[^*]+\*\*|`[^`]+`)/).map((part, i) =>
        part.startsWith("**") ? (
          <strong key={i}>{part.slice(2, -2)}</strong>
        ) : part.startsWith("`") ? (
          <code key={i} className="rounded bg-zinc-100 px-1 font-mono text-[0.9em] dark:bg-zinc-900">
            {part.slice(1, -1)}
          </code>
        ) : (
          <Fragment key={i}>{part}</Fragment>
        ),
      )}
    </>
  );
}

function Markdown({ source }: { source: string }) {
  const blocks: React.ReactNode[] = [];
  const lines = source.split("\n");
  const cells = (line: string) => line.slice(1, -1).split("|").map((c) => c.trim());
  for (let i = 0; i < lines.length; ) {
    const line = lines[i];
    if (line.startsWith("|")) {
      const table: string[] = [];
      while (i < lines.length && lines[i].startsWith("|")) table.push(lines[i++]);
      const [head, , ...body] = table;
      blocks.push(
        <div key={i} className="overflow-x-auto">
          <table className="w-full text-sm tabular-nums">
            <thead className={`text-left ${muted}`}>
              <tr>{cells(head).map((c, j) => <th key={j} className={th}><Inline text={c} /></th>)}</tr>
            </thead>
            <tbody>
              {body.map((r, k) => (
                <tr key={k} className={row}>
                  {cells(r).map((c, j) => <td key={j} className="py-1 pr-4 align-top"><Inline text={c} /></td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>,
      );
    } else if (line.startsWith("- ")) {
      const items: string[] = [];
      while (i < lines.length && lines[i].startsWith("- ")) items.push(lines[i++].slice(2));
      blocks.push(
        <ul key={i} className="list-disc pl-5 text-sm">
          {items.map((t, k) => <li key={k}><Inline text={t} /></li>)}
        </ul>,
      );
    } else {
      i++;
      if (line.startsWith("# ")) blocks.push(<h2 key={i} className="text-lg font-semibold">{line.slice(2)}</h2>);
      else if (line.startsWith("## ")) blocks.push(<h3 key={i} className="mt-2 font-medium">{line.slice(3)}</h3>);
      else if (line.trim()) blocks.push(<p key={i} className="text-sm"><Inline text={line} /></p>);
    }
  }
  return <div className="flex flex-col gap-3">{blocks}</div>;
}

function ReleaseTable({ releases, selected, onSelect }: { releases: Release[]; selected: number | null; onSelect: (id: number) => void }) {
  const trial = releases.some((r) => r.trial_spurious !== null);
  const holdout = releases.some((r) => r.membership_auc !== null);
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm tabular-nums">
        <thead className={`text-left ${muted}`}>
          <tr>
            <th className={th}>Release</th>
            <th className={th}>Method</th>
            <th className={`${th} text-right`}>Epsilon</th>
            <th className={`${th} text-right`}>Rows</th>
            <th className={`${th} text-right`}>Column TVD</th>
            <th className={`${th} text-right`}>Pair TVD (floor)</th>
            {holdout && <th className={`${th} text-right`}>Utility AUC (real)</th>}
            {holdout && <th className={`${th} text-right`}>Membership AUC</th>}
            {trial && <th className={`${th} text-right`}>Trial covers real</th>}
            {trial && <th className={`${th} text-right`}>Spurious effect</th>}
          </tr>
        </thead>
        <tbody>
          {releases.map((r) => (
            <tr
              key={r.release_id}
              onClick={() => onSelect(r.release_id)}
              className={`${row} cursor-pointer hover:bg-zinc-50 dark:hover:bg-zinc-900 ${selected === r.release_id ? "bg-zinc-100 dark:bg-zinc-900" : ""}`}
            >
              <td className="py-1 pr-4">{r.release_id}</td>
              <td className="py-1 pr-4">
                {METHODS[r.method] ?? r.method}
                {r.withdrawn_at && <span className="ml-2 rounded bg-red-100 px-1 text-xs font-medium text-red-800 dark:bg-red-950 dark:text-red-300">withdrawn</span>}
              </td>
              <td className={td}>{r.epsilon}</td>
              <td className={td}>{fmt(r.rows)}</td>
              <td className={td}>{num(r.column_tvd_mean)}</td>
              <td className={td}>
                {num(r.pair_tvd_mean)}
                {r.pair_tvd_floor !== null && <span className={muted}> ({num(r.pair_tvd_floor)})</span>}
              </td>
              {holdout && (
                <td className={td}>
                  {num(r.utility_auc)}
                  {r.utility_auc_real !== null && <span className={muted}> ({num(r.utility_auc_real)})</span>}
                </td>
              )}
              {holdout && <td className={td}>{num(r.membership_auc)}</td>}
              {trial && <td className={td}>{pct(r.trial_covers_real)}</td>}
              {trial && <td className={`${td} ${r.trial_spurious ? "font-semibold" : ""}`}>{pct(r.trial_spurious)}</td>}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function SyntheticData() {
  const [releases, setReleases] = useState<Release[] | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [card, setCard] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [monitor, setMonitor] = useState<Monitor | undefined>(undefined);

  function loadCard(id: number) {
    setSelected(id);
    setLoading(true);
    fetch(`/api/synth/releases/${id}`)
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error(`${res.status}`))))
      .then((d: { card: string }) => setCard(d.card))
      .catch((e) => setError(`Could not load release ${id} (${e.message}).`))
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    fetch("/api/synth/releases")
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error(`${res.status}`))))
      .then((list: Release[]) => {
        setReleases(list);
        if (list.length) loadCard(list[0].release_id);
      })
      .catch((e) => setError(`Could not load releases (${e.message}).`));
    fetch("/api/synth/monitor")
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error(`${res.status}`))))
      .then((m: Monitor) => setMonitor(m))
      .catch(() => setMonitor(undefined));
  }, []);

  const specs = releases ? [...new Set(releases.map((r) => r.spec_name))] : [];

  return (
    <main className="mx-auto flex w-full max-w-5xl flex-1 flex-col gap-6 px-6 py-12">
      <div>
        <h1 className="text-2xl font-semibold">Synthetic data releases</h1>
        <p className={`text-sm ${muted}`}>
          Differentially private copies of the OMOP data, each with its fidelity, utility, privacy risk, and data card.
          Pick a release to read its card.
        </p>
      </div>

      <p className="rounded-lg border border-zinc-300 p-4 text-sm text-zinc-900 dark:border-zinc-700 dark:text-zinc-100">
        Synthetic Synthea patients only. These reports read the source data and are for internal review, not for
        release. No clinical claims.
      </p>

      <p className={`text-sm ${muted}`}>
        TVD (total variation distance) is 0 for identical distributions and 1 for no overlap; the floor is the same
        measure between two real samples, which no release can be expected to beat. Utility AUC is a model trained on
        the release and tested on held-out real people, against one trained on real data. Membership AUC is how well an
        attacker tells training people from held-out ones: 0.5 is a coin flip.
      </p>

      {monitor !== undefined && <MonitorStatus monitor={monitor} />}

      {error && <p className="text-sm text-zinc-900 dark:text-zinc-100">{error}</p>}
      {!error && (releases === null || loading) && <Spinner />}
      {releases && releases.length === 0 && (
        <p className={`text-sm ${muted}`}>
          No releases yet. Run <code>uv run python scripts/synthesize.py</code> and{" "}
          <code>scripts/evaluate_synth.py</code>, then reload.
        </p>
      )}

      {specs.map((name) => (
        <section key={name} className="flex flex-col gap-2">
          <h2 className="font-medium text-zinc-900 dark:text-zinc-100">{name.replaceAll("_", " ")}</h2>
          <ReleaseTable releases={releases!.filter((r) => r.spec_name === name)} selected={selected} onSelect={loadCard} />
        </section>
      ))}

      {card && (
        <article className={`rounded-lg border border-grid p-6 transition-opacity ${loading ? "opacity-50" : ""}`}>
          <Markdown source={card} />
        </article>
      )}
    </main>
  );
}
