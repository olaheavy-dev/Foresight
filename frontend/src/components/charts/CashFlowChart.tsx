"use client";

/**
 * Cash-flow chart, "lows" mode (Home, Landing): observed balance, a Today rule, then the lowest
 * balance before each payday with its P10–P90 likely range, the buffer dotted, and a marker on
 * every pay-cycle low (ringed when it is below the buffer). Ported from
 * design/hifi/assets/charts.js as inline SVG; every value comes from the API contract
 * (`CashFlowForecastData`). Colours are CSS classes on tokens, so theme changes need no redraw.
 * A visually hidden table carries the same numbers for screen readers.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import type { CashFlowForecastData } from "@/ui-contracts/types";
import { formatDayDate, formatMoney, formatMoneyCompact, formatShortDate } from "@/lib/format";
import { layout, lowsSeries, monthTicks, nearest, toTime, type ForecastPoint, type ObservedPoint } from "./model";

type Props = {
  data: CashFlowForecastData;
  currency: string;
  locale?: string;
  height?: number;
  heightNarrow?: number;
  /** Label the first pay-cycle low on the chart. */
  calloutFirstLow?: boolean;
  /** Heading the chart sits under, used in the data-table caption. */
  title?: string;
  /** Days of observed history shown before Today. */
  historyDays?: number;
};

const NARROW = 560;
const DEFAULT_WIDTH = 720;

function describe(data: CashFlowForecastData, currency: string, locale: string, historyDays: number): string {
  const s = lowsSeries(data, historyDays);
  const money = (m: number) => formatMoney(m, currency, locale, { whole: true });
  const parts: string[] = [];
  if (s.history.length) {
    parts.push(
      `Observed balance from ${formatShortDate(s.history[0].date, locale)} to ${formatShortDate(s.history[s.history.length - 1].date, locale)}.`,
    );
  }
  const lows = s.points.filter((p) => p.low);
  if (lows.length) {
    parts.push(
      `Then the lowest balance forecast before each payday, to ${formatShortDate(lows[lows.length - 1].date, locale)}.`,
    );
    const first = lows[0];
    const buffer = data.buffer_minor;
    const rel =
      buffer === null ? "" : first.value < buffer ? `, below the ${money(buffer)} buffer` : `, above the ${money(buffer)} buffer`;
    parts.push(`The first low is ${money(first.value)} on ${formatShortDate(first.date, locale)}${rel}.`);
  } else {
    parts.push("No pay-cycle lows are forecast yet.");
  }
  return parts.join(" ");
}

export function CashFlowChart({
  data,
  currency,
  locale = "en-GB",
  height = 300,
  heightNarrow = 230,
  calloutFirstLow = true,
  title = "Cash-flow forecast",
  historyDays = 14,
}: Props) {
  const host = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(DEFAULT_WIDTH);
  const [hover, setHover] = useState<{ x: number; label: string; rows: string[] } | null>(null);

  useEffect(() => {
    const el = host.current;
    if (!el) return;
    const measure = () => {
      const w = Math.round(el.clientWidth);
      if (w > 0) setWidth(Math.max(280, w));
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const series = useMemo(() => lowsSeries(data, historyDays), [data, historyDays]);
  const narrow = width < NARROW;
  const h = narrow ? heightNarrow : height;
  const geo = useMemo(
    () => layout(series, { width, height: h, buffer: data.buffer_minor, narrow }),
    [series, width, h, data.buffer_minor, narrow],
  );
  const aria = useMemo(() => describe(data, currency, locale, historyDays), [data, currency, locale, historyDays]);
  const money = (m: number) => formatMoney(m, currency, locale, { whole: true });

  if (!geo) {
    return (
      <p className="chart-empty" role="status">
        There isn’t enough data to draw a forecast yet.
      </p>
    );
  }

  const { x, y, margin: m, scale } = geo;
  const W = geo.width;
  const H = geo.height;
  const pts = series.points;
  const hist = series.history;
  const today = series.today;
  const lows = pts.filter((p) => p.low);
  const buffer = data.buffer_minor;
  const band =
    pts.length > 1
      ? `${pts.map((p) => `${x(p.date)},${y(p.p90)}`).join(" ")} ${[...pts]
          .reverse()
          .map((p) => `${x(p.date)},${y(p.p10)}`)
          .join(" ")}`
      : null;
  const observedLine = [...hist, ...(today && hist.length ? [today] : [])]
    .map((p: ObservedPoint) => `${x(p.date)},${y(p.value)}`)
    .join(" ");
  const ticks = monthTicks(geo.start, geo.end, narrow ? 4 : 7);
  const first = calloutFirstLow ? lows[0] : undefined;

  // Place the buffer label where no drawn point sits under it: right above the line, right
  // below it, then left above / below. Width is estimated from the 12px label font.
  const drawn = [...hist, ...pts].map((p) => ({ px: x(p.date), py: y(p.value) }));
  const labelSpot = (text: string, at: number) => {
    const w = text.length * 6.6 + 8;
    const ly = y(at);
    const candidates = [
      { x: W - m.r - 2, y: ly - 6, anchor: "end" as const },
      { x: W - m.r - 2, y: ly + 16, anchor: "end" as const },
      { x: m.l + 6, y: ly - 6, anchor: "start" as const },
      { x: m.l + 6, y: ly + 16, anchor: "start" as const },
    ];
    const clear = (c: (typeof candidates)[number]) => {
      const x0 = c.anchor === "end" ? c.x - w : c.x;
      return !drawn.some((d) => d.px > x0 - 8 && d.px < x0 + w + 8 && d.py > c.y - 18 && d.py < c.y + 8);
    };
    return candidates.find(clear) ?? candidates[0];
  };

  const onMove = (clientX: number, rect: DOMRect) => {
    const px = ((clientX - rect.left) / rect.width) * W;
    const t0 = toTime(geo.start);
    const t1 = toTime(geo.end);
    const t = t0 + ((px - m.l) / (W - m.l - m.r)) * (t1 - t0);
    if (today && hist.length && t < toTime(today.date)) {
      const p = nearest(hist, t);
      if (!p) return;
      setHover({ x: x(p.date), label: `${formatShortDate(p.date, locale)} · observed`, rows: [money(p.value)] });
      return;
    }
    const p = nearest<ForecastPoint>(pts, t);
    if (!p) return;
    const rows = [money(p.value)];
    if (p.p10 !== p.p90) rows.push(`Likely ${money(p.p10)} to ${money(p.p90)}`);
    else rows.push("Today’s balance");
    if (p.chance) rows.push(`${p.chance} chance below your buffer`);
    setHover({
      x: x(p.date),
      label: `${formatShortDate(p.date, locale)}${p.low ? " · lowest before payday" : ""}`,
      rows,
    });
  };

  return (
    <div className="chart" ref={host} style={{ ["--chart-h" as string]: `${H}px` }}>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        width={W}
        height={H}
        role="img"
        aria-label={aria}
        onMouseMove={(e) => onMove(e.clientX, e.currentTarget.getBoundingClientRect())}
        onMouseLeave={() => setHover(null)}
      >
        <g className="grid">
          {scale.ticks.map((v) => (
            <line key={`g${v}`} x1={m.l} x2={W - m.r} y1={y(v)} y2={y(v)} />
          ))}
        </g>
        <g className="axis">
          {scale.ticks.map((v) => (
            <text key={`t${v}`} x={m.l - 8} y={y(v) + 4} textAnchor="end">
              {formatMoneyCompact(v, currency, locale)}
            </text>
          ))}
          {ticks.map((iso) =>
            x(iso) < m.l + 14 ? null : (
              <text key={iso} x={x(iso)} y={H - m.b + 18} textAnchor="middle">
                {new Intl.DateTimeFormat(locale, { month: "short", timeZone: "UTC" }).format(new Date(`${iso}T00:00:00Z`))}
                {iso.slice(5, 7) === "01" ? ` ${iso.slice(2, 4)}` : ""}
              </text>
            ),
          )}
        </g>

        {buffer !== null ? (
          <>
            <line className="cf-buffer" x1={m.l} x2={W - m.r} y1={y(buffer)} y2={y(buffer)} />
            {(() => {
              const text = `${money(buffer)} buffer`;
              const spot = labelSpot(text, buffer);
              return (
                <text className="lbl halo" x={spot.x} y={spot.y} textAnchor={spot.anchor}>
                  {text}
                </text>
              );
            })()}
          </>
        ) : null}
        {scale.lo < 0 ? <line className="cf-zero" x1={m.l} x2={W - m.r} y1={y(0)} y2={y(0)} /> : null}

        {today && hist.length ? (
          <>
            <line className="cf-today" x1={x(today.date)} x2={x(today.date)} y1={m.t - 8} y2={H - m.b} />
            <text className="lbl" x={x(today.date) + 6} y={m.t - 10}>
              Today
            </text>
            <text className="lbl faint" x={x(today.date) - 6} y={m.t - 10} textAnchor="end">
              Observed
            </text>
          </>
        ) : null}

        {band ? <polygon className="cf-band" points={band} /> : null}
        {observedLine ? <polyline className="cf-observed" points={observedLine} /> : null}
        {pts.length > 1 ? (
          <polyline className="cf-forecast" points={pts.map((p) => `${x(p.date)},${y(p.value)}`).join(" ")} />
        ) : null}
        {lows.map((p) => (
          <g key={p.date}>
            <circle className="cf-low" cx={x(p.date)} cy={y(p.value)} r={4} />
            {buffer !== null && p.value < buffer ? (
              <circle className="cf-breach" cx={x(p.date)} cy={y(p.value)} r={8} />
            ) : null}
          </g>
        ))}

        {first ? (
          (() => {
            const cx = x(first.date);
            const cy = y(first.value);
            const right = cx < W / 2;
            const ly = y(scale.lo + (scale.hi - scale.lo) * 0.62);
            return (
              <g>
                <line className="cf-leader" x1={cx} x2={cx} y1={ly + 6} y2={cy - 9} />
                <text className="lbl strong halo" x={cx + (right ? 4 : -4)} y={ly} textAnchor={right ? "start" : "end"}>
                  {`Lowest · ${formatDayDate(first.date, locale)} · ${money(first.value)}`}
                </text>
              </g>
            );
          })()
        ) : null}

        {hover ? <line className="cf-cross" x1={hover.x} x2={hover.x} y1={m.t} y2={H - m.b} /> : null}
      </svg>
      <div
        className={hover ? "tip show" : "tip"}
        aria-hidden="true"
        style={{ left: hover ? `${Math.min(Math.max(hover.x - 80, 0), Math.max(0, W - 180))}px` : 0, top: `${m.t}px` }}
      >
        {hover ? (
          <>
            <div>{hover.label}</div>
            <strong className="num">{hover.rows[0]}</strong>
            {hover.rows.slice(1).map((r) => (
              <div key={r}>{r}</div>
            ))}
          </>
        ) : null}
      </div>

      <div className="sr-only">
      <table>
        <caption>{title}: data</caption>
        <thead>
          <tr>
            <th scope="col">Date</th>
            <th scope="col">Balance</th>
            <th scope="col">Likely range</th>
            <th scope="col">Note</th>
          </tr>
        </thead>
        <tbody>
          {hist.map((p) => (
            <tr key={`h${p.date}`}>
              <td>{formatShortDate(p.date, locale)}</td>
              <td>{money(p.value)}</td>
              <td>—</td>
              <td>Observed</td>
            </tr>
          ))}
          {lows.map((p) => (
            <tr key={`l${p.date}`}>
              <td>{formatShortDate(p.date, locale)}</td>
              <td>{money(p.value)}</td>
              <td>{`${money(p.p10)} to ${money(p.p90)}`}</td>
              <td>{`Lowest before payday${p.chance ? `, ${p.chance} chance below buffer` : ""}`}</td>
            </tr>
          ))}
        </tbody>
      </table>
      </div>
    </div>
  );
}
