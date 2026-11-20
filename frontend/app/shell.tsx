"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { createContext, useContext, useEffect, useState } from "react";
import { type Live, MODULES } from "./modules";
import PilotBioMark from "./pilotbio-mark";

const LiveContext = createContext<Live>({});
export const useLive = () => useContext(LiveContext);

const get = (path: string) => fetch(path).then((r) => (r.ok ? r.json() : Promise.reject(r.status)));
const sum = (rows: Record<string, number>[], key: string) => rows.reduce((t, r) => t + r[key], 0);

// One fetch per section on first load; the shell stays mounted across navigation, so the figures
// do not refetch on every tab. A section whose API fails just shows no figures.
function useLiveFigures(): Live {
  const [live, setLive] = useState<Live>({});
  useEffect(() => {
    const put = (part: Live) => setLive((l) => ({ ...l, ...part }));
    const skip = () => {};
    get("/api/dq/runs")
      .then((runs) => runs.length && put({ dq: { ...runs[0].overview, runs: runs.length } }))
      .catch(skip);
    get("/api/tte/runs")
      .then((runs) => runs.length && put({ tte: { persons: runs[0].persons, runs: runs.length } }))
      .catch(skip);
    get("/api/eln/summary").then((s) => put({ eln: s })).catch(skip);
    get("/api/curation/sets")
      .then((sets) => put({ curation: { variants: sum(sets, "variants"), decided: sum(sets, "decided"), sets: sets.length } }))
      .catch(skip);
    Promise.all([get("/api/synth/releases"), get("/api/synth/monitor")])
      .then(([releases, monitor]) =>
        put({
          synth: {
            releases: releases.filter((r: { withdrawn_at: string | null }) => !r.withdrawn_at).length,
            withdrawn: releases.filter((r: { withdrawn_at: string | null }) => r.withdrawn_at).length,
            flags: monitor.latest?.flags?.length ?? 0,
          },
        }),
      )
      .catch(skip);
  }, []);
  return live;
}

export function Mark({ className = "" }: { className?: string }) {
  // A person and their synthetic counterpart: one solid circle, one dashed.
  return (
    <svg viewBox="0 0 40 40" className={className} aria-hidden="true">
      <rect x="1.5" y="1.5" width="37" height="37" rx="9" fill="none" stroke="currentColor" strokeWidth="2.5" />
      <circle cx="16.5" cy="20" r="6" fill="none" stroke="currentColor" strokeWidth="2.2" />
      <circle cx="23.5" cy="20" r="6" fill="none" stroke="currentColor" strokeWidth="2.2" strokeDasharray="2.4 2.3" />
    </svg>
  );
}

function ThemeToggle() {
  function toggle() {
    const dark = document.documentElement.classList.toggle("dark");
    try {
      localStorage.setItem("theme", dark ? "dark" : "light");
    } catch {}
  }
  return (
    <button onClick={toggle} aria-label="Switch light or dark mode" className="rounded-full p-2 text-muted hover:bg-accent-soft hover:text-foreground">
      <svg viewBox="0 0 24 24" className="h-5 w-5 dark:hidden" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
        <path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5Z" strokeLinejoin="round" />
      </svg>
      <svg viewBox="0 0 24 24" className="hidden h-5 w-5 dark:block" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
        <circle cx="12" cy="12" r="4" />
        <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" strokeLinecap="round" />
      </svg>
    </button>
  );
}

function GitHub() {
  return (
    <a href="https://github.com/toddcreasy/ehr-rwe-eln" aria-label="Source on GitHub" className="rounded-full p-2 text-muted hover:bg-accent-soft hover:text-foreground">
      <svg viewBox="0 0 16 16" className="h-5 w-5" fill="currentColor" aria-hidden="true">
        <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0 0 16 8c0-4.42-3.58-8-8-8Z" />
      </svg>
    </a>
  );
}

// On every page but home: the sections as a compact strip, each with its headline figure.
function SectionStrip({ path }: { path: string }) {
  const live = useLive();
  return (
    <nav aria-label="Sections" className="sticky top-0 z-10 border-b border-line bg-card/90 backdrop-blur">
      <div className="mx-auto flex max-w-6xl gap-1 overflow-x-auto px-4 sm:px-6">
        {MODULES.map((m, i) => {
          const active = path.startsWith(m.href);
          const top = m.figures(live)[0];
          return (
            <Link
              key={m.key}
              href={m.href}
              aria-current={active ? "page" : undefined}
              className={`flex shrink-0 items-baseline gap-2 border-b-2 px-3 py-3 text-sm ${
                active ? "border-accent text-foreground" : "border-transparent text-muted hover:text-foreground"
              }`}
            >
              <span className="font-mono text-xs text-muted">{i + 1}</span>
              <span className="font-medium">{m.name}</span>
              {top && <span className={`text-xs tabular-nums ${top.attention ? "text-attention" : "text-muted"}`}>{top.value}</span>}
            </Link>
          );
        })}
      </div>
    </nav>
  );
}

export default function Shell({ children }: { children: React.ReactNode }) {
  const live = useLiveFigures();
  const path = usePathname() ?? "/";
  const home = path === "/";
  return (
    <LiveContext.Provider value={live}>
      <header className="border-b border-line bg-card">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-4 py-4 sm:px-6">
          <Link href="/" className="flex items-center gap-3">
            <Mark className="h-10 w-10 shrink-0 text-accent" />
            <span>
              <span className="block font-serif text-2xl leading-tight font-semibold">Counterpart</span>
              <span className="block text-sm text-muted">Real world evidence from one synthetic population</span>
            </span>
          </Link>
          <div className="flex items-center gap-1">
            <a
              href="https://pilotbio.io"
              target="_blank"
              rel="noopener noreferrer"
              title="PilotBio"
              className="mr-2 flex items-center gap-1.5 text-sm font-medium text-foreground hover:opacity-80"
            >
              <PilotBioMark />
              <span className="hidden sm:inline">Todd Creasy</span>
            </a>
            <GitHub />
            <ThemeToggle />
          </div>
        </div>
      </header>
      {!home && <SectionStrip path={path} />}
      <div className="flex-1">
        {home ? (
          children
        ) : (
          <div className="mx-auto max-w-6xl px-4 py-8 sm:px-6">
            <div className="rounded-2xl border border-line bg-card">{children}</div>
          </div>
        )}
      </div>
    </LiveContext.Provider>
  );
}
