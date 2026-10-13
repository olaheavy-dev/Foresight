/**
 * Pure chart geometry for CashFlowChart (no DOM), so it can be tested for NaN and edge cases.
 * Chart grammar (tokens.css, docs/04): observed history = solid ink · forecast = solid blue with
 * a P10–P90 band · buffer = dotted · a "Today" rule between observed and forecast.
 *
 * Mode "lows" (Home, Landing): today's balance, then the lowest balance before each payday with
 * its likely range — a calm line that answers "will I stay above my buffer?". Values stay in
 * integer minor units until they are drawn.
 */
import type { CashFlowForecastData } from "@/ui-contracts/types";

export type ObservedPoint = { date: string; value: number };
export type ForecastPoint = {
  date: string;
  value: number;
  p10: number;
  p90: number;
  /** A pay-cycle low (drawn as a marker). */
  low: boolean;
  /** "80%" etc., from the API, for pay-cycle lows only. */
  chance?: string;
  belowBuffer?: boolean;
};

export type LowsSeries = {
  history: ObservedPoint[];
  today: ObservedPoint | null;
  points: ForecastPoint[];
};

const finite = (n: unknown): n is number => typeof n === "number" && Number.isFinite(n);
const DAY = 86_400_000;
export const toTime = (iso: string) => Date.parse(`${iso}T00:00:00Z`);

/** Observed history plus today's balance and each pay-cycle low, with the band read from the
 *  forecast fan on the low's date. Points with a non-finite value are dropped, never drawn. */
export function lowsSeries(data: CashFlowForecastData, historyDays = 14): LowsSeries {
  const h = data.history;
  const since = toTime(data.as_of) - historyDays * DAY;
  const history: ObservedPoint[] = h.dates
    .map((date, i) => ({ date, value: h.balance_minor[i] }))
    .filter((p): p is ObservedPoint => finite(p.value) && toTime(p.date) >= since);

  const fan = data.forecast;
  const at = new Map(fan.dates.map((d, i) => [d, i]));
  const start = at.get(data.as_of) ?? 0;
  const todayValue = fan.p50[start];
  const today = finite(todayValue) && fan.dates.length > 0 ? { date: fan.dates[start], value: todayValue } : null;

  const lows: ForecastPoint[] = (data.pay_cycles ?? []).flatMap((c) => {
    const i = at.get(c.low_date);
    const value = c.low.minor;
    const p10 = i === undefined ? value : fan.p10[i];
    const p90 = i === undefined ? value : fan.p90[i];
    if (![value, p10, p90].every(finite)) return [];
    return [
      {
        date: c.low_date,
        value,
        p10: Math.min(p10, value),
        p90: Math.max(p90, value),
        low: true,
        chance: c.chance_below_buffer?.display,
        belowBuffer: c.below_buffer,
      },
    ];
  });

  const points: ForecastPoint[] = today
    ? [{ date: today.date, value: today.value, p10: today.value, p90: today.value, low: false }, ...lows]
    : lows;
  return { history, today, points };
}

/** The last day of the forecast and its P50/P10/P90, for "if nothing changes" copy. */
export function forecastEnd(data: CashFlowForecastData) {
  const f = data.forecast;
  const i = f.dates.length - 1;
  if (i < 0 || ![f.p50[i], f.p10[i], f.p90[i]].every(finite)) return null;
  return { date: f.dates[i], p50: f.p50[i], p10: f.p10[i], p90: f.p90[i] };
}

/** Round axis steps of 1, 2, 2.5 or 5 × 10^k (in minor units), at most `maxTicks` intervals. */
export function niceScale(min: number, max: number, maxTicks = 5) {
  const lo0 = Math.min(min, max);
  const hi0 = Math.max(min, max);
  const span = hi0 - lo0 || Math.abs(hi0) || 1;
  const raw = span / maxTicks;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => span / s <= maxTicks) ?? 10 * mag;
  const lo = Math.floor(lo0 / step) * step;
  let hi = Math.ceil(hi0 / step) * step;
  if (hi === lo) hi = lo + step;
  const ticks: number[] = [];
  for (let v = lo; v <= hi + step / 1e6; v += step) ticks.push(Math.round(v));
  return { lo, hi, step, ticks };
}

/** First-of-month ticks between start and end, thinned to at most `max` labels. */
export function monthTicks(startIso: string, endIso: string, max: number): string[] {
  const start = toTime(startIso);
  const end = toTime(endIso);
  if (!(end > start)) return [];
  const out: string[] = [];
  const d = new Date(start);
  d.setUTCDate(1);
  d.setUTCMonth(d.getUTCMonth() + 1);
  while (d.getTime() <= end) {
    out.push(d.toISOString().slice(0, 10));
    d.setUTCMonth(d.getUTCMonth() + 1);
  }
  const every = Math.max(1, Math.ceil(out.length / Math.max(1, max)));
  return out.filter((_, i) => i % every === 0);
}

export type Layout = {
  width: number;
  height: number;
  margin: { t: number; r: number; b: number; l: number };
  x: (iso: string) => number;
  y: (minor: number) => number;
  scale: ReturnType<typeof niceScale>;
  start: string;
  end: string;
};

/** Pixel mapping for a series. Returns null when there is nothing to draw. */
export function layout(
  series: LowsSeries,
  { width, height, buffer, narrow }: { width: number; height: number; buffer: number | null; narrow: boolean },
): Layout | null {
  const dates = [...series.history.map((p) => p.date), ...series.points.map((p) => p.date)];
  if (dates.length < 2) return null;
  const start = dates.reduce((a, b) => (a < b ? a : b));
  const end = dates.reduce((a, b) => (a > b ? a : b));
  if (toTime(end) - toTime(start) < DAY) return null;
  const values = [
    ...series.history.map((p) => p.value),
    ...series.points.flatMap((p) => [p.p10, p.p90, p.value]),
    ...(buffer === null ? [] : [buffer]),
    0,
  ];
  const scale = niceScale(Math.min(...values), Math.max(...values), narrow ? 4 : 5);
  const margin = { t: series.history.length ? 34 : 22, r: 12, b: 34, l: narrow ? 44 : 52 };
  const t0 = toTime(start);
  const t1 = toTime(end);
  const x = (iso: string) => margin.l + ((toTime(iso) - t0) / (t1 - t0)) * (width - margin.l - margin.r);
  const y = (v: number) => margin.t + ((scale.hi - v) * (height - margin.t - margin.b)) / (scale.hi - scale.lo);
  return { width, height, margin, x, y, scale, start, end };
}

/** Nearest point by date (for the hover tooltip). */
export function nearest<T extends { date: string }>(points: T[], time: number): T | null {
  let best: T | null = null;
  let bestGap = Infinity;
  for (const p of points) {
    const gap = Math.abs(toTime(p.date) - time);
    if (gap < bestGap) {
      best = p;
      bestGap = gap;
    }
  }
  return best;
}
