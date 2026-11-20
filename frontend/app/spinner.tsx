// A small navy ring with a red arc (PilotBio's ink and route) for while a page's data is on its
// way. The text is for screen readers.
export default function Spinner({ label = "Loading" }: { label?: string }) {
  return (
    <div role="status" className="flex items-center gap-2 text-sm text-muted">
      <span
        aria-hidden="true"
        className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-accent/20 border-t-route"
      />
      <span>{label}…</span>
    </div>
  );
}
