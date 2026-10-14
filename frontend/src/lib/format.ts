/**
 * Money and date formatting for amounts the API returns in integer minor units (docs/07 §2).
 * Any currency: the number of minor digits comes from Intl (GBP 2, JPY 0, KWD 3), never from a
 * hardcoded table, and locale grouping follows the profile (en-GB "1,284.50", en-IN lakh).
 */

export function minorDigits(currency: string): number {
  return new Intl.NumberFormat("en", { style: "currency", currency }).resolvedOptions().maximumFractionDigits ?? 2;
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
  const parts = new Intl.NumberFormat(locale, { style: "currency", currency, maximumFractionDigits: 0 }).formatToParts(
    0,
  );
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

/** ISO timestamp → "09:14:06" in the profile's time zone. */
export function formatClock(iso: string, locale = "en-GB", timeZone = "Europe/London"): string {
  const t = Date.parse(iso);
  if (!Number.isFinite(t)) return "";
  return new Intl.DateTimeFormat(locale, {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
    timeZone,
  }).format(new Date(t));
}

/** Milliseconds → "6.4 s", "48 s", "2 min 5 s". */
export function formatDuration(ms: number, locale = "en-GB"): string {
  if (!(ms >= 0)) return "";
  const s = ms / 1000;
  if (s < 10) return `${new Intl.NumberFormat(locale, { maximumFractionDigits: 1 }).format(s)} s`;
  if (s < 60) return `${Math.round(s)} s`;
  const m = Math.floor(s / 60);
  const rest = Math.round(s - m * 60);
  return rest ? `${m} min ${rest} s` : `${m} min`;
}

/** Whole numbers with locale grouping: 18240 → "18,240". */
export function formatCount(n: number, locale = "en-GB"): string {
  return new Intl.NumberFormat(locale, { maximumFractionDigits: 0 }).format(n);
}

/** An estimated model cost in US dollars: "about $0.05" (never "$0.00" for a small non-zero cost). */
export function formatUsdEstimate(usd: number, locale = "en-GB"): string {
  if (usd > 0 && usd < 0.01) return "under $0.01";
  const digits = usd < 1 ? 2 : usd < 10 ? 2 : 0;
  const body = new Intl.NumberFormat(locale, {
    style: "currency",
    currency: "USD",
    currencyDisplay: "narrowSymbol",
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(usd);
  return `about ${body}`;
}

/**
 * A typed amount ("1,234.56", "£1234.5", "-40") as integer minor units of `currency`, or null
 * when it isn't a plain number. Grouping commas and the currency symbol are ignored; the decimal
 * point is ".", as the en-GB inputs here use.
 */
export function parseAmountMinor(text: string, currency: string): number | null {
  const cleaned = text.replace(/[\s,£$€₹¥]/g, "");
  if (!/^-?\d+(\.\d+)?$/.test(cleaned)) return null;
  const digits = minorDigits(currency);
  const [whole, fraction = ""] = cleaned.replace("-", "").split(".");
  if (fraction.length > digits) return null;
  const minor = Number(whole) * 10 ** digits + Number(fraction.padEnd(digits, "0") || 0);
  return cleaned.startsWith("-") ? -minor : minor;
}
