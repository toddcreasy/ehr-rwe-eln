"use client";

import { usePathname } from "next/navigation";
import {
  Children,
  useCallback,
  createContext,
  isValidElement,
  type ReactNode,
  useContext,
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";
import { createPortal } from "react-dom";
import { type Entry, GLOSSARY, type TermKey } from "./glossary";

// Help on the page: a switch in the header shows or hides every "?" button. Each button shows a
// note about one region of the page (the nearest element marked data-help) in a panel docked at
// the right edge, which the page makes room for. The panel opens on the page's own note when a
// visit starts with help on, follows to each new page's note, and closes only from its X or the
// header switch. Terms marked with <Term> show their definition on hover, focus, or tap.

const PANEL_WIDTH = 380;
const TIP_WIDTH = 288;
const EDGE = 12;
// The narrowest screen where the page makes room for the panel (globals.css, .help-panel-open).
const WIDE = 1100;
// The id of each page's own note (the one marked <Help page>).
const PAGE = "page";

type Tip = { key: TermKey; rect: DOMRect };
// Which note the panel shows, and on which page it was picked. null: the panel is closed.
type Active = { path: string; id: string } | null;

const HelpContext = createContext<{
  shown: string | null;
  show: (id: string) => void;
  close: () => void;
  register: (id: string, title: string) => () => void;
  panelEl: HTMLElement | null;
  setTip: (tip: Tip | null) => void;
}>({ shown: null, show: () => {}, close: () => {}, register: () => () => {}, panelEl: null, setTip: () => {} });

// The panel's launch state, also read by the script in layout.tsx before first paint: open when
// help is on and the screen is wide enough for the page to make room for it, unless the visitor
// closed it earlier in this browser session. Narrower, it waits for a "?".
const noChange = () => () => {};
function opensAtLaunch() {
  if (document.documentElement.classList.contains("docs-off")) return false;
  if (!matchMedia(`(min-width: ${WIDE}px)`).matches) return false;
  try {
    return sessionStorage.getItem("help-panel") !== "closed";
  } catch {
    return true;
  }
}
function rememberClosed(closed: boolean) {
  try {
    if (closed) sessionStorage.setItem("help-panel", "closed");
    else sessionStorage.removeItem("help-panel");
  } catch {}
}

export function HelpProvider({ children }: { children: ReactNode }) {
  const path = usePathname() ?? "/";
  // undefined until the visitor opens or closes anything: the launch state decides.
  const [active, setActive] = useState<Active | undefined>(undefined);
  const launch = useSyncExternalStore(noChange, opensAtLaunch, () => false);
  const [tip, setTip] = useState<Tip | null>(null);
  const [panelEl, setPanelEl] = useState<HTMLElement | null>(null);
  // The notes on the page now, by id, with their titles.
  const [notes, setNotes] = useState<ReadonlyMap<string, string>>(new Map());
  const register = useCallback((id: string, title: string) => {
    setNotes((m) => new Map(m).set(id, title));
    return () =>
      setNotes((m) => {
        const next = new Map(m);
        next.delete(id);
        return next;
      });
  }, []);

  // A note picked on another page, or one its page no longer shows, is gone; the panel shows
  // this page's own note instead, or says there is none.
  const open = active === undefined ? launch : active !== null;
  const wanted = !open ? null : active && active.path === path ? active.id : PAGE;
  const shown = wanted === null ? null : notes.has(wanted) ? wanted : notes.has(PAGE) ? PAGE : null;

  const show = (id: string) => {
    setActive({ path, id });
    setTip(null);
    rememberClosed(false);
  };
  const close = () => {
    setActive(null);
    setTip(null);
    rememberClosed(true);
  };

  // The page makes room for the panel (globals.css, .help-panel-open).
  useEffect(() => {
    if (!open) return;
    const html = document.documentElement;
    html.classList.add("help-panel-open");
    return () => html.classList.remove("help-panel-open");
  }, [open]);

  // A definition is placed where its term was; any scroll would leave it behind, so it goes. So
  // does a tap anywhere but a term, since a touch screen never hovers off or blurs it.
  useEffect(() => {
    if (!tip) return;
    const hide = () => setTip(null);
    const away = (e: PointerEvent) => {
      if (!(e.target as Element).closest?.("[data-term]")) setTip(null);
    };
    window.addEventListener("scroll", hide, true);
    window.addEventListener("resize", hide);
    document.addEventListener("pointerdown", away);
    return () => {
      window.removeEventListener("scroll", hide, true);
      window.removeEventListener("resize", hide);
      document.removeEventListener("pointerdown", away);
    };
  }, [tip]);

  return (
    <HelpContext.Provider value={{ shown, show, close, register, panelEl, setTip }}>
      {children}
      {open && (
        <aside
          aria-label="Help"
          style={{ width: PANEL_WIDTH }}
          className="fixed top-0 right-0 z-40 flex h-dvh max-w-full flex-col border-l border-grid bg-card font-sans text-sm shadow-lg"
        >
          <div className="flex items-start justify-between gap-2 border-b border-line px-5 py-4">
            <div className="text-base font-semibold text-foreground">{shown ? notes.get(shown) : "Help"}</div>
            <button
              type="button"
              onClick={close}
              aria-label="Close help"
              className="-mt-1 -mr-2 rounded-full p-1 text-muted hover:bg-accent-soft hover:text-foreground"
            >
              <svg viewBox="0 0 16 16" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
                <path d="M4 4l8 8M12 4l-8 8" strokeLinecap="round" />
              </svg>
            </button>
          </div>
          <div ref={setPanelEl} className="flex-1 overflow-y-auto overscroll-contain">
            {shown === null && <p className="px-5 py-4 text-muted">There is no help for this page.</p>}
          </div>
        </aside>
      )}
      {tip && <TermTip tip={tip} />}
    </HelpContext.Provider>
  );
}

// Same pattern as the theme: a class on <html>, saved in localStorage, set before first paint by
// the script in layout.tsx so the buttons never flash in for someone who turned them off.
const watchHtmlClass = (change: () => void) => {
  const observer = new MutationObserver(change);
  observer.observe(document.documentElement, { attributeFilter: ["class"] });
  return () => observer.disconnect();
};

export function DocsToggle() {
  const { show, close } = useContext(HelpContext);
  const on = useSyncExternalStore(
    watchHtmlClass,
    () => !document.documentElement.classList.contains("docs-off"),
    () => true,
  );
  function toggle() {
    const off = document.documentElement.classList.toggle("docs-off");
    if (off) close();
    else show(PAGE);
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

// "OMOP: Observational Medical Outcomes Partnership", but just "Apache Iceberg" when the name
// already says the short form.
const heading = (key: TermKey) => {
  const entry: Entry = GLOSSARY[key];
  if (!entry.name) return key;
  return entry.name.includes(key) ? entry.name : `${key}: ${entry.name}`;
};

// The definition beside a hovered or focused term: below it, or above when it is near the bottom
// of the screen. Fixed to the screen so a scrolling panel never clips it.
function TermTip({ tip }: { tip: Tip }) {
  const left = Math.min(Math.max(tip.rect.left, EDGE), window.innerWidth - TIP_WIDTH - EDGE);
  const below = window.innerHeight - tip.rect.bottom > 160;
  return (
    <div
      id="term-tip"
      role="tooltip"
      style={{
        position: "fixed",
        left,
        width: TIP_WIDTH,
        ...(below ? { top: tip.rect.bottom + 6 } : { bottom: window.innerHeight - tip.rect.top + 6 }),
      }}
      className="pointer-events-none z-[60] rounded-md bg-foreground px-3 py-2 font-sans text-xs leading-relaxed font-normal text-card shadow-lg"
    >
      <span className="block font-semibold">{heading(tip.key)}</span>
      {GLOSSARY[tip.key].def}
    </div>
  );
}

// A glossary term in a note: dotted underline, definition on hover, focus, or tap.
export function Term({ t, children }: { t: TermKey; children?: ReactNode }) {
  const { setTip } = useContext(HelpContext);
  const show = (el: HTMLElement) => setTip({ key: t, rect: el.getBoundingClientRect() });
  return (
    <button
      type="button"
      data-term=""
      aria-describedby="term-tip"
      onPointerEnter={(e) => e.pointerType === "mouse" && show(e.currentTarget)}
      onPointerLeave={(e) => e.pointerType === "mouse" && setTip(null)}
      onFocus={(e) => show(e.currentTarget)}
      onBlur={() => setTip(null)}
      onClick={(e) => show(e.currentTarget)}
      className="cursor-help underline decoration-dotted decoration-1 underline-offset-[3px] hover:text-foreground"
    >
      {children ?? t}
    </button>
  );
}

// Every <Term> in a note, in the order they appear, for the list at the foot of the panel.
function termsIn(node: ReactNode, found: Set<TermKey> = new Set()): Set<TermKey> {
  Children.forEach(node, (child) => {
    if (!isValidElement<{ children?: ReactNode; t?: TermKey }>(child)) return;
    if (child.type === Term && child.props.t) found.add(child.props.t);
    termsIn(child.props.children, found);
  });
  return found;
}

// page: this is the page's own note, the one the panel opens on.
export function Help({
  title,
  children,
  page = false,
  className = "",
}: {
  title: string;
  children: ReactNode;
  page?: boolean;
  className?: string;
}) {
  const uid = useId();
  const id = page ? PAGE : uid;
  const { shown: current, show, register, panelEl } = useContext(HelpContext);
  const shown = current === id;
  const button = useRef<HTMLButtonElement>(null);
  const note = useRef<HTMLDivElement>(null);

  // Before paint, so the panel never shows "no help" for a page that has some.
  useLayoutEffect(() => register(id, title), [register, id, title]);

  // Outline the region this note is about while the panel shows it.
  useLayoutEffect(() => {
    if (!shown) return;
    const region = (button.current?.closest("[data-help]") as HTMLElement | null) ?? button.current?.parentElement;
    region?.setAttribute("data-help-active", "");
    return () => region?.removeAttribute("data-help-active");
  }, [shown]);

  const terms = shown ? [...termsIn(children)] : [];

  return (
    <>
      <button
        ref={button}
        type="button"
        onClick={() => {
          // Clicking the "?" whose note is showing leaves it showing.
          show(id);
          requestAnimationFrame(() => note.current?.focus({ preventScroll: true }));
          // The first note opened stops the pulse on every "?" for good.
          document.documentElement.classList.remove("help-new");
          try {
            localStorage.setItem("help-seen", "1");
          } catch {}
        }}
        aria-expanded={shown}
        aria-controls={shown ? `${id}-note` : undefined}
        aria-label={`About: ${title}`}
        data-tip="What's this?"
        className={`help-button tip inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-accent align-middle text-sm font-bold text-card shadow-sm hover:opacity-85 ${
          shown ? "ring-2 ring-accent ring-offset-2 ring-offset-card" : ""
        } ${className}`}
      >
        ?
      </button>
      {shown &&
        panelEl &&
        createPortal(
          <div
            ref={note}
            id={`${id}-note`}
            role="region"
            aria-label={title}
            tabIndex={-1}
            className="px-5 py-4 leading-relaxed font-normal tracking-normal normal-case outline-none"
          >
            <div>
              <div className="flex flex-col gap-2 text-muted [&_strong]:font-medium [&_strong]:text-foreground">{children}</div>
              {terms.length > 0 && (
                <div className="mt-6 border-t border-line pt-4">
                  <h3 className="text-xs font-semibold tracking-wide text-foreground uppercase">Terms in this note</h3>
                  <dl className="mt-2 flex flex-col gap-2 text-muted">
                    {terms.map((k) => (
                      <div key={k}>
                        <dt className="font-medium text-foreground">{heading(k)}</dt>
                        <dd>{GLOSSARY[k].def}</dd>
                      </div>
                    ))}
                  </dl>
                </div>
              )}
            </div>
          </div>,
          panelEl,
        )}
    </>
  );
}
