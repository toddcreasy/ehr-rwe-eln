"use client";

import Link from "next/link";
import { type KeyboardEvent, useRef, useState } from "react";
import { MODULES } from "./modules";
import { useLive } from "./shell";

const n = (x: number) => x.toLocaleString("en-US");

export default function Home() {
  const live = useLive();
  const [picked, setPicked] = useState(0);
  const tabs = useRef<(HTMLButtonElement | null)[]>([]);
  const m = MODULES[picked];
  const figures = m.figures(live);

  // Arrow keys move between tabs, as the WAI-ARIA tabs pattern expects.
  function onKey(e: KeyboardEvent) {
    const step = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
    if (!step) return;
    const next = (picked + step + MODULES.length) % MODULES.length;
    setPicked(next);
    tabs.current[next]?.focus();
  }

  return (
    <main className="mx-auto flex w-full max-w-6xl flex-col gap-8 px-4 py-10 sm:px-6">
      <section className="max-w-3xl">
        <p className="text-sm font-medium tracking-wide text-accent uppercase">Synthetic patients only</p>
        <h1 className="mt-2 font-serif text-3xl leading-tight font-semibold sm:text-4xl">
          One synthetic population, five ways to turn it into evidence.
        </h1>
        <p className="mt-4 text-lg leading-relaxed text-muted">
          Counterpart generates {live.tte ? n(live.tte.persons) : "thousands of"} patients with Synthea, loads them into
          the OMOP Common Data Model (the OHDSI standard for observational health data), and runs every analysis on that one copy:
          checking the data, emulating trials, reading lab notebooks, curating genetic variants, and releasing private
          synthetic versions. None of it is real patient data, so every record is open to inspect.
        </p>
      </section>

      <section>
        <div role="tablist" aria-label="Sections" onKeyDown={onKey} className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
          {MODULES.map((mod, i) => {
            const active = i === picked;
            const top = mod.figures(live)[0];
            return (
              <button
                key={mod.key}
                ref={(el) => {
                  tabs.current[i] = el;
                }}
                role="tab"
                id={`tab-${mod.key}`}
                aria-selected={active}
                aria-controls="section-panel"
                tabIndex={active ? 0 : -1}
                onClick={() => setPicked(i)}
                className={`relative flex flex-col items-start rounded-2xl border p-4 text-left transition-colors ${
                  active ? "border-accent bg-card shadow-sm" : "border-line bg-card/60 hover:bg-card"
                }`}
              >
                <span
                  className={`flex h-8 w-8 items-center justify-center rounded-full border font-mono text-sm ${
                    active ? "border-accent bg-accent text-card" : "border-line bg-card text-muted"
                  }`}
                >
                  {i + 1}
                </span>
                <span className="mt-3 font-serif text-xl font-semibold">{mod.verb}</span>
                <span className="text-sm text-muted">{mod.name}</span>
                <span className={`mt-3 text-sm tabular-nums ${top?.attention ? "text-attention" : "text-muted"}`}>
                  {top ? `${top.value} ${top.label}` : " "}
                </span>
              </button>
            );
          })}
        </div>

        <div
          role="tabpanel"
          id="section-panel"
          aria-labelledby={`tab-${m.key}`}
          className="mt-4 grid gap-6 rounded-2xl border border-line bg-card p-6 lg:grid-cols-[1fr_auto]"
        >
          <div className="max-w-2xl">
            <h2 className="font-serif text-2xl font-semibold">{m.summary}</h2>
            <p className="mt-3 leading-relaxed text-muted">{m.detail}</p>
            <Link
              href={m.href}
              className="mt-5 inline-flex items-center gap-2 rounded-full bg-accent px-5 py-2.5 text-sm font-medium text-card hover:opacity-90"
            >
              Open {m.name.toLowerCase()} <span aria-hidden="true">→</span>
            </Link>
          </div>
          {figures.length > 0 && (
            <dl className="grid content-start gap-3 sm:grid-cols-3 lg:w-80 lg:grid-cols-1">
              {figures.map((f) => (
                <div
                  key={f.label}
                  className={`rounded-xl border px-4 py-3 ${f.attention ? "border-attention/40 bg-attention-soft" : "border-line"}`}
                >
                  <dt className="text-sm text-muted">{f.label}</dt>
                  <dd className={`text-2xl font-semibold tabular-nums ${f.attention ? "text-attention" : ""}`}>{f.value}</dd>
                </div>
              ))}
            </dl>
          )}
        </div>
      </section>
    </main>
  );
}
