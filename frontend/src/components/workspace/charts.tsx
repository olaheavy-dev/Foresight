"use client";

/**
 * Answer-canvas charts, inline SVG on tokens (same grammar as the Home chart): the baseline is a
 * solid forecast line with its likely range, scenarios are dashed in the scenario colour, the
 * buffer is dotted. Every chart has a visually hidden table with the same numbers.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { formatMoney, formatMoneyCompact, formatShortDate } from "@/lib/format";
import { monthTicks, niceScale, toTime } from "@/components/charts/model";

function useWidth(fallback = 720) {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(fallback);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const measure = () => {
      const w = Math.round(el.clientWidth);
      if (w > 0) setWidth(Math.max(260, w));
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return { ref, width };
}

export type ChartLine = {
  key: string;
  label: string;
  dates: string[];
  values: number[];
  kind: "forecast" | "scenario";
  band?: { lo: number[]; hi: number[] } | null;
};

const NARROW = 560;

export function LineChart({
  lines,
  currency,
  locale = "en-GB",
  buffer = null,
  bufferLabel,
  target = null,
  targetLabel,
  ariaLabel,
  height = 260,
  heightNarrow = 210,
}: {
  lines: ChartLine[];
  currency: string;
  locale?: string;
  buffer?: number | null;
  bufferLabel?: string;
  target?: number | null;
  targetLabel?: string;
  ariaLabel: string;
  height?: number;
  heightNarrow?: number;
}) {
  const { ref, width } = useWidth();
  const narrow = width < NARROW;
  const H = narrow ? heightNarrow : height;
  const money = (m: number) => formatMoney(m, currency, locale, { whole: true });

  const geo = useMemo(() => {
    const usable = lines.filter((l) => l.dates.length > 1 && l.dates.length === l.values.length);
    if (usable.length === 0) return null;
    const dates = usable.flatMap((l) => l.dates);
    const start = dates.reduce((a, b) => (a < b ? a : b));
    const end = dates.reduce((a, b) => (a > b ? a : b));
    if (!(toTime(end) > toTime(start))) return null;
    const values = usable.flatMap((l) => [...l.values, ...(l.band ? [...l.band.lo, ...l.band.hi] : [])]);
    if (buffer !== null) values.push(buffer);
    if (target !== null) values.push(target);
    values.push(0);
    const scale = niceScale(Math.min(...values), Math.max(...values), narrow ? 4 : 5);
    const m = { t: 18, r: narrow ? 14 : 18, b: 30, l: narrow ? 44 : 52 };
    const t0 = toTime(start);
    const t1 = toTime(end);
    const x = (iso: string) => m.l + ((toTime(iso) - t0) / (t1 - t0)) * (width - m.l - m.r);
    const y = (v: number) => m.t + ((scale.hi - v) * (H - m.t - m.b)) / (scale.hi - scale.lo);
    return { usable, start, end, scale, m, x, y };
  }, [lines, buffer, target, width, H, narrow]);

  if (!geo) {
    return (
      <p className="chart-empty" role="status">
        There isn’t enough data to draw this chart.
      </p>
    );
  }
  const { usable, scale, m, x, y } = geo;
  const path = (dates: string[], vals: number[]) =>
    dates.map((d, i) => `${i ? "L" : "M"}${x(d).toFixed(1)},${y(vals[i]).toFixed(1)}`).join("");
  const ticks = monthTicks(geo.start, geo.end, narrow ? 3 : 6);
  const first = usable[0];

  return (
    <div className="chart" ref={ref}>
      <svg viewBox={`0 0 ${width} ${H}`} width={width} height={H} role="img" aria-label={ariaLabel}>
        {scale.ticks.map((v) => (
          <g key={v}>
            <line x1={m.l} x2={width - m.r} y1={y(v)} y2={y(v)} className={v === 0 ? "cf-zero" : "ws-grid"} />
            <text x={m.l - 8} y={y(v) + 4} textAnchor="end" className="ws-tick">
              {formatMoneyCompact(v, currency, locale)}
            </text>
          </g>
        ))}
        {ticks.map((d) => (
          <text key={d} x={x(d)} y={H - 8} textAnchor="middle" className="ws-tick">
            {new Intl.DateTimeFormat(locale, { month: "short", timeZone: "UTC" }).format(new Date(`${d}T00:00:00Z`))}
          </text>
        ))}
        {usable.map((l) =>
          l.band && l.band.lo.length === l.dates.length && l.band.hi.length === l.dates.length ? (
            <path
              key={`${l.key}-band`}
              className={l.kind === "scenario" ? "ws-band-scenario" : "cf-band"}
              d={`${path(l.dates, l.band.hi)}${[...l.dates]
                .map((d, i) => ({ d, v: l.band!.lo[i] }))
                .reverse()
                .map((p) => `L${x(p.d).toFixed(1)},${y(p.v).toFixed(1)}`)
                .join("")}Z`}
            />
          ) : null,
        )}
        {buffer !== null ? (
          <>
            <line x1={m.l} x2={width - m.r} y1={y(buffer)} y2={y(buffer)} className="cf-buffer" />
            <text x={width - m.r - 2} y={y(buffer) - 6} textAnchor="end" className="ws-annot">
              {bufferLabel ?? `${money(buffer)} buffer`}
            </text>
          </>
        ) : null}
        {target !== null ? (
          <>
            <line x1={m.l} x2={width - m.r} y1={y(target)} y2={y(target)} className="ws-target" />
            <text x={m.l + 6} y={y(target) - 6} className="ws-annot">
              {targetLabel ?? `Target ${money(target)}`}
            </text>
          </>
        ) : null}
        {usable.map((l) => (
          <path
            key={l.key}
            d={path(l.dates, l.values)}
            className={l.kind === "scenario" ? "ws-scenario" : "cf-forecast"}
          />
        ))}
        {usable.map((l) => {
          const last = l.dates.length - 1;
          return (
            <circle
              key={`${l.key}-end`}
              cx={x(l.dates[last])}
              cy={y(l.values[last])}
              r={3.5}
              className={l.kind === "scenario" ? "ws-dot-scenario" : "cf-low"}
            />
          );
        })}
      </svg>
      <ul className="legend" aria-hidden="true">
        {usable.map((l) => (
          <li key={l.key}>
            <svg viewBox="0 0 26 10">
              <line x1="1" y1="5" x2="25" y2="5" className={l.kind === "scenario" ? "ws-scenario" : "cf-forecast"} />
            </svg>
            {l.label}
          </li>
        ))}
        {usable.some((l) => l.band) ? (
          <li>
            <svg viewBox="0 0 26 10">
              <rect x="1" y="1" width="24" height="8" rx="2" className="cf-band" />
            </svg>
            Likely range
          </li>
        ) : null}
        {buffer !== null ? (
          <li>
            <svg viewBox="0 0 26 10">
              <line x1="1" y1="5" x2="25" y2="5" className="cf-buffer" />
            </svg>
            {bufferLabel ?? `Buffer · ${money(buffer)}`}
          </li>
        ) : null}
      </ul>
      <div className="sr-only">
        {/* A div clips; a table ignores width: 1px and would widen the page. */}
        <table>
          <caption>{ariaLabel}</caption>
          <thead>
            <tr>
              <th scope="col">Date</th>
              {usable.map((l) => (
                <th key={l.key} scope="col">
                  {l.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {first.dates.map((d, i) => (
              <tr key={d}>
                <th scope="row">{formatShortDate(d, locale)}</th>
                {usable.map((l) => (
                  <td key={l.key}>{l.dates[i] === d ? money(l.values[i]) : ""}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export type BarRow = {
  key: string;
  label: string;
  minor: number;
  display: string;
  note?: string;
  baselineMinor?: number | null;
  baselineDisplay?: string | null;
  highlight?: boolean;
};

/** Ranked horizontal bars (spending by category or merchant), with an optional usual-level mark. */
export function HBars({ rows, label }: { rows: BarRow[]; label: string }) {
  const max = Math.max(1, ...rows.flatMap((r) => [Math.abs(r.minor), Math.abs(r.baselineMinor ?? 0)]));
  return (
    <ul className="hbars" aria-label={label}>
      {rows.map((r) => (
        <li key={r.key} className={r.highlight ? "hl" : undefined}>
          <span className="hb-label">{r.label}</span>
          <span className="hb-value num">{r.display}</span>
          <span className="hb-track" aria-hidden="true">
            <span className="hb-fill" style={{ width: `${(Math.abs(r.minor) / max) * 100}%` }} />
            {r.baselineMinor != null ? (
              <span className="hb-base" style={{ left: `${(Math.abs(r.baselineMinor) / max) * 100}%` }} />
            ) : null}
          </span>
          {r.note || r.baselineDisplay ? (
            <span className="hb-note">
              {[r.note, r.baselineDisplay ? `usual ${r.baselineDisplay}` : null].filter(Boolean).join(" · ")}
            </span>
          ) : null}
        </li>
      ))}
    </ul>
  );
}

/** Columns over time (e.g. weekly spend) with a dotted "usual" reference line. */
export function Columns({
  x: labels,
  values,
  baseline = null,
  currency,
  locale = "en-GB",
  ariaLabel,
}: {
  x: string[];
  values: number[];
  baseline?: number | null;
  currency: string;
  locale?: string;
  ariaLabel: string;
}) {
  const { ref, width } = useWidth();
  const narrow = width < NARROW;
  const H = narrow ? 200 : 230;
  const m = { t: 14, r: 8, b: 28, l: narrow ? 40 : 48 };
  const n = values.length;
  if (n === 0 || labels.length !== n) {
    return (
      <p className="chart-empty" role="status">
        There isn’t enough data to draw this chart.
      </p>
    );
  }
  const scale = niceScale(0, Math.max(...values, baseline ?? 0), narrow ? 4 : 5);
  const y = (v: number) => m.t + ((scale.hi - v) * (H - m.t - m.b)) / (scale.hi - scale.lo);
  const slot = (width - m.l - m.r) / n;
  const bw = Math.max(6, Math.min(36, slot * 0.62));
  const every = narrow ? Math.ceil(n / 4) : Math.ceil(n / 8);
  const money = (v: number) => formatMoney(v, currency, locale);
  return (
    <div className="chart" ref={ref}>
      <svg viewBox={`0 0 ${width} ${H}`} width={width} height={H} role="img" aria-label={ariaLabel}>
        {scale.ticks.map((v) => (
          <g key={v}>
            <line x1={m.l} x2={width - m.r} y1={y(v)} y2={y(v)} className={v === 0 ? "cf-zero" : "ws-grid"} />
            <text x={m.l - 8} y={y(v) + 4} textAnchor="end" className="ws-tick">
              {formatMoneyCompact(v, currency, locale)}
            </text>
          </g>
        ))}
        {values.map((v, i) => {
          const cx = m.l + slot * i + slot / 2;
          const above = baseline !== null && v > baseline;
          return (
            <g key={i}>
              <rect
                x={cx - bw / 2}
                y={y(Math.max(0, v))}
                width={bw}
                height={Math.max(0, y(0) - y(Math.max(0, v)))}
                rx={3}
                className={above ? "ws-col-hi" : "ws-col"}
              />
              {i % every === 0 ? (
                <text x={cx} y={H - 8} textAnchor="middle" className="ws-tick">
                  {labels[i]}
                </text>
              ) : null}
            </g>
          );
        })}
        {baseline !== null ? (
          <line x1={m.l} x2={width - m.r} y1={y(baseline)} y2={y(baseline)} className="ws-usual" />
        ) : null}
      </svg>
      <ul className="legend" aria-hidden="true">
        <li>
          <svg viewBox="0 0 26 10">
            <rect x="5" y="0" width="16" height="10" rx="3" className="ws-col-hi" />
          </svg>
          {baseline !== null ? "Above your usual" : "Spend"}
        </li>
        {baseline !== null ? (
          <>
            <li>
              <svg viewBox="0 0 26 10">
                <rect x="5" y="0" width="16" height="10" rx="3" className="ws-col" />
              </svg>
              At or below usual
            </li>
            <li>
              <svg viewBox="0 0 26 10">
                <line x1="1" y1="5" x2="25" y2="5" className="ws-usual" />
              </svg>
              Usual · {money(baseline)}
            </li>
          </>
        ) : null}
      </ul>
      <div className="sr-only">
        {/* A div clips; a table ignores width: 1px and would widen the page. */}
        <table>
          <caption>{ariaLabel}</caption>
          <tbody>
            {values.map((v, i) => (
              <tr key={i}>
                <th scope="row">{labels[i]}</th>
                <td>{money(v)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
