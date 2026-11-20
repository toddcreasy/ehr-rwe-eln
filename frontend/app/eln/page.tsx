"use client";

import { useEffect, useState } from "react";

type Summary = {
  subjects: number;
  entries: number;
  extracted: number;
  failed: number;
  samples: number;
  results: number;
  models: string[];
};

type EntryRow = {
  entry_id: string;
  title: string;
  author: string;
  created: string;
  status: "extracted" | "failed" | "pending";
  samples: number | null;
  results: number | null;
};

type Sample = { sample_id: string; subject_id: string; specimen_type: string; collection_date: string | null };
type Result = { sample_id: string; analyte: string; value: number; unit: string };

type Entry = {
  entry_id: string;
  title: string;
  author: string;
  created: string;
  body: string;
  model: string | null;
  extraction: { samples: Sample[]; results: Result[] } | null;
  error: string | null;
  subjects: { subject_id: string; linked: boolean }[];
};

const fmt = (n: number) => n.toLocaleString("en-US");
const muted = "text-zinc-600 dark:text-zinc-400";
const th = "py-1 pr-4 font-normal";
const row = "border-t border-zinc-200 dark:border-zinc-800";

function StatTile({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="rounded-lg border border-zinc-200 p-4 dark:border-zinc-800">
      <div className={`text-sm ${muted}`}>{label}</div>
      <div className="mt-1 text-2xl font-semibold text-zinc-900 tabular-nums dark:text-zinc-100">{value}</div>
      {note && <div className="mt-1 text-xs text-zinc-500">{note}</div>}
    </div>
  );
}

function EntryDetail({ entry }: { entry: Entry }) {
  const linked = new Map(entry.subjects.map((s) => [s.subject_id, s.linked]));
  return (
    <article className="flex flex-col gap-4 rounded-lg border border-zinc-200 p-6 dark:border-zinc-800">
      <header>
        <h2 className="text-lg font-semibold text-zinc-900 dark:text-zinc-100">
          {entry.entry_id}: {entry.title}
        </h2>
        <p className={`text-sm ${muted}`}>
          {entry.author}, {entry.created}
          {entry.model && `; extracted by ${entry.model}`}
        </p>
      </header>

      <div className="grid gap-6 lg:grid-cols-2">
        <section className="flex flex-col gap-2">
          <h3 className="font-medium text-zinc-900 dark:text-zinc-100">Entry as written</h3>
          <pre className="whitespace-pre-wrap rounded bg-zinc-100 p-4 font-mono text-sm dark:bg-zinc-900">{entry.body}</pre>
        </section>

        <section className="flex flex-col gap-4">
          <h3 className="font-medium text-zinc-900 dark:text-zinc-100">Extracted</h3>
          {entry.error && <p className="text-sm">Extraction failed: {entry.error}</p>}
          {!entry.extraction && !entry.error && <p className={`text-sm ${muted}`}>Not extracted yet.</p>}
          {entry.extraction && (
            <>
              <div className="overflow-x-auto">
                <table className="w-full text-sm tabular-nums">
                  <thead className={`text-left ${muted}`}>
                    <tr>
                      <th className={th}>Sample</th>
                      <th className={th}>Subject</th>
                      <th className={th}>Specimen</th>
                      <th className="py-1 font-normal">Collected</th>
                    </tr>
                  </thead>
                  <tbody>
                    {entry.extraction.samples.map((s) => (
                      <tr key={s.sample_id} className={row}>
                        <td className="py-1 pr-4">{s.sample_id}</td>
                        <td className="py-1 pr-4">
                          {s.subject_id}
                          <span className={muted}>{linked.get(s.subject_id) ? " (linked)" : " (no OMOP person)"}</span>
                        </td>
                        <td className="py-1 pr-4">{s.specimen_type.replaceAll("_", " ")}</td>
                        <td className="py-1">{s.collection_date ?? <span className={muted}>not stated</span>}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-sm tabular-nums">
                  <thead className={`text-left ${muted}`}>
                    <tr>
                      <th className={th}>Sample</th>
                      <th className={th}>Analyte</th>
                      <th className={`${th} text-right`}>Value</th>
                      <th className="py-1 font-normal">Unit</th>
                    </tr>
                  </thead>
                  <tbody>
                    {entry.extraction.results.map((r) => (
                      <tr key={`${r.sample_id} ${r.analyte}`} className={row}>
                        <td className="py-1 pr-4">{r.sample_id}</td>
                        <td className="py-1 pr-4">{r.analyte.replaceAll("_", " ")}</td>
                        <td className="py-1 pr-4 text-right">{r.value}</td>
                        <td className="py-1">{r.unit}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </section>
      </div>
    </article>
  );
}

export default function LabNotebook() {
  const [summary, setSummary] = useState<Summary | null>(null);
  const [entries, setEntries] = useState<EntryRow[] | null>(null);
  const [entry, setEntry] = useState<Entry | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  function loadEntry(id: string) {
    setLoading(true);
    fetch(`/api/eln/entries/${encodeURIComponent(id)}`)
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error(`${res.status}`))))
      .then(setEntry)
      .catch((e) => setError(`Could not load entry ${id} (${e.message}).`))
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    const json = (res: Response) => (res.ok ? res.json() : Promise.reject(new Error(`${res.status}`)));
    fetch("/api/eln/summary").then(json).then(setSummary).catch((e) => setError(`Could not load the summary (${e.message}).`));
    fetch("/api/eln/entries")
      .then(json)
      .then((list: EntryRow[]) => {
        setEntries(list);
        if (list.length) loadEntry(list[0].entry_id);
      })
      .catch((e) => setError(`Could not load entries (${e.message}).`));
  }, []);

  return (
    <main className="mx-auto flex w-full max-w-6xl flex-1 flex-col gap-6 px-6 py-12">
      <div>
        <h1 className="text-2xl font-semibold">Lab notebook extraction</h1>
        <p className={`text-sm ${muted}`}>
          Synthetic ELN entries, and the samples and results Claude extracted from each, checked against a typed model
          before they are written to OMOP and FHIR.
        </p>
      </div>

      <p className="rounded-lg border border-zinc-300 p-4 text-sm text-zinc-900 dark:border-zinc-700 dark:text-zinc-100">
        Synthetic entries on synthetic Synthea patients only. Subject codes link to OMOP persons through a registry
        this page does not show. No clinical claims.
      </p>

      {error && <p className="text-sm text-zinc-900 dark:text-zinc-100">{error}</p>}

      {summary && (
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <StatTile label="Entries" value={fmt(summary.entries)} note={`${fmt(summary.subjects)} study subjects`} />
          <StatTile
            label="Extracted"
            value={fmt(summary.extracted)}
            note={`${fmt(summary.failed)} failed, ${fmt(summary.entries - summary.extracted - summary.failed)} pending`}
          />
          <StatTile label="Samples" value={fmt(summary.samples)} />
          <StatTile label="Results" value={fmt(summary.results)} note={summary.models.join(", ") || undefined} />
        </div>
      )}

      {entries && entries.length === 0 && (
        <p className={`text-sm ${muted}`}>
          No entries yet. Run <code>uv run python scripts/generate_eln.py</code> and{" "}
          <code>scripts/extract_eln.py</code>, then reload.
        </p>
      )}

      {entries && entries.length > 0 && (
        <div className="grid gap-6 lg:grid-cols-[18rem_1fr]">
          <div className="max-h-[70vh] overflow-y-auto rounded-lg border border-zinc-200 dark:border-zinc-800">
            <ul>
              {entries.map((e) => (
                <li key={e.entry_id}>
                  <button
                    onClick={() => loadEntry(e.entry_id)}
                    className={`flex w-full flex-col items-start gap-0.5 border-b border-zinc-200 px-3 py-2 text-left text-sm dark:border-zinc-800 ${entry?.entry_id === e.entry_id ? "bg-zinc-100 dark:bg-zinc-900" : "hover:bg-zinc-50 dark:hover:bg-zinc-900"}`}
                  >
                    <span className="font-medium">{e.entry_id}</span>
                    <span className={muted}>{e.title}</span>
                    <span className="text-xs text-zinc-500">
                      {e.status === "extracted" ? `${e.samples} samples, ${e.results} results` : e.status}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
          <div className={`transition-opacity ${loading ? "opacity-50" : ""}`}>{entry && <EntryDetail entry={entry} />}</div>
        </div>
      )}
    </main>
  );
}
