/**
 * Money and date formatting for amounts the API returns in integer minor units (docs/07 §2).
 * Any currency: the number of minor digits comes from Intl (GBP 2, JPY 0, KWD 3), never from a
 * hardcoded table, and locale grouping follows the profile (en-GB "1,284.50", en-IN lakh).
 */

function minorDigits(currency: string): number {
  return new Intl.NumberFormat("en", { style: "currency", currency }).resolvedOptions()
    .maximumFractionDigits ?? 2;
}

export function toMajor(minor: number, currency: string): number {
  return minor / 10 ** minorDigits(currency);
}

/** Full amount, e.g. £1,284.50. `whole` drops the minor units (rounded), e.g. £1,285. */
export function formatMoney(
  minor: number,
  currency: string,
  locale = "en-GB",
  { whole = false }: { whole?: boolean } = {},
): string {
  const digits = whole ? 0 : minorDigits(currency);
  return new Intl.NumberFormat(locale, {
    style: "currency",
    currency,
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(toMajor(minor, currency));
}

/** Axis labels: £0, £500, £1K, £2.5K, £1.2M. Built by hand (symbol from Intl) so the server
 *  and the browser render identical text, whatever their ICU versions. */
export function formatMoneyCompact(minor: number, currency: string, locale = "en-GB"): string {
  const major = toMajor(minor, currency);
  const abs = Math.abs(major);
  const parts = new Intl.NumberFormat(locale, { style: "currency", currency, maximumFractionDigits: 0 }).formatToParts(0);
  const symbol = parts.find((p) => p.type === "currency")?.value ?? currency;
  const symbolFirst = parts.findIndex((p) => p.type === "currency") < parts.findIndex((p) => p.type === "integer");
  const [n, unit] = abs >= 1e6 ? [abs / 1e6, "M"] : abs >= 1e3 ? [abs / 1e3, "K"] : [abs, ""];
  const digits = new Intl.NumberFormat(locale, { maximumFractionDigits: 1 }).format(n);
  const body = symbolFirst ? `${symbol}${digits}${unit}` : `${digits}${unit} ${symbol}`;
  return major < 0 ? `−${body}` : body;
}

const UTC = "UTC";

/** ISO date (YYYY-MM-DD) → "27 Oct". */
export function formatShortDate(iso: string, locale = "en-GB"): string {
  return new Intl.DateTimeFormat(locale, { day: "numeric", month: "short", timeZone: UTC }).format(
    new Date(`${iso}T00:00:00Z`),
  );
}

/** ISO date → "Tue 27 Oct". */
export function formatDayDate(iso: string, locale = "en-GB"): string {
  return new Intl.DateTimeFormat(locale, {
    weekday: "short",
    day: "numeric",
    month: "short",
    timeZone: UTC,
  }).format(new Date(`${iso}T00:00:00Z`));
}

/** ISO date → "27 Oct 2026". */
export function formatLongDate(iso: string, locale = "en-GB"): string {
  return new Intl.DateTimeFormat(locale, {
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: UTC,
  }).format(new Date(`${iso}T00:00:00Z`));
}
