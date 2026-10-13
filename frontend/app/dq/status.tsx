// Check status: the reserved status palette, in the stack order that passed the colorblind
// separation check (pass and fail never touch). Each status also has its own icon shape, so
// color never carries the meaning alone.

export type Status = "pass" | "na" | "fail" | "error";

export const STATUSES: Status[] = ["pass", "na", "fail", "error"];

export const STATUS_META: Record<Status, { label: string; color: string }> = {
  pass: { label: "Pass", color: "#0ca30c" },
  na: { label: "Not applicable", color: "#898781" },
  fail: { label: "Fail", color: "#d03b3b" },
  error: { label: "Error", color: "#ec835a" },
};

export type CheckResult = {
  check_id: string;
  check_name: string;
  check_level: string;
  check_description: string;
  cdm_table_name: string;
  cdm_field_name: string | null;
  category: string;
  subcategory: string | null;
  context: string;
  severity: string;
  num_violated_rows: number | null;
  pct_violated_rows: number | null;
  num_denominator_rows: number | null;
  threshold_value: number | null;
  notes_value: string | null;
  failed: boolean;
  passed: boolean;
  is_error: boolean;
  not_applicable: boolean;
  not_applicable_reason: string | null;
  error: string | null;
};

// DQD can mark a check both errored and not applicable (its field is missing); not applicable
// wins, matching how DQD scores it.
export function statusOf(r: CheckResult): Status {
  if (r.not_applicable) return "na";
  if (r.is_error) return "error";
  if (r.failed) return "fail";
  return "pass";
}

export function StatusIcon({ status, size = 14 }: { status: Status; size?: number }) {
  const color = STATUS_META[status].color;
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" aria-hidden="true" className="shrink-0">
      <circle cx="8" cy="8" r="7" fill={color} />
      {status === "pass" && (
        <path d="M4.5 8.2 7 10.5l4.5-5" fill="none" stroke="white" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      )}
      {status === "na" && <path d="M4.5 8h7" stroke="white" strokeWidth="2" strokeLinecap="round" />}
      {status === "fail" && (
        <path d="m5.2 5.2 5.6 5.6m0-5.6-5.6 5.6" stroke="white" strokeWidth="2" strokeLinecap="round" />
      )}
      {status === "error" && (
        <>
          <path d="M8 4.2v4.6" stroke="#0b0b0b" strokeWidth="2" strokeLinecap="round" />
          <circle cx="8" cy="11.6" r="1.1" fill="#0b0b0b" />
        </>
      )}
    </svg>
  );
}

export function StatusBadge({ status }: { status: Status }) {
  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap text-zinc-900 dark:text-zinc-100">
      <StatusIcon status={status} />
      {STATUS_META[status].label}
    </span>
  );
}
