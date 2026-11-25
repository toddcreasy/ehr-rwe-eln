"use client";

import { useEffect, useState } from "react";
import Spinner from "../spinner";
import {
  ArmsHelp,
  AttritionHelp,
  BalanceHelp,
  ControlsHelp,
  DiagnosticsHelp,
  HazardHelp,
  NotEstimableHelp,
  PageHelp,
  RisksHelp,
} from "./help";

type Run = {
  run_id: number;
  started_at: string;
  cdm_source_name: string | null;
  persons: number;
};

type Risk = {
  day: number;
  risk_treatment: number;
  risk_comparator: number;
  risk_difference: number;
  risk_ratio: number | null;
};

type Interval = { low: number | null; high: number | null };

type NegativeControl = {
  name: string;
  persons: number;
  events: number;
  hazard_ratio: number | null;
  robust_ci: [number, number] | null;
  not_estimable: string | null;
  excludes_null: boolean;
};

type Report = {
  protocol: { id: number; name: string; description: string; treatment: string; comparator: string; outcome: string };
  attrition: { rule: string; persons: number }[];
  arms: { name: string; persons: number; events: number; median_follow_up_days: number }[];
  not_estimable: string | null;
  balance: { covariate: string; smd_before: number; smd_after: number }[] | null;
  diagnostics: {
    "share_ps_outside_0.05_0.95": number;
    weight_min: number;
    weight_max: number;
    effective_n_treatment: number;
    effective_n_comparator: number;
    covariates_unbalanced_after: number;
    covariates_dropped: Record<string, string>;
  } | null;
  survival: {
    crude_risks: Risk[];
    weighted_risks: Risk[];
    crude_hazard_ratio: number | null;
    hazard_ratio: number | null;
    hazard_ratio_robust_ci: [number, number] | null;
    bootstrap_ci: Record<string, Interval>;
    replicates_used: number;
    replicates_not_estimable: number;
  } | null;
  negative_controls: NegativeControl[];
};

// Below 0.1 is the usual threshold for a balanced covariate.
const BALANCED = 0.1;
const fmt = (n: number) => n.toLocaleString("en-US");
const pct = (n: number | null) => (n === null ? "" : `${(n * 100).toFixed(1)}%`);
const signed = (n: number | null) => (n === null ? "" : `${n >= 0 ? "+" : ""}${(n * 100).toFixed(1)}%`);
const ratio = (n: number | null) => (n === null ? "none" : n.toFixed(2));
const ci = (c: [number, number] | Interval | null) => {
  if (!c) return "";
  const [low, high] = Array.isArray(c) ? c : [c.low, c.high];
  return low === null || high === null ? "" : `${low.toFixed(2)} to ${high.toFixed(2)}`;
};

const muted = "text-zinc-600 dark:text-zinc-400";
const th = "py-1 pr-4 font-normal";
const row = "border-t border-zinc-200 dark:border-zinc-800";

function StatTile({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="rounded-lg border-[1.5px] border-grid p-4">
      <div className={`text-sm ${muted}`}>{label}</div>
      <div className="mt-1 text-2xl font-semibold text-zinc-900 tabular-nums dark:text-zinc-100">{value}</div>
      {note && <div className="mt-1 text-xs text-zinc-500">{note}</div>}
    </div>
  );
}

function Section({ title, note, help, children }: { title: string; note?: string; help?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section data-help className="flex flex-col gap-2">
      <div>
        <h3 className="flex items-center gap-2 font-medium text-zinc-900 dark:text-zinc-100">
          {title} {help}
        </h3>
        {note && <p className={`text-sm ${muted}`}>{note}</p>}
      </div>
      <div className="overflow-x-auto">{children}</div>
    </section>
  );
}

function ProtocolReport({ report }: { report: Report }) {
  const { protocol, diagnostics: d, survival: s } = report;
  const crude = new Map(s?.crude_risks.map((r) => [r.day, r]));
  return (
    <article className="flex flex-col gap-6 rounded-lg border-[1.5px] border-grid p-6">
      <header>
        <h2 className="text-lg font-semibold text-zinc-900 dark:text-zinc-100">
          {protocol.id}. {protocol.treatment} vs {protocol.comparator}, outcome {protocol.outcome.replaceAll("_", " ")}
        </h2>
        <p className={`text-sm ${muted}`}>{protocol.description}</p>
      </header>

      <div className="grid gap-6 md:grid-cols-2">
        <Section title="Attrition" note="Persons remaining after each eligibility rule." help={<AttritionHelp attrition={report.attrition} />}>
          <table className="w-full text-sm tabular-nums">
            <tbody>
              {report.attrition.map((a) => (
                <tr key={a.rule} className={row}>
                  <td className="py-1 pr-4">{a.rule}</td>
                  <td className="py-1 text-right">{fmt(a.persons)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Section>
        <Section title="Arms" help={<ArmsHelp arms={report.arms} />}>
          <table className="w-full text-sm tabular-nums">
            <thead className={`text-left ${muted}`}>
              <tr>
                <th className={th}>Strategy</th>
                <th className={`${th} text-right`}>Persons</th>
                <th className={`${th} text-right`}>Events</th>
                <th className="py-1 text-right font-normal">Median follow-up</th>
              </tr>
            </thead>
            <tbody>
              {report.arms.map((a) => (
                <tr key={a.name} className={row}>
                  <td className="py-1 pr-4">{a.name}</td>
                  <td className="py-1 pr-4 text-right">{fmt(a.persons)}</td>
                  <td className="py-1 pr-4 text-right">{fmt(a.events)}</td>
                  <td className="py-1 text-right">{fmt(Math.round(a.median_follow_up_days))} days</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Section>
      </div>

      {report.not_estimable && (
        <div data-help className="rounded-lg border border-zinc-300 p-4 text-sm dark:border-zinc-700">
          <div className="flex items-center gap-2 font-medium text-zinc-900 dark:text-zinc-100">
            Not estimable <NotEstimableHelp reason={report.not_estimable} />
          </div>
          <div className={muted}>
            {report.not_estimable}. The covariates tell the arms apart too well for weighting to make them comparable,
            so no estimate is made.
          </div>
        </div>
      )}

      {d && report.balance && (
        <>
          <div data-help className="relative grid grid-cols-2 gap-3 lg:grid-cols-4">
            <div className="absolute -top-2.5 -right-2.5 rounded-full bg-card">
              <DiagnosticsHelp
                outside={d["share_ps_outside_0.05_0.95"]}
                weightMin={d.weight_min}
                weightMax={d.weight_max}
                effective={[d.effective_n_treatment, d.effective_n_comparator]}
                arms={report.arms}
                unbalanced={d.covariates_unbalanced_after}
              />
            </div>
            <StatTile
              label="Propensity outside 0.05 to 0.95"
              value={`${(d["share_ps_outside_0.05_0.95"] * 100).toFixed(0)}%`}
              note="Persons with almost no chance of the other arm"
            />
            <StatTile label="Weights" value={`${d.weight_min.toFixed(2)} to ${d.weight_max.toFixed(2)}`} note="Stabilized, truncated" />
            <StatTile
              label="Effective sample size"
              value={`${fmt(Math.round(d.effective_n_treatment))} vs ${fmt(Math.round(d.effective_n_comparator))}`}
              note="What the weighted arms are worth unweighted"
            />
            <StatTile label="Unbalanced after weighting" value={fmt(d.covariates_unbalanced_after)} note={`Covariates with |SMD| ${BALANCED} or more`} />
          </div>

          <Section
            title="Covariate balance"
            note={`Standardized mean difference between the arms. Below ${BALANCED} in absolute value is the usual threshold for balanced.`}
            help={<BalanceHelp balance={report.balance} />}
          >
            <table className="w-full text-sm tabular-nums">
              <thead className={`text-left ${muted}`}>
                <tr>
                  <th className={th}>Covariate</th>
                  <th className={`${th} text-right`}>Before weighting</th>
                  <th className="py-1 text-right font-normal">After weighting</th>
                </tr>
              </thead>
              <tbody>
                {report.balance.map((b) => (
                  <tr key={b.covariate} className={row}>
                    <td className="py-1 pr-4">{b.covariate}</td>
                    <td className="py-1 pr-4 text-right">{b.smd_before.toFixed(3)}</td>
                    <td className={`py-1 text-right ${Math.abs(b.smd_after) >= BALANCED ? "font-semibold" : ""}`}>
                      {b.smd_after.toFixed(3)}
                      {Math.abs(b.smd_after) >= BALANCED && " (unbalanced)"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {Object.keys(d.covariates_dropped).length > 0 && (
              <p className={`mt-2 text-sm ${muted}`}>
                Dropped from the model:{" "}
                {Object.entries(d.covariates_dropped).map(([c, why]) => `${c} (${why})`).join("; ")}.
              </p>
            )}
          </Section>
        </>
      )}

      {s && (
        <>
          <Section
            title="Risk of the outcome"
            note="Kaplan-Meier risk by day, crude and weighted, with the 95% bootstrap interval for the weighted difference."
            help={
              <RisksHelp
                treatment={protocol.treatment}
                comparator={protocol.comparator}
                weighted={s.weighted_risks}
                bootstrap={s.bootstrap_ci}
              />
            }
          >
            <table className="w-full text-sm tabular-nums">
              <thead className={`text-left ${muted}`}>
                <tr>
                  <th className={th}>Day</th>
                  <th className={`${th} text-right`}>{protocol.treatment}, crude / weighted</th>
                  <th className={`${th} text-right`}>{protocol.comparator}, crude / weighted</th>
                  <th className="py-1 text-right font-normal">Weighted difference (95% CI)</th>
                </tr>
              </thead>
              <tbody>
                {s.weighted_risks.map((r) => {
                  const c = crude.get(r.day);
                  const interval = s.bootstrap_ci[`risk_difference_${r.day}`];
                  return (
                    <tr key={r.day} className={row}>
                      <td className="py-1 pr-4">{fmt(r.day)}</td>
                      <td className="py-1 pr-4 text-right">{pct(c?.risk_treatment ?? null)} / {pct(r.risk_treatment)}</td>
                      <td className="py-1 pr-4 text-right">{pct(c?.risk_comparator ?? null)} / {pct(r.risk_comparator)}</td>
                      <td className="py-1 text-right">
                        {signed(r.risk_difference)}
                        {interval && ` (${signed(interval.low)} to ${signed(interval.high)})`}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </Section>

          <div data-help className="relative grid grid-cols-2 gap-3 lg:grid-cols-4">
            <div className="absolute -top-2.5 -right-2.5 rounded-full bg-card">
              <HazardHelp
                treatment={protocol.treatment}
                comparator={protocol.comparator}
                hr={s.hazard_ratio}
                robust={s.hazard_ratio_robust_ci}
                boot={s.bootstrap_ci.hazard_ratio ?? null}
                crude={s.crude_hazard_ratio}
                used={s.replicates_used}
                notEstimable={s.replicates_not_estimable}
              />
            </div>
            <StatTile label="Hazard ratio, weighted" value={ratio(s.hazard_ratio)} note={`${protocol.treatment} vs ${protocol.comparator}`} />
            <StatTile label="Robust 95% CI" value={ci(s.hazard_ratio_robust_ci) || "none"} />
            <StatTile label="Bootstrap 95% CI" value={ci(s.bootstrap_ci.hazard_ratio ?? null) || "none"} note={`${fmt(s.replicates_used)} resamples, ${fmt(s.replicates_not_estimable)} not estimable`} />
            <StatTile label="Hazard ratio, crude" value={ratio(s.crude_hazard_ratio)} note="Before weighting" />
          </div>
        </>
      )}

      {report.negative_controls.length > 0 && (
        <Section
          title="Negative controls"
          note="Outcomes neither strategy plausibly causes, run through the same analysis. Hazard ratios should be near 1; an interval that excludes 1 points to confounding the weights did not remove, or chance."
          help={<ControlsHelp controls={report.negative_controls} />}
        >
          <table className="w-full text-sm tabular-nums">
            <thead className={`text-left ${muted}`}>
              <tr>
                <th className={th}>Outcome</th>
                <th className={`${th} text-right`}>Persons</th>
                <th className={`${th} text-right`}>Events</th>
                <th className={`${th} text-right`}>Hazard ratio</th>
                <th className="py-1 text-right font-normal">Robust 95% CI</th>
              </tr>
            </thead>
            <tbody>
              {report.negative_controls.map((nc) => (
                <tr key={nc.name} className={row}>
                  <td className="py-1 pr-4">{nc.name.replaceAll("_", " ")}</td>
                  <td className="py-1 pr-4 text-right">{fmt(nc.persons)}</td>
                  <td className="py-1 pr-4 text-right">{fmt(nc.events)}</td>
                  <td className="py-1 pr-4 text-right">{nc.not_estimable ? "not estimable" : ratio(nc.hazard_ratio)}</td>
                  <td className={`py-1 text-right ${nc.excludes_null ? "font-semibold" : ""}`}>
                    {ci(nc.robust_ci)}
                    {nc.excludes_null && " (excludes 1)"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Section>
      )}
    </article>
  );
}

export default function TargetTrials() {
  const [runs, setRuns] = useState<Run[] | null>(null);
  const [runId, setRunId] = useState<number | null>(null);
  const [detail, setDetail] = useState<{ run: Run; reports: Report[] } | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  function loadRun(id: number) {
    setRunId(id);
    setLoading(true);
    fetch(`/api/tte/runs/${id}`)
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error(`${res.status}`))))
      .then(setDetail)
      .catch((e) => setError(`Could not load run ${id} (${e.message}).`))
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    fetch("/api/tte/runs")
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error(`${res.status}`))))
      .then((list: Run[]) => {
        setRuns(list);
        if (list.length) loadRun(list[0].run_id);
      })
      .catch((e) => setError(`Could not load runs (${e.message}).`));
  }, []);

  return (
    <main className="mx-auto flex w-full max-w-5xl flex-1 flex-col gap-6 px-6 py-12">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div data-help>
          <h1 className="flex items-center gap-2 text-2xl font-semibold">
            Target trial emulation <PageHelp />
          </h1>
          <p className={`text-sm ${muted}`}>Bias diagnostics for each protocol: who was eligible, how well weighting balanced the arms, the estimates, and negative controls.</p>
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
                Run {r.run_id}, {fmt(r.persons)} persons, {new Date(r.started_at).toLocaleString()}
              </option>
            ))}
          </select>
        )}
      </div>

      <p className="rounded-lg border border-zinc-300 p-4 text-sm text-zinc-900 dark:border-zinc-700 dark:text-zinc-100">
        Synthetic Synthea patients only. Synthea assigns diagnoses and treatments by fixed rules, so these numbers test the
        method, not the drugs. No clinical claims.
      </p>

      {error && <p className="text-sm text-zinc-900 dark:text-zinc-100">{error}</p>}
      {!error && (runs === null || loading) && <Spinner />}
      {runs && runs.length === 0 && (
        <p className={`text-sm ${muted}`}>
          No runs yet. Run <code>uv run python scripts/run_tte.py</code>, then reload.
        </p>
      )}

      {detail && (
        <div className={`flex flex-col gap-6 transition-opacity ${loading ? "opacity-50" : ""}`}>
          <div className={`text-sm ${muted}`}>
            {detail.run.cdm_source_name ?? "Unknown source"}, {fmt(detail.run.persons)} persons
          </div>
          {detail.reports.map((r) => (
            <ProtocolReport key={r.protocol.id} report={r} />
          ))}
        </div>
      )}
    </main>
  );
}
