"use client";

import { useSyncExternalStore } from "react";

// The build time (next.config.ts), in the visitor's timezone and date format. The browser knows
// both from the device's settings; the static pages are built without them, so the date only
// appears once the page runs in the browser.
const released = process.env.RELEASED_AT ?? "";
const noChange = () => () => {};

// The bold separator between the footer's links.
export const Dot = () => (
  <span aria-hidden="true" className="font-bold text-foreground">
    ·
  </span>
);

function local() {
  const when = new Date(released);
  if (Number.isNaN(when.getTime())) return "";
  return when.toLocaleString(undefined, {
    year: "numeric",
    month: "long",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZoneName: "short",
  });
}

export default function Released() {
  const text = useSyncExternalStore(noChange, local, () => "");
  if (!text) return null;
  return (
    <>
      <Dot />
      <time dateTime={released} title={`${released} (UTC)`}>
        Released {text}
      </time>
    </>
  );
}
