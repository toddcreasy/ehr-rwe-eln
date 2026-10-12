"use client";

import { Authenticator } from "@aws-amplify/ui-react";
import "@aws-amplify/ui-react/styles.css";
import { Amplify } from "aws-amplify";
import { fetchAuthSession } from "aws-amplify/auth";
import { useState } from "react";

Amplify.configure({
  Auth: {
    Cognito: {
      userPoolId: process.env.NEXT_PUBLIC_USER_POOL_ID!,
      userPoolClientId: process.env.NEXT_PUBLIC_USER_POOL_CLIENT_ID!,
    },
  },
});

function MePanel() {
  const [result, setResult] = useState<string>("");

  async function callMe() {
    const { tokens } = await fetchAuthSession();
    // Same-origin path; Amplify rewrites /api/* to the backend, so no CORS.
    const res = await fetch("/api/me", {
      headers: { Authorization: `Bearer ${tokens?.accessToken.toString()}` },
    });
    setResult(`${res.status} ${await res.text()}`);
  }

  return (
    <div className="flex flex-col gap-4">
      <button
        onClick={callMe}
        className="w-fit rounded bg-zinc-900 px-4 py-2 text-sm text-white dark:bg-zinc-100 dark:text-black"
      >
        Call GET /me
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
      <Authenticator loginMechanisms={["email"]}>
        {({ signOut, user }) => (
          <div className="flex flex-col gap-6">
            <div className="flex items-center gap-4 text-sm">
              <span>Signed in as {user?.signInDetails?.loginId}</span>
              <button onClick={signOut} className="underline">
                Sign out
              </button>
            </div>
            <MePanel />
          </div>
        )}
      </Authenticator>
    </main>
  );
}
