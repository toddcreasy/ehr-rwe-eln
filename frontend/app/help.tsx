"use client";

import { createContext, useCallback, useContext, useId, useLayoutEffect, useRef, useState, useSyncExternalStore } from "react";

// Help on the page: a switch in the header shows or hides every "?" button, and each button opens
// a small scrollable note about one region of the page (the nearest element marked data-help).
// The note sits beside that region, never on top of it.

const WIDTH = 320;
const MAX_HEIGHT = 340;
const GAP = 10;
const EDGE = 12;

const OpenContext = createContext<{ open: string | null; setOpen: (id: string | null) => void }>({
  open: null,
  setOpen: () => {},
});

export function HelpProvider({ children }: { children: React.ReactNode }) {
  const [open, setOpen] = useState<string | null>(null);
  return <OpenContext.Provider value={{ open, setOpen }}>{children}</OpenContext.Provider>;
}

// Same pattern as the theme: a class on <html>, saved in localStorage, set before first paint by
// the script in layout.tsx so the buttons never flash in for someone who turned them off.
const watchHtmlClass = (change: () => void) => {
  const observer = new MutationObserver(change);
  observer.observe(document.documentElement, { attributeFilter: ["class"] });
  return () => observer.disconnect();
};

export function DocsToggle() {
  const { setOpen } = useContext(OpenContext);
  const on = useSyncExternalStore(
    watchHtmlClass,
    () => !document.documentElement.classList.contains("docs-off"),
    () => true,
  );
  function toggle() {
    const off = document.documentElement.classList.toggle("docs-off");
    if (off) setOpen(null);
    try {
      localStorage.setItem("docs", off ? "off" : "on");
    } catch {}
  }
  return (
    <button
      onClick={toggle}
      aria-pressed={on}
      aria-label={on ? "Hide help on the page" : "Show help on the page"}
      data-tip={on ? "Hide help on the page" : "Show help on the page"}
      className={`tip rounded-full p-2 hover:text-foreground ${on ? "bg-accent-soft text-foreground" : "text-muted hover:bg-accent-soft"}`}
    >
      {on ? (
        // On: a solid circle with the question mark cut out of it.
        <svg viewBox="0 0 24 24" className="h-5 w-5" aria-hidden="true">
          <circle cx="12" cy="12" r="10" fill="currentColor" />
          <path d="M9.5 9.3a2.6 2.6 0 0 1 5 .9c0 1.7-2.5 2.2-2.5 3.8" fill="none" stroke="var(--card)" strokeWidth="2" strokeLinecap="round" />
          <circle cx="12" cy="17.2" r="1.1" fill="var(--card)" />
        </svg>
      ) : (
        // Off: the outline, struck through.
        <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
          <circle cx="12" cy="12" r="9" />
          <path d="M9.5 9.3a2.6 2.6 0 0 1 5 .9c0 1.7-2.5 2.2-2.5 3.8" strokeLinecap="round" />
          <circle cx="12" cy="17" r="0.6" fill="currentColor" />
          <path d="M4 4l16 16" strokeLinecap="round" />
        </svg>
      )}
    </button>
  );
}

type Place = { top: number; left: number; maxHeight: number };

// Beside the region if it fits there (right, then left), else below or above it, shrinking to
// the larger gap when neither has room for the whole note. Never over the region itself.
function place(region: DOMRect, button: DOMRect, height: number): Place {
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  const width = Math.min(WIDTH, vw - 2 * EDGE);
  const h = Math.min(height, MAX_HEIGHT, vh - 2 * EDGE);
  const clampTop = (t: number) => Math.min(Math.max(t, EDGE), vh - h - EDGE);
  const clampLeft = (l: number) => Math.min(Math.max(l, EDGE), vw - width - EDGE);

  if (vw - region.right - GAP - EDGE >= width)
    return { top: clampTop(button.top), left: region.right + GAP, maxHeight: h };
  if (region.left - GAP - EDGE >= width)
    return { top: clampTop(button.top), left: region.left - GAP - width, maxHeight: h };

  const below = vh - region.bottom - GAP - EDGE;
  const above = region.top - GAP - EDGE;
  const left = clampLeft(button.right - width);
  if (below >= h) return { top: region.bottom + GAP, left, maxHeight: h };
  if (above >= h) return { top: region.top - GAP - h, left, maxHeight: h };
  if (below >= above) return { top: region.bottom + GAP, left, maxHeight: Math.max(below, 0) };
  const fit = Math.max(above, 0);
  return { top: region.top - GAP - fit, left, maxHeight: fit };
}

export function Help({ title, children, className = "" }: { title: string; children: React.ReactNode; className?: string }) {
  const id = useId();
  const { open, setOpen } = useContext(OpenContext);
  const shown = open === id;
  const button = useRef<HTMLButtonElement>(null);
  const note = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState<Place | null>(null);
  const [more, setMore] = useState(false);

  // True while the note has text below what it shows.
  const checkMore = useCallback(() => {
    const n = note.current;
    if (n) setMore(n.scrollTop + n.clientHeight < n.scrollHeight - 4);
  }, []);

  const region = useCallback(
    () => (button.current?.closest("[data-help]") as HTMLElement | null) ?? button.current?.parentElement ?? null,
    [],
  );

  const reposition = useCallback(() => {
    const r = region();
    if (!r || !button.current || !note.current) return;
    setPos(place(r.getBoundingClientRect(), button.current.getBoundingClientRect(), note.current.scrollHeight));
    requestAnimationFrame(checkMore);
  }, [region, checkMore]);

  useLayoutEffect(() => {
    if (!shown) return;
    // Runs before paint, so a position left from an earlier opening is never seen.
    reposition();
    const r = region();
    r?.setAttribute("data-help-active", "");
    note.current?.focus({ preventScroll: true });
    // The page holds still while a note is open; padding the width of the scrollbar it hides
    // keeps the layout from shifting sideways.
    const html = document.documentElement;
    const before = { overflow: html.style.overflow, paddingRight: html.style.paddingRight };
    html.style.paddingRight = `${window.innerWidth - html.clientWidth}px`;
    html.style.overflow = "hidden";
    const away = (e: PointerEvent) => {
      const t = e.target as Node;
      if (!note.current?.contains(t) && !button.current?.contains(t)) setOpen(null);
    };
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setOpen(null);
        button.current?.focus();
      }
    };
    window.addEventListener("scroll", reposition, true);
    window.addEventListener("resize", reposition);
    document.addEventListener("pointerdown", away);
    document.addEventListener("keydown", key);
    return () => {
      r?.removeAttribute("data-help-active");
      html.style.overflow = before.overflow;
      html.style.paddingRight = before.paddingRight;
      window.removeEventListener("scroll", reposition, true);
      window.removeEventListener("resize", reposition);
      document.removeEventListener("pointerdown", away);
      document.removeEventListener("keydown", key);
    };
  }, [shown, reposition, region, setOpen]);

  return (
    <>
      <button
        ref={button}
        type="button"
        onClick={() => {
          setOpen(shown ? null : id);
          // The first note opened stops the pulse on every "?" for good.
          document.documentElement.classList.remove("help-new");
          try {
            localStorage.setItem("help-seen", "1");
          } catch {}
        }}
        aria-expanded={shown}
        aria-controls={shown ? id : undefined}
        aria-label={`About: ${title}`}
        data-tip="What's this?"
        className={`help-button tip inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-accent align-middle text-sm font-bold text-card shadow-sm hover:opacity-85 ${
          shown ? "ring-2 ring-accent ring-offset-2 ring-offset-card" : ""
        } ${className}`}
      >
        ?
      </button>
      {shown && (
        <div
          ref={note}
          id={id}
          role="dialog"
          aria-label={title}
          tabIndex={-1}
          onScroll={checkMore}
          style={{
            position: "fixed",
            width: `min(${WIDTH}px, calc(100vw - ${2 * EDGE}px))`,
            top: pos?.top ?? 0,
            left: pos?.left ?? 0,
            maxHeight: pos?.maxHeight ?? MAX_HEIGHT,
            visibility: pos ? "visible" : "hidden",
          }}
          className="help-note z-50 overflow-y-auto overscroll-contain rounded-lg border border-grid bg-card p-4 text-sm leading-relaxed text-foreground shadow-lg outline-none"
        >
          <div className="sticky -top-4 -mx-4 -mt-4 mb-2 flex items-start justify-between gap-2 bg-card px-4 pt-4 pb-1">
            <div className="font-semibold">{title}</div>
            <button
              type="button"
              onClick={() => {
                setOpen(null);
                button.current?.focus();
              }}
              aria-label="Close"
              className="-mt-1 -mr-2 rounded-full p-1 text-muted hover:bg-accent-soft hover:text-foreground"
            >
              <svg viewBox="0 0 16 16" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
                <path d="M4 4l8 8M12 4l-8 8" strokeLinecap="round" />
              </svg>
            </button>
          </div>
          <div className="flex flex-col gap-2 text-muted [&_strong]:font-medium [&_strong]:text-foreground">{children}</div>
          {more && (
            <button
              type="button"
              onClick={() => note.current?.scrollBy({ top: note.current.clientHeight * 0.75, behavior: "smooth" })}
              className="sticky -bottom-4 -mx-4 -mb-4 mt-2 flex w-[calc(100%+2rem)] items-center justify-center gap-1.5 border-t border-line bg-card px-4 py-2 text-xs font-medium text-muted hover:text-foreground"
            >
              Scroll for more
              <svg viewBox="0 0 16 16" className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
                <path d="M4 6l4 4 4-4" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </button>
          )}
        </div>
      )}
    </>
  );
}
