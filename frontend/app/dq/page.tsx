"use client";

import { useEffect, useMemo, useState } from "react";
import { type CheckResult, STATUSES, STATUS_META, type Status, StatusBadge, statusOf } from "./status";
import Spinner from "../spinner";

type Overview = {
  countTotal: number;
  countOverallFailed: number;
  percentPassed: number;
  strictPercentPassed: number | null;
};

type Run = {
  run_id: number;
  started_at: string;
  cdm_source_name: string | null;
  vocabulary_version: string | null;
  overview: Overview;
};

const CATEGORIES = ["Conformance", "Completeness", "Plausibility"];
const fmt = (n: number) => n.toLocaleString("en-US");

function StatTile({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="rounded-lg border-[1.5px] border-grid p-4">
      <div className="text-sm text-zinc-600 dark:text-zinc-400">{label}</div>
      <div className="mt-1 text-2xl font-semibold text-zinc-900 dark:text-zinc-100">{value}</div>
      {note && <div className="mt-1 text-xs text-zinc-500">{note}</div>}
    </div>
  );
}

type Counts = Record<string, Record<Status, number>>;

function CategoryBreakdown({ counts }: { counts: Counts }) {
  const [hover, setHover] = useState<{ category: string; status: Status; center: number } | null>(null);
  const [showTable, setShowTable] = useState(false);

  return (
    <figure className="rounded-lg border-[1.5px] border-grid p-4">
      <div className="flex items-start justify-between gap-4">
        <figcaption>
          <div className="font-medium text-zinc-900 dark:text-zinc-100">Checks by Kahn category</div>
          <div className="text-sm text-zinc-600 dark:text-zinc-400">Share of checks in each category, by status</div>
        </figcaption>
        <button onClick={() => setShowTable(!showTable)} className="text-sm text-accent underline underline-offset-2 hover:opacity-80">
          {showTable ? "Show chart" : "Show table"}
        </button>
      </div>

      <div className="mt-3 flex flex-wrap gap-4 text-sm">
        {STATUSES.map((s) => (
          <StatusBadge key={s} status={s} />
        ))}
      </div>

      {showTable ? (
        <table className="mt-4 w-full text-sm tabular-nums">
          <thead className="text-left text-zinc-600 dark:text-zinc-400">
            <tr>
              <th className="py-1 font-normal">Category</th>
              {STATUSES.map((s) => (
                <th key={s} className="py-1 text-right font-normal">{STATUS_META[s].label}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {CATEGORIES.map((c) => (
              <tr key={c} className="border-t border-zinc-200 dark:border-zinc-800">
                <td className="py-1">{c}</td>
                {STATUSES.map((s) => (
                  <td key={s} className="py-1 text-right">{fmt(counts[c][s])}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <div className="mt-4 flex flex-col gap-4">
          {CATEGORIES.map((c) => {
            const total = STATUSES.reduce((sum, s) => sum + counts[c][s], 0);
            let start = 0;
            return (
              <div key={c}>
                <div className="mb-1 flex justify-between text-sm">
                  <span className="text-zinc-900 dark:text-zinc-100">{c}</span>
                  <span className="text-zinc-600 tabular-nums dark:text-zinc-400">{fmt(total)} checks</span>
                </div>
                <div className="relative">
                  {/* The 2px gap between segments shows the surface, so neighbors never need a border. */}
                  <div className="flex h-6 gap-[2px]">
                    {STATUSES.filter((s) => counts[c][s] > 0).map((s, i, shown) => {
                      const share = counts[c][s] / total;
                      const center = start + share / 2;
                      start += share;
                      const last = i === shown.length - 1;
                      return (
                        <div
                          key={s}
                          tabIndex={0}
                          role="img"
                          aria-label={`${c}: ${STATUS_META[s].label}, ${counts[c][s]} checks`}
                          onPointerEnter={() => setHover({ category: c, status: s, center })}
                          onPointerLeave={() => setHover(null)}
                          onFocus={() => setHover({ category: c, status: s, center })}
                          onBlur={() => setHover(null)}
                          className={`min-w-[4px] outline-none hover:brightness-110 focus-visible:ring-2 focus-visible:ring-zinc-400 ${last ? "rounded-r" : ""}`}
                          style={{ flexGrow: share, flexBasis: 0, backgroundColor: STATUS_META[s].color }}
                        />
                      );
                    })}
                  </div>
                  {hover?.category === c && (
                    <div
                      style={{ left: `${Math.min(Math.max(hover.center * 100, 12), 88)}%` }}
                      className="pointer-events-none absolute -top-14 z-10 -translate-x-1/2 whitespace-nowrap rounded border border-zinc-200 bg-white px-3 py-1.5 text-sm shadow-sm dark:border-zinc-700 dark:bg-zinc-900">
                      <div className="font-semibold text-zinc-900 tabular-nums dark:text-zinc-100">
                        {fmt(counts[c][hover.status])} checks ({((counts[c][hover.status] / total) * 100).toFixed(1)}%)
                      </div>
                      <div className="flex items-center gap-1.5 text-zinc-600 dark:text-zinc-400">
                        <span className="inline-block h-0.5 w-3" style={{ backgroundColor: STATUS_META[hover.status].color }} />
                        {STATUS_META[hover.status].label}
                      </div>
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </figure>
  );
}

function ResultsTable({ results }: { results: CheckResult[] }) {
  const [status, setStatus] = useState<"problems" | "all" | Status>("problems");
  const [category, setCategory] = useState("all");
  const [table, setTable] = useState("all");
  const [search, setSearch] = useState("");

  const tables = useMemo(() => [...new Set(results.map((r) => r.cdm_table_name))].sort(), [results]);
  const shown = useMemo(() => {
    const q = search.trim().toLowerCase();
    return results
      .filter((r) => {
        const s = statusOf(r);
        if (status === "problems" ? !(s === "fail" || s === "error") : status !== "all" && s !== status) return false;
        if (category !== "all" && r.category !== category) return false;
        if (table !== "all" && r.cdm_table_name !== table) return false;
        const text = `${r.check_name} ${r.cdm_table_name} ${r.cdm_field_name ?? ""} ${r.concept_id ?? ""} ${r.check_description}`;
        return !q || text.toLowerCase().includes(q);
      })
      .sort((a, b) => (b.pct_violated_rows ?? -1) - (a.pct_violated_rows ?? -1));
  }, [results, status, category, table, search]);

  const select = "rounded border border-zinc-300 bg-transparent px-2 py-1 text-sm dark:border-zinc-700";
  return (
    <section className="flex flex-col gap-3">
      <h2 className="font-medium text-zinc-900 dark:text-zinc-100">Checks</h2>
      <div className="flex flex-wrap items-center gap-2">
        <select aria-label="Status" value={status} onChange={(e) => setStatus(e.target.value as typeof status)} className={select}>
          <option value="problems">Failed and errors</option>
          <option value="all">All statuses</option>
          {STATUSES.map((s) => (
            <option key={s} value={s}>{STATUS_META[s].label}</option>
          ))}
        </select>
        <select aria-label="Category" value={category} onChange={(e) => setCategory(e.target.value)} className={select}>
          <option value="all">All categories</option>
          {CATEGORIES.map((c) => (
            <option key={c} value={c}>{c}</option>
          ))}
        </select>
        <select aria-label="Table" value={table} onChange={(e) => setTable(e.target.value)} className={select}>
          <option value="all">All tables</option>
          {tables.map((t) => (
            <option key={t} value={t}>{t}</option>
          ))}
        </select>
        <input
          aria-label="Search checks"
          placeholder="Search check, table, field, concept"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className={`${select} w-56`}
        />
        <span className="text-sm text-zinc-600 tabular-nums dark:text-zinc-400">
          {fmt(shown.length)} of {fmt(results.length)}
        </span>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-left text-zinc-600 dark:text-zinc-400">
            <tr className="border-b border-zinc-200 dark:border-zinc-800">
              <th className="py-2 pr-4 font-normal">Status</th>
              <th className="py-2 pr-4 font-normal">Check</th>
              <th className="whitespace-nowrap py-2 pr-4 text-right font-normal">Violated rows</th>
              <th className="py-2 pr-4 text-right font-normal">Violated</th>
              <th className="py-2 text-right font-normal">Threshold</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((r) => (
              <tr key={r.check_id} className="border-b border-zinc-100 align-top dark:border-zinc-900">
                <td className="py-2 pr-4"><StatusBadge status={statusOf(r)} /></td>
                <td className="py-2 pr-4">
                  <div className="font-medium text-zinc-900 dark:text-zinc-100">
                    {r.check_name}{" "}
                    <span className="font-normal text-zinc-600 dark:text-zinc-400">
                      {r.cdm_table_name}{r.cdm_field_name ? `.${r.cdm_field_name}` : ""}
                      {r.concept_id ? ` = ${r.concept_id}` : ""}
                    </span>
                  </div>
                  <div className="text-zinc-600 dark:text-zinc-400">{r.not_applicable_reason ?? r.error ?? r.check_description}</div>
                </td>
                <td className="whitespace-nowrap py-2 pr-4 text-right tabular-nums">
                  {r.num_violated_rows === null ? "" : `${fmt(r.num_violated_rows)} of ${fmt(r.num_denominator_rows ?? 0)}`}
                </td>
                <td className="py-2 pr-4 text-right tabular-nums">
                  {r.pct_violated_rows === null ? "" : `${(r.pct_violated_rows * 100).toFixed(2)}%`}
                </td>
                <td className="py-2 text-right tabular-nums">{r.threshold_value === null ? "0%" : `${r.threshold_value}%`}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

export default function DataQuality() {
  const [runs, setRuns] = useState<Run[] | null>(null);
  const [runId, setRunId] = useState<number | null>(null);
  const [detail, setDetail] = useState<{ run: Run; results: CheckResult[] } | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  function loadRun(id: number) {
    setRunId(id);
    setLoading(true);
    fetch(`/api/dq/runs/${id}`)
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error(`${res.status}`))))
      .then(setDetail)
      .catch((e) => setError(`Could not load run ${id} (${e.message}).`))
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    fetch("/api/dq/runs")
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error(`${res.status}`))))
      .then((list: Run[]) => {
        setRuns(list);
        if (list.length) loadRun(list[0].run_id);
      })
      .catch((e) => setError(`Could not load runs (${e.message}).`));
  }, []);

  const counts = useMemo(() => {
    const c: Counts = Object.fromEntries(
      CATEGORIES.map((cat) => [cat, { pass: 0, na: 0, fail: 0, error: 0 }]),
    );
    for (const r of detail?.results ?? []) c[r.category][statusOf(r)] += 1;
    return c;
  }, [detail]);
  const totals = useMemo(() => {
    const t = { pass: 0, na: 0, fail: 0, error: 0 };
    for (const r of detail?.results ?? []) t[statusOf(r)] += 1;
    return t;
  }, [detail]);

  return (
    <main className="mx-auto flex w-full max-w-5xl flex-1 flex-col gap-6 px-6 py-12">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">Data quality</h1>
          <p className="text-sm text-zinc-600 dark:text-zinc-400">
            OHDSI DataQualityDashboard v2.9.0 checks on the OMOP CDM.
          </p>
        </div>
        {runs && runs.length > 0 && (
          <select
            aria-label="Run"
            value={runId ?? ""}
            onChange={(e) => loadRun(Number(e.target.value))}
            className="rounded border border-zinc-300 bg-transparent px-2 py-1 text-sm dark:border-zinc-700"
          >
            {runs.map((r) => (
              <option key={r.run_id} value={r.run_id}>
                Run {r.run_id}, {new Date(r.started_at).toLocaleString()}
              </option>
            ))}
          </select>
        )}
      </div>

      {error && <p className="text-sm text-zinc-900 dark:text-zinc-100">{error}</p>}
      {!error && (runs === null || loading) && <Spinner />}
      {runs && runs.length === 0 && (
        <p className="text-sm text-zinc-600 dark:text-zinc-400">
          No data quality runs yet. Run <code>uv run python scripts/hades.py run_dqd.R</code>, load it with <code>scripts/load_dqd.py</code>, then reload.
        </p>
      )}

      {detail && (
        // While another run loads, the current one stays on screen, dimmed.
        <div className={`flex flex-col gap-6 transition-opacity ${loading ? "opacity-50" : ""}`}>
          <div className="text-sm text-zinc-600 dark:text-zinc-400">
            {detail.run.cdm_source_name ?? "Unknown source"}, vocabulary {detail.run.vocabulary_version ?? "unknown"}
          </div>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
            <StatTile
              label="Pass rate"
              value={detail.run.overview.strictPercentPassed === null ? "n/a" : `${detail.run.overview.strictPercentPassed}%`}
              note="Applicable checks only"
            />
            <StatTile label="DQD pass rate" value={`${detail.run.overview.percentPassed}%`} note="Counts not applicable as passed" />
            <StatTile label="Checks" value={fmt(detail.results.length)} />
            <StatTile label="Failed" value={fmt(totals.fail)} />
            <StatTile label="Errors" value={fmt(totals.error)} />
            <StatTile label="Not applicable" value={fmt(totals.na)} note="Mostly empty tables" />
          </div>
          <CategoryBreakdown counts={counts} />
          <ResultsTable results={detail.results} />
        </div>
      )}
    </main>
  );
}
