/** A report as the Reports page shows it: every row is built from live API data, never typed in. */
export type ReportKind = "occupancy" | "arrears" | "maintenance" | "log";

export type ReportRow = Record<string, string | number>;

export interface ReportTemplate {
  id: ReportKind;
  name: string;
  description: string;
  period: string;
  columns: string[];
  rows: ReportRow[];
  /** What to say when there are no rows, e.g. why the report is empty. */
  emptyMessage: string;
  /** The source could not be read; the page shows an alert instead of a table. */
  failed: boolean;
  /** Roles that may open the report. */
  roles: readonly string[];
}
