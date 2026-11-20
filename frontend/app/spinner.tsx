// A small maroon ring for while a page's data is on its way. The text is for screen readers.
export default function Spinner({ label = "Loading" }: { label?: string }) {
  return (
    <div role="status" className="flex items-center gap-2 text-sm text-muted">
      <span
        aria-hidden="true"
        className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-accent/25 border-t-accent"
      />
      <span>{label}…</span>
    </div>
  );
}
