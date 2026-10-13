"use client";

import Link from "next/link";
import { useState } from "react";

function HealthPanel() {
  const [result, setResult] = useState<string>("");

  async function checkDatabase() {
    // Same origin: FastAPI serves this page and the API, so no CORS.
    const res = await fetch("/api/health/db");
    setResult(`${res.status} ${await res.text()}`);
  }

  return (
    <div className="flex flex-col gap-4">
      <button
        onClick={checkDatabase}
        className="w-fit rounded bg-zinc-900 px-4 py-2 text-sm text-white dark:bg-zinc-100 dark:text-black"
      >
        Call GET /api/health/db
      </button>
      {result && (
        <pre className="rounded bg-zinc-100 p-4 font-mono text-sm dark:bg-zinc-900">{result}</pre>
      )}
    </div>
  );
}

export default function Home() {
  return (
    <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-6 px-6 py-12">
      <h1 className="text-2xl font-semibold">ehr-rwe-eln</h1>
      <Link href="/dq/" className="w-fit underline">
        Data quality dashboard
      </Link>
      <Link href="/tte/" className="w-fit underline">
        Target trial emulation
      </Link>
      <HealthPanel />
    </main>
  );
}
