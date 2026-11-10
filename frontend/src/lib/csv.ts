/**
 * CSV for pasting into a spreadsheet. Cell text comes from tenants, contractors and message content, so it is
 * untrusted: a cell that starts with = + - @ (or a tab / carriage return) would run as a formula in Excel and
 * Sheets, so it gets a leading apostrophe. Quotes, commas and line breaks follow RFC 4180.
 */
const FORMULA_START = /^[=+\-@\t\r]/;

export function csvCell(value: unknown): string {
  let text = value === null || value === undefined ? "" : String(value);
  if (FORMULA_START.test(text)) text = `'${text}`;
  return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

export function toCsv(columns: string[], rows: Array<Record<string, unknown>>): string {
  const header = columns.map(csvCell).join(",");
  const body = rows.map((row) => columns.map((column) => csvCell(row[column])).join(","));
  return [header, ...body].join("\r\n");
}
