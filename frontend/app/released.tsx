"use client";

import { useSyncExternalStore } from "react";

// The release (package.json) and its build time (next.config.ts). The date is in the visitor's
// timezone and date format, which the browser knows from the device's settings; the static pages
// are built without them, so the date only appears once the page runs in the browser.
const version = process.env.RELEASE_VERSION ?? "";
const released = process.env.RELEASED_AT ?? "";
const noChange = () => () => {};

// The bold separator between the footer's links.
export const Dot = () => (
  <span aria-hidden="true" className="font-bold text-foreground">
    ·
  </span>
);

function localDate() {
  const when = new Date(released);
  if (Number.isNaN(when.getTime())) return "";
  return when.toLocaleDateString(undefined, { year: "numeric", month: "long", day: "numeric" });
}

export default function Released() {
  const date = useSyncExternalStore(noChange, localDate, () => "");
  return (
    <>
      {version && (
        <>
          <Dot />
          <span>Release Version {version}</span>
        </>
      )}
      {date && (
        <>
          <Dot />
          <time dateTime={released} title={`${released} (UTC)`}>
            {date}
          </time>
        </>
      )}
    </>
  );
}
